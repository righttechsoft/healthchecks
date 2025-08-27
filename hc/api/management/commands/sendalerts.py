from __future__ import annotations

import logging
import signal
import time
from argparse import ArgumentParser
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import timedelta as td
from threading import BoundedSemaphore
from types import FrameType
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils.timezone import now

from hc.api.models import Check, Flip
from hc.lib.statsd import statsd

logger = logging.getLogger("hc")


def notify(flip: Flip) -> str | None:
    # First, mark the flip as processed:
    q = Flip.objects.filter(id=flip.id, processed=None)
    num_updated = q.update(processed=now())
    if num_updated != 1:
        # Nothing got updated: another sendalerts process got there first.
        return None

    # Set or clear dates for followup nags
    check = flip.owner
    check.project.update_next_nag_dates()
    channels = flip.select_channels()
    if not channels:
        return None

    send_start = now()
    status_msg = f"{flip.new_status}"
    if flip.reason == "nag":
        status_msg += " (repeat notification)"
    logs = [f"{check.code} goes {status_msg}"]
    for ch in channels:
        notify_start = time.time()
        error = ch.notify(flip)
        secs = time.time() - notify_start
        code8 = str(ch.code)[:8]
        if error:
            logs.append(f"  {code8} ({ch.kind}) Error in {secs:.1f}s: {error}")
        else:
            logs.append(f"  {code8} ({ch.kind}) OK in {secs:.1f}s")

    statsd.timing("hc.sendalerts.dwellTime", send_start - flip.created)
    statsd.timing("hc.sendalerts.sendTime", now() - send_start)
    return "\n".join(logs)


