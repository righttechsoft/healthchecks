# Healthchecks - Cron Job Monitoring Service

## Project Overview

**Healthchecks** is a production-ready cron job monitoring service that listens for HTTP requests and email messages ("pings") from scheduled tasks and cron jobs. When a ping doesn't arrive on time, the system sends out alerts through various notification channels.

**Core Functionality:**
- Monitors scheduled tasks by expecting regular "pings" (HTTP requests or emails)
- Tracks check status (up, down, new, paused, grace period)
- Sends alerts through 25+ integration channels when checks fail
- Provides a web dashboard for managing checks and viewing status
- Offers both hosted service (healthchecks.io) and self-hosted options

---

## Technology Stack

### Backend
- **Django 5.2** - Web framework
- **Python 3.10+** - Programming language (supports up to Python 3.13)
- **Database Options:**
  - SQLite (default for development)
  - PostgreSQL (recommended for production)
  - MySQL/MariaDB

### Key Python Dependencies
- `aiosmtpd==1.4.6` - SMTP server for email pings
- `cronsim==2.6` - Cron expression parsing
- `django-compressor==4.5.1` - Static file compression
- `fido2==2.0.0` - WebAuthn 2FA support
- `oncalendar==1.1` - Systemd calendar expression parsing
- `psycopg==3.2.9` - PostgreSQL adapter
- `pycurl==7.45.6` - HTTP client library
- `pydantic==2.11.7` - Data validation
- `PyJWT[crypto]==2.10.1` - JWT token handling
- `pyotp==2.9.0` - TOTP support
- `segno==1.6.6` - QR code generation
- `statsd==4.0.1` - Metrics collection
- `whitenoise==6.9.0` - Static file serving

### Frontend Technologies
- **Bootstrap 5** - UI framework
- **jQuery 3.6.0** - DOM manipulation
- **Moment.js** - Date/time handling with timezone support
- **noUiSlider** - Range sliders
- **Selectize.js** - Enhanced select boxes
- **DOMPurify** - XSS sanitization
- **WebAuthn JSON** - FIDO2 browser API

---

## Project Structure

```
healthchecks/
├── hc/                          # Main Django project
│   ├── accounts/                # User authentication & profiles
│   │   ├── models.py            # Profile, Project, Member, Credential
│   │   ├── views.py             # Login, signup, settings
│   │   └── management/commands/ # User management commands
│   ├── api/                     # Core monitoring logic
│   │   ├── models.py            # Check, Ping, Channel, Flip, Notification
│   │   ├── views.py             # API endpoints
│   │   ├── transports.py        # Notification integrations (25+ channels)
│   │   └── management/commands/ # sendalerts, sendreports, smtpd
│   ├── front/                   # Web UI
│   │   ├── views.py             # Dashboard, check management
│   │   └── management/commands/ # Documentation rendering
│   ├── logs/                    # Logging infrastructure
│   ├── payments/                # Subscription management (stub)
│   ├── lib/                     # Shared utilities
│   │   ├── badges.py            # Status badge generation
│   │   ├── curl.py              # HTTP client utilities
│   │   ├── emails.py            # Email templates
│   │   ├── s3.py                # Object storage integration
│   │   └── statsd.py            # Metrics collection
│   ├── settings.py              # Django settings
│   ├── urls.py                  # URL routing
│   └── wsgi.py                  # WSGI application
├── static/                      # Static assets (CSS, JS, images)
├── templates/                   # Django templates
├── docker/                      # Docker configuration
│   ├── Dockerfile               # Multi-stage build
│   ├── docker-compose.yml       # Compose configuration
│   └── uwsgi.ini                # uWSGI configuration
├── manage.py                    # Django management script
└── requirements.txt             # Python dependencies
```

---

## Core Data Models

### User/Account Models (hc.accounts)

#### Profile
Extends Django User with application-specific settings.
- **Limits**: `check_limit`, `sms_limit`, `call_limit`, `team_limit`, `ping_log_limit`
- **Reports**: `reports` (off/daily/weekly/monthly), `next_report_date`
- **Nag settings**: `nag_period`, `next_nag_date`
- **2FA**: `totp`, `totp_created`
- **Theme**: `theme`, `sort`, `tz`
- **Relationship**: OneToOne with Django User