class Command(BaseCommand):
    help = "Sends UP/DOWN email alerts"

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.seats = BoundedSemaphore(10)
        self.shutdown = False

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--num-workers",
            type=int,
            default=1,
            help="The number of concurrent worker processes to use",
        )

        parser.add_argument(
            "--pool",
            action="store_true",
            help="Use DB connection pool (PostgreSQL-only)",
        )

    def on_notify_done(self, future: Future[str | None]) -> None:
        close_old_connections()
        self.seats.release()

        try:
            if logs := future.result():
                self.stdout.write(logs)
        except Exception as exc:
            logger.error("Exception in notify", exc_info=exc)
            raise exc

    def process_one_flip(self) -> bool:
        """Find unprocessed flip, send notifications.

        Return True if the main loop should continue right away.

        Return False if the main loop should  wait a bit before continuing.
        (because either all workers are currently busy or there are currently no
        unprocessed flips in the database).

        """

        if not self.seats.acquire(timeout=1):
            return False  # Workers busy, main thread should wait a bit

        flip = Flip.objects.filter(processed=None).first()
        if flip is None:
            self.seats.release()
            return False  # No work found, main thread should wait a bit

        f = self.executor.submit(notify, flip)
        f.add_done_callback(self.on_notify_done)
        return True

    def handle_going_down(self) -> bool:
        """Process a single check going down.

        1. Find a check with alert_after in the past, and status other than "down".
        2. Calculate its current status.
        3. If calculation throws an exception, push alert_after forward and re-raise.
        4. If the current status is not "down", update alert_after and return.
        5. Update the check's status in the database to "down".
        6. If exactly 1 row gets updated, create a Flip object.

        """

        q = Check.objects.filter(alert_after__lt=now()).exclude(status="down")
        # Sort by alert_after, to avoid unnecessary sorting by id:
        check = q.order_by("alert_after").first()
        if check is None:
            return False

        old_status = check.status
        q = Check.objects.filter(id=check.id, status=old_status)

        try:
            status = check.get_status()
        except Exception as e:
            # Make sure we don't trip on this check again for an hour:
            # Otherwise sendalerts may end up in a crash loop.
            q.update(alert_after=now() + td(hours=1))
            # Then re-raise the exception:
            raise e

        if status != "down":
            # It is not down yet. Update alert_after
            q.update(alert_after=check.going_down_after())
            return True

        flip_time = check.going_down_after()
        # In theory, going_down_after() can return None, but:
        # get_status() just reported status "down", so "going_down_after()"
        # must be able to calculate precisely when the check's state flipped.
        assert flip_time

        # Atomically update status
        num_updated = q.update(alert_after=None, status="down")
        if num_updated != 1:
            # Nothing got updated: another worker process got there first.
            return True

        flip = Flip(owner=check)
        flip.created = flip_time
        flip.old_status = old_status
        flip.new_status = "down"
        flip.reason = "timeout"
        flip.save()

        return True

    def handle_repeat_notifications(self) -> bool:
        """Create repeat notifications for checks that have been down for a while.
        
        This method finds checks that:
        1. Are currently down
        2. Have been down for more than 1 hour (configurable)
        3. Haven't had a notification sent in the last 1 hour
        
        For each qualifying check, it creates a new Flip to trigger notifications.
        """
        # Time thresholds for repeat notifications
        repeat_interval = td(hours=1)  # Send repeat notifications every hour
        min_down_time = td(hours=1)    # Only send repeats after being down for 1 hour
        
        current_time = now()
        
        # Find checks that have been down for at least min_down_time
        down_threshold = current_time - min_down_time
        q = Check.objects.filter(status="down")
        
        # Filter for checks that have been down long enough
        # We look at the most recent flip to "down" status to determine how long it's been down
        checks_needing_repeat = []
        for check in q:
            # Get the most recent "down" flip for this check
            latest_down_flip = check.flip_set.filter(new_status="down").order_by("-created").first()
            if latest_down_flip and latest_down_flip.created <= down_threshold:
                # Check if we've sent a notification recently
                latest_notification = check.notification_set.filter(
                    check_status="down"
                ).order_by("-created").first()
                
                # If no notification or last notification was sent more than repeat_interval ago
                if (not latest_notification or 
                    latest_notification.created <= current_time - repeat_interval):
                    checks_needing_repeat.append((check, latest_down_flip))
        
        if not checks_needing_repeat:
            return False
        
        # Process the first check that needs a repeat notification
        check, original_flip = checks_needing_repeat[0]
        
        # Create a new flip to trigger notifications
        # Use reason "nag" to distinguish from original timeout/fail reasons
        flip = Flip(owner=check)
        flip.created = current_time
        flip.old_status = "down"  # Status hasn't actually changed
        flip.new_status = "down"  # Still down, but we want to notify again
        flip.reason = "nag"       # Mark this as a repeat/nag notification
        flip.save()
        
        return True

    def on_signal(self, signum: int, frame: FrameType | None) -> None:
        desc = signal.strsignal(signum)
        self.stdout.write(f"{desc}, finishing...\n")
        self.shutdown = True

    def handle(self, num_workers: int, pool: bool, **options: Any) -> str:
        if pool:
            db = settings.DATABASES["default"]
            # psycopg_pool requires non-persistent connections:
            db["CONN_MAX_AGE"] = 0
            options = db.setdefault("OPTIONS", {})
            options["pool"] = True

        self.seats = BoundedSemaphore(num_workers)
        self.executor = ThreadPoolExecutor(max_workers=num_workers)

        signal.signal(signal.SIGTERM, self.on_signal)
        signal.signal(signal.SIGINT, self.on_signal)

        self.stdout.write("sendalerts is now running\n")
        while not self.shutdown:
            # Create flips for any checks going down
            while self.handle_going_down() and not self.shutdown:
                pass

            # Create repeat notifications for checks that have been down for a while
            while self.handle_repeat_notifications() and not self.shutdown:
                pass

            # Submit unprocessed flips to the self.executor
            while self.process_one_flip() and not self.shutdown:
                pass

            # Either all workers are busy or there are no unprocessed flips.
            # Wait a bit:
            if not self.shutdown:
                time.sleep(2)

        self.executor.shutdown(wait=True)
        return "Done."