#### Project
Container for organizing checks and channels.
- **Fields**: `name`, `owner`, `api_key`, `api_key_readonly`, `badge_key`, `ping_key`
- **Configuration**: `show_slugs`
- **Relationships**: Belongs to User (owner), has many Checks, Channels, Members

#### Member
Team membership for project collaboration.
- **Fields**: `user`, `project`, `role` (readonly/regular/manager)
- **Features**: `transfer_request_date` for ownership transfers

#### Credential
WebAuthn credentials for hardware key authentication.
- **Fields**: `code`, `name`, `user`, `created`, `data`

### Monitoring Models (hc.api)

#### Check
Central model representing a monitoring check.
- **Identity**: `code` (UUID), `name`, `slug`, `tags`, `desc`
- **Configuration**:
  - `kind` (simple/cron/oncalendar)
  - `timeout`, `grace` - timing thresholds
  - `schedule`, `tz` - for cron/oncalendar types
- **Status**: `status` (up/down/new/paused), `alert_after`, `last_ping`, `last_start`
- **Filtering**: `methods`, `filter_subject`, `filter_body`, `success_kw`, `failure_kw`, `start_kw`
- **Statistics**: `n_pings`, `last_duration`
- **Features**: `manual_resume`, `has_confirmation_link`

#### Ping
Individual heartbeat/ping event.
- **Sequence**: `n` (auto-incrementing per check)
- **Type**: `kind` (success/start/fail/log/ign)
- **Metadata**: `scheme`, `remote_addr`, `method`, `ua`, `exitstatus`, `rid`
- **Body storage**: `body_raw` (≤100 bytes in DB) or `object_size` (>100 bytes in S3)

#### Flip
Status change event (up↔down transitions).
- **Fields**: `owner` (Check), `created`, `processed`
- **Change**: `old_status`, `new_status`
- **Reason**: `timeout`, `fail`, or `nag` (for repeat notifications)

#### Channel
Notification destination/integration.
- **Configuration**: `name`, `kind` (email/slack/webhook/etc), `value` (JSON config)
- **Status**: `email_verified`, `disabled`, `last_notify`, `last_error`
- **Relationships**: Many-to-many with Checks

#### Notification
Record of sent notification.
- **Fields**: `code`, `owner` (Check), `check_status`, `channel`, `created`, `error`

#### TokenBucket
Rate limiting using token bucket algorithm.
- **Fields**: `value` (identifier), `tokens`, `updated`
- **Used for**: Login attempts, API calls, SMS/phone limits

### Model Relationships
```
User
 ├─ Profile (1:1)
 ├─ Project (1:many as owner)
 └─ Member (1:many) → Project

Project
 ├─ Check (1:many)
 ├─ Channel (1:many)
 └─ Member (1:many) → User

Check
 ├─ Ping (1:many)
 ├─ Flip (1:many)
 ├─ Notification (1:many)
 └─ Channel (many:many)

Channel
 ├─ Notification (1:many)
 └─ Check (many:many)
```

---

## Key Features

### Check Management
- **Multiple check types:**
  - **Simple**: Expect pings at regular intervals (timeout + grace period)
  - **Cron**: Schedule-based using cron expressions
  - **OnCalendar**: Systemd calendar expressions
- **Ping methods:** HTTP (GET/POST), Email, or via API
- **Ping types:** Success, Start (for tracking duration), Fail, Log, Ignored
- **Status filtering:** Filter pings by subject/body keywords
- **Tagging:** Organize checks with tags
- **Slugs:** Custom readable identifiers

### Monitoring & Alerting
- Real-time status calculation (up/down/grace/paused/started)
- Automatic status transitions based on ping timing
- Grace period before marking checks as down
- Manual resume option (prevent auto-recovery)
- **Nagging/Repeat notifications:** Send repeat alerts every hour for checks that remain down

### Notification Channels (25+ integrations)

**Communication:**
- Email, Slack, Discord, MS Teams, Mattermost, Rocket.Chat, Zulip, Matrix, Google Chat

**SMS/Phone:**
- Twilio (SMS/WhatsApp), Phone calls, Signal

**Incident Management:**
- PagerDuty, Opsgenie, VictorOps, PagerTree, Spike

**Developer Tools:**
- Webhook, Pushover, Pushbullet, GitHub Issues, Trello, ntfy

**Other:**
- Apprise (meta-integration supporting 70+ services), Telegram, Prometheus, Gotify, Shell Commands

### Team Collaboration
- Projects for organizing checks
- Team members with role-based access (read-only/member/manager)
- Project transfer functionality
- Shared notification channels

### Reporting
- Monthly/weekly/daily email reports
- Downtime statistics and uptime calculations
- Ping history with configurable retention
- Status badges for public display

### Security Features
- **WebAuthn (FIDO2)** two-factor authentication
- **TOTP** support
- Email-based passwordless login
- API key authentication (read-write and read-only)
- Rate limiting via TokenBucket
- External authentication via HTTP headers (LDAP/OAuth proxy)

---

## Management Commands

### Core Monitoring Commands

#### `sendalerts` - Main Alerting Daemon
**Purpose:** Continuously polls for checks going down and sends notifications.
- Creates Flip objects when checks change status
- Processes unprocessed flips and sends notifications
- **Implements nagging/repeat notifications** (hourly alerts for checks down >1 hour)
- Supports concurrent workers: `--num-workers N`
- PostgreSQL connection pooling: `--pool`

**Location:** `hc/api/management/commands/sendalerts.py`

**Deployment:** Must run continuously (systemd/supervisor)

#### `sendreports` - Report Generation
**Purpose:** Sends periodic email reports and nag reminders.
- Monthly/weekly/daily email reports
- Hourly/daily nag reminders
- Modes: One-shot or continuous (`--loop`)

**Location:** `hc/api/management/commands/sendreports.py`

#### `smtpd` - SMTP Listener
**Purpose:** Receives pings via email.
- Listens on configurable port (default: 2525)
- Email format: `<check-uuid>@<PING_EMAIL_DOMAIN>`

**Location:** `hc/api/management/commands/smtpd.py`

### Maintenance Commands

- **`pruneusers`** - Remove inactive accounts (>1 month old, never logged in)
- **`prunetokenbucket`** - Clean rate limiting records (>1 day old)
- **`pruneobjects`** - Clean S3 storage (remove orphaned ping bodies)
- **`prunepingsslow`** - Alternative ping pruning

### Integration Setup

- **`settelegramwebhook`** - Configure Telegram bot webhook
- **`submitchallenge`** - Submit Signal CAPTCHA challenges

### Account Management

- **`createsuperuser`** - Create admin account
- **`senddeletionscheduled`** - Account deletion notifications
- **`sendinactivitynotices`** - Inactive account warnings

### Documentation

- **`render_docs`** - Generate documentation
- **`pygmentize`** - Syntax highlighting
- **`populate_searchdb`** - Build documentation search index

---

## API Endpoints

### Ping Endpoints
```
GET/POST  /ping/<uuid>                 # Record successful ping
GET/POST  /ping/<uuid>/start           # Record start event
GET/POST  /ping/<uuid>/fail            # Record failure
GET/POST  /ping/<uuid>/log             # Log-only ping (no status change)
GET/POST  /ping/<uuid>/<exitstatus>    # Ping with exit status
GET/POST  /ping/<ping_key>/<slug>      # Ping by slug
```

### API v3 Endpoints

**Check Management:**
```
GET/POST  /api/v3/checks/              # List/create checks
GET/POST  /api/v3/checks/<uuid>        # Get/update single check
GET       /api/v3/checks/<sha1>        # Get check by unique key (readonly)
POST      /api/v3/checks/<uuid>/pause  # Pause check
POST      /api/v3/checks/<uuid>/resume # Resume check
```

**Ping History:**
```
GET       /api/v3/checks/<uuid>/pings/     # List pings
GET       /api/v3/checks/<uuid>/pings/<n>/body  # Get ping body
```

**Flip History:**
```
GET       /api/v3/checks/<uuid>/flips/    # List status changes
```

**Other:**
```
GET       /api/v3/channels/              # List notification channels
GET       /api/v3/badges/                # List badges
GET       /api/v3/metrics/               # Prometheus metrics
GET       /api/v3/status/                # Overall status
GET       /api/v3/bounces/               # Email bounce info
```

### Badge Endpoints
```
GET       /badge/<badge_key>/<signature>/<tag>.<fmt>  # Project badge
GET       /b/<states>/<badge_key>.<fmt>               # Single check badge
```

### Web UI Key Endpoints
```
GET       /                              # Homepage
GET       /projects/<code>/checks/       # Check list
GET       /checks/<code>/details/        # Check details
GET       /checks/<code>/log/            # Ping log
GET       /projects/<code>/integrations/ # Channel list
GET       /accounts/login/               # Login
GET       /accounts/profile/             # User settings
```

---

## Authentication & Authorization

### Authentication Methods

1. **Email-based (Passwordless)** - Primary method
   - User receives login link via email
   - 1-hour validity
   - Backend: `hc.accounts.backends.EmailBackend`

2. **Password-based** - Optional
   - Standard Django authentication
   - Backend: `hc.accounts.backends.ProfileBackend`

3. **WebAuthn (FIDO2)** - Hardware keys/biometrics
   - Requires HTTPS and `RP_ID` setting
   - Credentials stored in `Credential` model

4. **TOTP** - Software-based 2FA
   - QR code generation
   - Secrets stored in `Profile.totp`

5. **External Authentication** - Via reverse proxy headers
   - Uses `REMOTE_USER_HEADER`
   - For LDAP/OAuth integration
   - Backend: `hc.accounts.backends.CustomHeaderBackend`

6. **API Keys** - Project-level authentication
   - Read-Write (`hcw_*`) and Read-Only (`hcr_*`)
   - HMAC hashes stored in database

### Authorization

**Role-Based Access Control:**
- **Project Owner** - Full control
- **Manager** - Can manage checks, channels, and members
- **Member** - Can view and manage checks
- **Read-only** - View only

**Rate Limiting:**
- Login attempts: 20 per hour per IP
- Email login: 20 per hour per email
- Password attempts: 20 per day
- SMS/API calls also rate limited

**Sudo Mode:**
- Required for sensitive operations
- Re-authentication for: password changes, account closure, adding 2FA

---

## Notification System

### Transport Architecture

The notification system is implemented in `hc/api/transports.py` with a base `Transport` class and specific implementations for each integration.

**Base Transport Interface:**
```python
class Transport:
    def notify(self, flip: Flip, notification: Notification) -> None
    def is_noop(self, status: str) -> bool
    def down_checks(self, check: Check) -> list[Check] | None
    def last_ping(self, flip: Flip) -> Ping | None
```

### Notification Flow

1. **Status Change Detection** (`sendalerts` command):
   - Polls checks with `alert_after` in the past
   - Calculates current status
   - Creates `Flip` object if status changed

2. **Flip Processing**:
   - `Flip.select_channels()` determines which channels to notify
   - Excludes disabled channels
   - Excludes channels where `is_noop()` returns True
   - Sorts by `last_notify_duration` (fastest first)

3. **Notification Sending**:
   - `Channel.notify(flip)` creates `Notification` record
   - Calls transport's `notify()` method
   - Handles `TransportError` exceptions
   - Updates channel status (last_notify, last_error, disabled)

4. **Concurrent Processing**:
   - Uses `ThreadPoolExecutor` for parallel notifications
   - Configurable worker count
   - Prevents blocking on slow integrations

### Special Features

- **Conditional Notifications**: Webhooks can specify separate URLs for up/down events
- **Up/Down Filtering**: Email, SMS, Phone can notify only on specific status changes
- **Template Variables**: Webhooks support variables like $NAME, $STATUS, $JSON
- **Retry Logic**: Failed notifications marked as disabled (permanent errors) or retried
- **Nagging**: Repeat notifications every hour for checks that remain down (reason="nag")

---

## Background Jobs & Scheduled Tasks

### Long-Running Daemons

**`sendalerts`** - Alert Processing (REQUIRED)
- Main monitoring loop
- Detects checks going down
- Processes flips and sends notifications
- Handles nagging/repeat notifications
- **Must run continuously**

**`sendreports`** - Report Distribution (RECOMMENDED)
- Sends periodic reports
- Sends nag reminders
- Can run with `--loop` flag

**`smtpd`** - Email Ping Receiver (OPTIONAL)
- Accepts pings via email
- Port 2525 by default

### Periodic Tasks (via Cron/Systemd Timers)

- **`pruneusers`** - Daily/weekly (remove inactive accounts)
- **`prunetokenbucket`** - Daily (clean rate limiting)
- **`pruneobjects`** - Monthly (clean S3 storage)
- **`senddeletionscheduled`** - Daily
- **`sendinactivitynotices`** - Daily

### Automatic Cleanup

- **Ping pruning**: Automatic after every 100 pings
- **Flip/Notification pruning**: Automatic (keeps 93 days)
- **Old ping bodies**: Removed from S3 during new uploads

---

## Configuration

Configuration sources (priority order):
1. **`hc/local_settings.py`** (highest priority, optional, gitignored)
2. **Environment Variables**
3. **Default Values** (in settings.py)

### Core Settings

**Site Configuration:**
```python
SECRET_KEY               # Cryptographic signing (REQUIRED in production)
DEBUG                    # Debug mode (default: True)
SITE_ROOT                # Base URL, e.g., "https://example.com"
SITE_NAME                # Display name (default: "Mychecks")
SITE_LOGO_URL            # Custom logo URL
ALLOWED_HOSTS            # Defaults to domain from SITE_ROOT
```

**Database:**
```python
DB                       # postgres/mysql/mariadb
DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT
DB_CONN_MAX_AGE          # Connection pooling (PostgreSQL)
DB_SSLMODE               # SSL mode for PostgreSQL
```

**Email:**
```python
DEFAULT_FROM_EMAIL       # Sender address
EMAIL_HOST, EMAIL_PORT   # SMTP server
EMAIL_HOST_USER, EMAIL_HOST_PASSWORD
EMAIL_USE_TLS, EMAIL_USE_SSL
EMAIL_USE_VERIFICATION   # Verify email addresses
```

**Pings:**
```python
PING_ENDPOINT            # Ping URL base
PING_EMAIL_DOMAIN        # Domain for email pings
PING_BODY_LIMIT          # Max ping body size (default: 10000 bytes)
```

**Object Storage (S3):**
```python
S3_ACCESS_KEY, S3_SECRET_KEY
S3_ENDPOINT              # For S3-compatible services
S3_REGION, S3_BUCKET
S3_TIMEOUT               # Request timeout (default: 60s)
```

**Authentication:**
```python
RP_ID                    # WebAuthn relying party ID
REMOTE_USER_HEADER       # External auth header
```

**Features:**
```python
REGISTRATION_OPEN        # Allow new signups (default: True)
USE_PAYMENTS             # Enable payments (default: False)
```

**Integrations:**
Each integration has enable/disable flags and configuration:
```python
SLACK_CLIENT_ID, SLACK_CLIENT_SECRET, SLACK_ENABLED
DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET
PD_ENABLED, PD_APP_ID
TELEGRAM_BOT_NAME, TELEGRAM_TOKEN
TWILIO_ACCOUNT, TWILIO_AUTH, TWILIO_FROM
SIGNAL_CLI_SOCKET
# ... and many more
```

**Monitoring:**
```python
STATSD_HOST              # StatsD server
METRICS_KEY              # Auth for /metrics endpoint
```

---

## Database Schema

### Key Design Features

1. **UUID-based Public IDs**: All public-facing IDs use UUIDs (not sequential integers)
2. **Efficient Indexing**: Partial indexes for common queries
3. **Hybrid Storage**: Small ping bodies in DB, large ones in S3
4. **Denormalization**: `n_pings`, `last_ping` cached on Check for performance
5. **Automatic Cleanup**: Pings, flips, notifications pruned automatically

### Core Tables

**User Management:**
- `auth_user` (Django built-in)
- `accounts_profile` (1:1 with user)
- `accounts_project`
- `accounts_member` (many-to-many users and projects)
- `accounts_credential` (WebAuthn)

**Monitoring:**
- `api_check` - Central check model
- `api_ping` - Heartbeat events
- `api_flip` - Status changes
- `api_channel` - Notification integrations
- `api_notification` - Notification records
- `api_check_channels` (many-to-many)

**Other:**
- `api_tokenbucket` - Rate limiting
- `logs_record` - Database logging
- `payments_subscription` - Payment tracking (stub)

### Migration History
- Started around 2015 (migration 0001)
- Currently at 100+ migrations
- Active development with regular schema updates

---

## Testing

### Test Framework
- Django's built-in test framework (unittest-based)
- Custom test runner: `hc.api.tests.CustomRunner`
- Base test case: `hc.test.BaseTestCase`

### Test Structure

**170+ test files across:**
- `hc/accounts/tests/` - 30+ files (auth, profile, projects)
- `hc/api/tests/` - 80+ files (models, API, transports)
- `hc/front/tests/` - 60+ files (UI, integrations)
- `hc/lib/tests/` - Library utilities

### Test Utilities

**BaseTestCase provides:**
- Pre-created users: `self.alice`, `self.bob`, `self.charlie`
- Pre-created project: `self.project`
- CSRF-enabled client: `self.csrf_client`

**Custom assertions:**
- `assertEmailContains(fragment)`
- `assertEmailContainsText(fragment)`
- `assertEmailContainsHtml(fragment)`
- `assertEmailNotContains(fragment)`

### Running Tests

```bash
# All tests
./manage.py test

# Specific app
./manage.py test hc.api

# Specific test file
./manage.py test hc.api.tests.test_notify_email

# With coverage
coverage run --source='.' manage.py test
coverage report
```

### CI/CD
- GitHub Actions workflow: `.github/workflows/tests.yml`
- Coverage tracking with Coveralls
- High test coverage maintained

---

## Deployment

### Production Checklist

**Required Settings:**
```python
DEBUG = False
SECRET_KEY = "strong-random-key"  # Must be set!
ALLOWED_HOSTS = ["yourdomain.com"]
```

**Database:**
- **PostgreSQL recommended** for production
- MySQL/MariaDB also supported
- **SQLite NOT recommended** (locking issues)
- Enable connection pooling: `DB_CONN_MAX_AGE`
- **Regular backups essential**

**Web Server Options:**
1. **uWSGI** (recommended, used in Docker)
   ```bash
   uwsgi --http :8000 --module hc.wsgi
   ```

2. **Gunicorn**
   ```bash
   gunicorn hc.wsgi:application --bind 0.0.0.0:8000
   ```

3. **NEVER use `manage.py runserver`** - development only!

**Reverse Proxy:**
- Nginx or Apache for TLS termination
- Set `SECURE_PROXY_SSL_HEADER` if behind proxy

**Static Files:**
```bash
./manage.py compress
./manage.py collectstatic --noinput
```

### Background Processes

**Required:**
```bash
# Must run continuously
./manage.py sendalerts
```

**Recommended:**
```bash
# Reports and nags
./manage.py sendreports --loop

# Email pings (if needed)
./manage.py smtpd --port 2525
```

**Periodic (cron/systemd timers):**
```bash
# Daily
./manage.py pruneusers
./manage.py prunetokenbucket

# Monthly
./manage.py pruneobjects
```

### Docker Deployment

**Using docker-compose:**
```bash
cd docker
cp .env.example .env
# Edit .env with your settings
docker-compose up -d
```

**Pre-built image:**
```bash
docker run -d \
  --name healthchecks \
  -e SECRET_KEY="..." \
  -e DB="postgres" \
  -e DB_HOST="db" \
  -e DB_NAME="healthchecks" \
  -e DB_PASSWORD="..." \
  -p 8000:8000 \
  healthchecks/healthchecks:latest
```

**Docker features:**
- Multi-stage build (smaller image)
- Python 3.13.1
- uWSGI with automatic background process management
- Healthcheck included
- Non-root user
- Data volume: `/data`

### Database Migrations
```bash
./manage.py migrate
```
- Run before starting web server
- Safe to run if no changes needed
- Docker image runs automatically on startup

### Security

**TLS/HTTPS:**
- Required for WebAuthn
- Use Let's Encrypt with reverse proxy
- Set `SITE_ROOT` to `https://...`

**Firewall:**
- Web: 80/443
- SMTP (if used): 2525 or custom
- Database: Only from app server

**Secrets:**
- Store securely (environment variables/secret management)
- Never commit to version control

**Email:**
- Configure SMTP for login links and alerts
- Set up SPF/DKIM/DMARC

### Monitoring

**Application:**
- Monitor `sendalerts` process is running
- Check database connectivity
- Monitor disk space

**Metrics:**
- StatsD integration: `STATSD_HOST`
- Prometheus endpoint: `/api/v3/metrics/`
- Can require auth: `METRICS_KEY`

### Scaling Considerations

**Horizontal Scaling:**
- Web processes: Scale freely (stateless)
- Background workers: Multiple `sendalerts` OK (uses DB locking)
- Multiple workers: `--num-workers 4`

**Resource Requirements:**
- Minimal: 1 CPU, 512MB RAM
- Scales with number of checks and integrations

**Backup Strategy:**
- **Database backups** - Critical!
- Frequency: Daily minimum, hourly recommended
- Test restore procedures
- S3 bucket backups (if used)

### Update Process
```bash
# 1. Backup database
# 2. Pull new code
git pull
# 3. Install dependencies
pip install -r requirements.txt
# 4. Run migrations
./manage.py migrate
# 5. Collect static files
./manage.py compress
./manage.py collectstatic --noinput
# 6. Restart processes
systemctl restart healthchecks-web
systemctl restart healthchecks-sendalerts
```

---

## Recent Development

### Recent Commits
- **705ec5ae** - Refactor nagging logic to centralize in sendalerts command
- **620522da** - Second attempt to implement nagging notifications
- **4774b301** - Nagging logic added
- **485bdb99** - Add daily email report option

### Current Status
- **Branch**: master
- **Working directory**: Clean
- **Recent feature**: Nagging/repeat notifications for persistent failures

---

## Important Notes for Claude Code

### Nagging Notification Implementation

**Location:** `hc/api/management/commands/sendalerts.py:172-247`

**How it works:**
1. Runs every loop iteration in `sendalerts` command
2. Finds checks with `status="down"`
3. Filters for checks down >1 hour
4. Creates Flip with `reason="nag"` if last nagging flip was >1 hour ago
5. Notifications include "(repeat notification)" suffix

**Critical bug fixed (2025-12-10):**
- Original implementation looked at all "down" notifications
- This created a circular dependency (nag notifications blocked themselves)
- **Fixed by looking only at flips with `reason="nag"` instead of notifications**
- Now correctly sends repeat notifications every hour

**Code reference:** `sendalerts.py:213-224`

### Code Navigation

When referencing code, use pattern: `file_path:line_number`

Example:
- Nagging logic: `hc/api/management/commands/sendalerts.py:172`
- Check model: `hc/api/models.py:100`
- Channel notify: `hc/api/models.py:988`

### Development Commands

```bash
# Run development server
./manage.py runserver

# Run tests
./manage.py test

# Create migrations
./manage.py makemigrations

# Apply migrations
./manage.py migrate

# Create superuser
./manage.py createsuperuser

# Run sendalerts (testing)
./manage.py sendalerts

# Send reports
./manage.py sendreports
```

### Common Tasks

**Add new notification channel:**
1. Add transport class in `hc/api/transports.py`
2. Add channel setup view in `hc/front/views.py`
3. Add template in `templates/integrations/`
4. Add configuration variables in `hc/settings.py`
5. Add tests in `hc/api/tests/test_notify_*.py`
6. Update documentation

**Modify check logic:**
1. Update `Check` model in `hc/api/models.py`
2. Create migration: `./manage.py makemigrations`
3. Update API serialization in `hc/api/views.py`
4. Add tests
5. Update UI templates if needed

**Add new management command:**
1. Create file in `hc/*/management/commands/`
2. Inherit from `BaseCommand`
3. Implement `handle()` method
4. Add tests
5. Document in this file

---

## Summary

Healthchecks is a **production-ready, enterprise-grade cron job monitoring system** featuring:

- ✅ **Robust Django 5.2 architecture** with PostgreSQL/MySQL/SQLite support
- ✅ **Comprehensive monitoring** with 3 check types and 25+ notification channels
- ✅ **Advanced features**: WebAuthn 2FA, team collaboration, API access, status badges
- ✅ **Scalable design**: Concurrent workers, connection pooling, S3 storage
- ✅ **Well-tested**: 170+ test files with high coverage
- ✅ **Flexible deployment**: Docker, traditional server, or cloud platforms
- ✅ **Active development**: 100+ migrations, regular updates
- ✅ **Innovative alerting**: Repeat/nagging notifications for persistent failures

The codebase is well-organized, thoroughly documented, and follows Django best practices. Perfect for both self-hosted deployments and SaaS offerings.
