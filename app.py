from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, date, timedelta
import os
import secrets
import shutil
import json
import smtplib
import threading
import logging
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr
from html import escape as html_escape
import urllib.error
import click
from itsdangerous import URLSafeSerializer, BadSignature
from email_validator import validate_email, EmailNotValidError

try:
    from dotenv import load_dotenv
    load_dotenv()  # loads .env for local DATABASE_URL / SECRET_KEY
except ImportError:
    pass

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'faatn-gate-secret-key-change-in-production-2026')
app.config['TEMPLATES_AUTO_RELOAD'] = True

# ---------- Search-engine verification & site identity ----------
# Prefer environment variables on Render (recommended). Fallbacks below use the
# real codes so verification works even if the env vars are not yet set.
#   GOOGLE_SITE_VERIFICATION  -> <meta name="google-site-verification" content="Hv5guTDnf-PC_m39QAAzh0sFAnGKCsTG-Jr9sbKabL4" />
#   BING_SITE_VERIFICATION    -> <meta name="msvalidate.01" content="E69E467EDBB0C6D57FFDA07288D20B4B" />
#   GOOGLE_HTML_FILE          -> (optional) e.g. google1234567890abcdef.html
#   BING_AUTH_CODE            -> (optional) code inside BingSiteAuth.xml
#   PUBLIC_SITE_URL           -> https://faatn-gate.com  (used in sitemap.xml and robots.txt)

GOOGLE_SITE_VERIFICATION = os.environ.get(
    'GOOGLE_SITE_VERIFICATION',
    'Hv5guTDnf-PC_m39QAAzh0sFAnGKCsTG-Jr9sbKabL4'
).strip()
BING_SITE_VERIFICATION = os.environ.get(
    'BING_SITE_VERIFICATION',
    'E69E467EDBB0C6D57FFDA07288D20B4B'
).strip()
GOOGLE_HTML_FILE = os.environ.get('GOOGLE_HTML_FILE', '').strip()
BING_AUTH_CODE = os.environ.get('BING_AUTH_CODE', '').strip()


@app.context_processor
def inject_seo_settings():
    """Make verification codes available to every template (only real codes are rendered)."""
    def real(code):
        return code if code and not code.startswith('YOUR_') else ''
    return {
        'google_site_verification': real(GOOGLE_SITE_VERIFICATION),
        'bing_site_verification': real(BING_SITE_VERIFICATION),
        'canonical_base': os.environ.get('PUBLIC_SITE_URL', '').rstrip('/') or request.url_root.rstrip('/'),
    }
# ---------- Database: PostgreSQL only (Render DATABASE_URL or local Postgres) ----------
# No SQLite. Set DATABASE_URL, e.g.:
#   postgresql://USER:PASSWORD@HOST:5432/faatn_gate
# Render may provide postgres:// — we normalise to postgresql://
database_url = os.environ.get('DATABASE_URL', '').strip()

# Local preview when Postgres is not installed (this environment / quick test)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Preview / local: SQLite when DATABASE_URL is not set
if not database_url:
    sqlite_path = os.path.join(BASE_DIR, 'faatn_gate.db').replace('\\', '/')
    database_url = f'sqlite:///{sqlite_path}'
    print('Using local SQLite for preview (set DATABASE_URL for PostgreSQL)')
    print(f'  DB file: {sqlite_path}')
    
if not database_url:
    # Optional local Postgres via discrete env vars
    pg_user = os.environ.get('PGUSER', 'postgres')
    pg_pass = os.environ.get('PGPASSWORD', '')
    pg_host = os.environ.get('PGHOST', 'localhost')
    pg_port = os.environ.get('PGPORT', '5432')
    pg_db = os.environ.get('PGDATABASE', 'faatn_gate')
    if pg_pass:
        database_url = f'postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}'
    else:
        database_url = os.environ.get(
            'SQLALCHEMY_DATABASE_URI',
            f'postgresql://{pg_user}:{pg_pass or "postgres"}@{pg_host}:{pg_port}/{pg_db}'
        )

if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

if not (database_url.startswith('postgresql') or database_url.startswith('sqlite')):
    raise RuntimeError(
        'FAATN-GATE requires PostgreSQL. Set DATABASE_URL=postgresql://... '
        'Or set ALLOW_SQLITE=1 for local preview only.'
    )

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
if database_url.startswith('sqlite'):
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'connect_args': {'check_same_thread': False},
    }
else:
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_size': int(os.environ.get('DB_POOL_SIZE', 5)),
        'max_overflow': int(os.environ.get('DB_MAX_OVERFLOW', 5)),
        'pool_timeout': int(os.environ.get('DB_POOL_TIMEOUT', 30)),
        'pool_pre_ping': True,
        'pool_recycle': int(os.environ.get('DB_POOL_RECYCLE', 280)),
    }

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads', 'avatars')
app.config['CHAT_UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads', 'chat')
app.config['BG_UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'images', 'backgrounds')
app.config['EVENT_UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads', 'events')
app.config['GALLERY_UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads', 'gallery')
app.config['PRODUCT_UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads', 'products')
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024  # 8 MB max
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
# Only this role may publish Events/News and Gallery images
PUBLISHER_ROLE = 'admin'

OCCUPATIONS = [
    'Automobile Mechanic',
    'Welder / Fabricator',
    'Electrician',
    'Plumber',
    'Refrigeration / AC Technician',
    'Solar Technician',
    'Borehole Technician',
    'Carpenter',
    'Mason',
    'Electronics Technician',
    'Motorcycle Technician',
    'Agricultural Machinery Technician',
    'Tailor / Fashion Designer',
    'Painter',
    'Tiler',
    'Generator Technician',
    'ICT / Computer Technician',
    'Massage Therapist',
    'Spa / Wellness Therapist',
    'Beauty Therapist',
    'Other',
]

NIGERIA_STATES = [
    'Abia', 'Adamawa', 'Akwa Ibom', 'Anambra', 'Bauchi', 'Bayelsa', 'Benue', 'Borno',
    'Cross River', 'Delta', 'Ebonyi', 'Edo', 'Ekiti', 'Enugu', 'FCT', 'Gombe', 'Imo',
    'Jigawa', 'Kaduna', 'Kano', 'Katsina', 'Kebbi', 'Kogi', 'Kwara', 'Lagos', 'Nasarawa',
    'Niger', 'Ogun', 'Ondo', 'Osun', 'Oyo', 'Plateau', 'Rivers', 'Sokoto', 'Taraba',
    'Yobe', 'Zamfara',
]

# Credibility listing categories — not everyone is a "FAATN artisan"
LISTING_CATEGORIES = {
    'public': 'Public Listing',
    'registered': 'FAATN-Registered',       # 🟢 Registered
    'verified': 'FAATN-Verified',           # 🔵 Verified
    'accredited': 'FAATN-Accredited',       # 🟣 Accredited
    'partner': 'Partner / Supplier',
}

SUPPLIER_CATEGORIES = [
    'Spare Parts', 'Solar Equipment', 'Electrical Materials', 'Plumbing Materials',
    'Welding Equipment', 'Automobile Parts', 'Refrigeration Parts', 'Machinery',
    'Tools', 'Safety Equipment', 'Fabrication Materials', 'Other',
]

INSTITUTION_TYPES = [
    'Tertiary Institution', 'Polytechnic', 'University', 'Research Institute',
    'Government Agency', 'Ministry', 'Industry / Manufacturer',
    'Financial Institution', 'Development Organisation', 'Other',
]

GEO_ZONES = {
    'North Central': ['Benue', 'Kogi', 'Kwara', 'Nasarawa', 'Niger', 'Plateau', 'FCT'],
    'North East': ['Adamawa', 'Bauchi', 'Borno', 'Gombe', 'Taraba', 'Yobe'],
    'North West': ['Jigawa', 'Kaduna', 'Kano', 'Katsina', 'Kebbi', 'Sokoto', 'Zamfara'],
    'South East': ['Abia', 'Anambra', 'Ebonyi', 'Enugu', 'Imo'],
    'South South': ['Akwa Ibom', 'Bayelsa', 'Cross River', 'Delta', 'Edo', 'Rivers'],
    'South West': ['Ekiti', 'Lagos', 'Ogun', 'Ondo', 'Osun', 'Oyo'],
}

# ---------- Role-based access control (RBAC) ----------
ROLES = {
    'artisan': 'Artisan',
    'technician': 'Technician',
    'engineer': 'Engineer / Technical Professional',
    'institution': 'Institution',
    'government': 'Government / Development Partner',
    'industry': 'Industry',
    'partner': 'Partner',
    'supplier': 'Supplier',
    'admin': 'Administrator',
}

MEMBER_ROLES = ('artisan', 'technician', 'engineer')  # member portal + directory + chat
STAKEHOLDER_ROLES = MEMBER_ROLES + ('institution', 'government', 'industry', 'partner', 'supplier')

MAX_ADMINS = 2  # hard limit: at most two Administrator accounts
MAX_NEWS_WORDS = 2000

# Trash lives OUTSIDE /static so deleted members' files are never publicly reachable
app.config['TRASH_FOLDER'] = os.environ.get('TRASH_FOLDER') or os.path.join(BASE_DIR, 'trash')
os.makedirs(app.config['TRASH_FOLDER'], exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['CHAT_UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['BG_UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['EVENT_UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['GALLERY_UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['PRODUCT_UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def is_publisher(user):
    """Admin publisher role (full moderation rights)."""
    return user.is_authenticated and getattr(user, 'role', None) == PUBLISHER_ROLE


def can_upload_content(user):
    """Only one designated user (admin) may upload to Gallery and Events/News."""
    return is_publisher(user)


def has_role(user, *roles):
    """True if authenticated user has one of the given roles."""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    return getattr(user, 'role', None) in roles


def is_admin(user):
    return has_role(user, 'admin')


def is_member(user):
    """Artisan / technician / engineer member portal users."""
    return has_role(user, *MEMBER_ROLES)


def role_required(*roles):
    """Decorator: require login + one of the listed roles."""
    from functools import wraps

    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            if not has_role(current_user, *roles):
                flash('Access denied for your role.', 'danger')
                return redirect(url_for('dashboard'))
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def admin_required(fn):
    """Decorator: admin only."""
    return role_required('admin')(fn)


def admin_count():
    """Number of accounts with role=admin."""
    return User.query.filter_by(role='admin').count()


def can_create_admin():
    return admin_count() < MAX_ADMINS


def word_count(text):
    if not text:
        return 0
    return len(text.strip().split())

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'


# ==================== EMAIL ====================
# Configure ONE of these on Render > Environment:
#
#   A) SMTP (Gmail app password, Brevo, Zoho, your host's mail server, ...)
#        MAIL_SERVER=smtp.example.com   MAIL_PORT=587   MAIL_USERNAME=...   MAIL_PASSWORD=...
#        MAIL_FROM=no-reply@yourdomain.ng   MAIL_USE_TLS=1  (or MAIL_USE_SSL=1 with port 465)
#
#   B) Resend HTTP API (works where outbound SMTP ports are blocked)
#        RESEND_API_KEY=re_xxx   MAIL_FROM=no-reply@yourdomain.ng   (domain must be verified in Resend)
#
# Optional: MAIL_FROM_NAME (default "FAATN-GATE"), VISIT_EMAIL=0 to turn off visitor e-mails
# (in-app visitor notifications stay on).
MAIL_SERVER = os.environ.get('MAIL_SERVER', '').strip()
MAIL_PORT = int(os.environ.get('MAIL_PORT', '587') or 587)
MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '').strip()
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', '0') == '1'
MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', '1') == '1'
MAIL_FROM = (os.environ.get('MAIL_FROM', '') or MAIL_USERNAME).strip()
MAIL_FROM_NAME = os.environ.get('MAIL_FROM_NAME', 'FAATN-GATE').strip()
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '').strip()
BREVO_API_KEY = os.environ.get('BREVO_API_KEY', '').strip()      # HTTPS API; works on Render free, accepts a single verified sender
ADMIN_NOTIFY_EMAIL = os.environ.get('ADMIN_NOTIFY_EMAIL', '').strip()  # optional: alert for new sign-ups / help requests
VISIT_EMAIL = os.environ.get('VISIT_EMAIL', '1') != '0'

mail_log = logging.getLogger('faatn.mail')


def mail_configured():
    return bool(MAIL_FROM and (RESEND_API_KEY or BREVO_API_KEY or MAIL_SERVER))


def mail_transport():
    """Which sender is active: 'resend', 'brevo', 'smtp' or None."""
    if not mail_configured():
        return None
    return 'resend' if RESEND_API_KEY else 'brevo' if BREVO_API_KEY else 'smtp'


def is_valid_email(addr):
    if not addr or '\n' in addr or '\r' in addr:
        return False
    try:
        validate_email(addr, check_deliverability=False)
        return True
    except EmailNotValidError:
        return False


def _deliver_email_raw(to_addr, subject, text_body, html_body, unsubscribe_url=None):
    """Blocking send. RAISES on any failure (callers decide what to do)."""
    subject = ' '.join(str(subject).split())[:200]          # no line breaks -> no header injection
    if RESEND_API_KEY:
        data = {
            'from': formataddr((MAIL_FROM_NAME, MAIL_FROM)),
            'to': [to_addr], 'subject': subject, 'text': text_body, 'html': html_body or None,
        }
        if unsubscribe_url:
            data['headers'] = {'List-Unsubscribe': f'<{unsubscribe_url}>'}
        req = urllib.request.Request(
            'https://api.resend.com/emails', data=json.dumps(data).encode('utf-8'), method='POST',
            headers={'Authorization': f'Bearer {RESEND_API_KEY}', 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
    elif BREVO_API_KEY:
        data = {'sender': {'name': MAIL_FROM_NAME, 'email': MAIL_FROM}, 'to': [{'email': to_addr}],
                'subject': subject, 'textContent': text_body}
        if html_body:
            data['htmlContent'] = html_body
        if unsubscribe_url:
            data['headers'] = {'List-Unsubscribe': f'<{unsubscribe_url}>'}
        req = urllib.request.Request(
            'https://api.brevo.com/v3/smtp/email', data=json.dumps(data).encode('utf-8'), method='POST',
            headers={'api-key': BREVO_API_KEY, 'accept': 'application/json', 'content-type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                resp.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f'Brevo rejected the email (HTTP {exc.code}): {exc.read().decode("utf-8", "ignore")[:200]}') from None
    else:
        msg = EmailMessage()
        msg['From'] = formataddr((MAIL_FROM_NAME, MAIL_FROM))
        msg['To'] = to_addr
        msg['Subject'] = subject
        if unsubscribe_url:
            msg['List-Unsubscribe'] = f'<{unsubscribe_url}>'
        msg.set_content(text_body)
        if html_body:
            msg.add_alternative(html_body, subtype='html')
        if MAIL_USE_SSL:
            server = smtplib.SMTP_SSL(MAIL_SERVER, MAIL_PORT, timeout=20)
        else:
            server = smtplib.SMTP(MAIL_SERVER, MAIL_PORT, timeout=20)
        try:
            if MAIL_USE_TLS and not MAIL_USE_SSL:
                server.starttls()
            if MAIL_USERNAME:
                server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.send_message(msg)
        finally:
            try:
                server.quit()
            except Exception:
                pass


def _deliver_email(to_addr, subject, text_body, html_body, unsubscribe_url=None):
    """Blocking send used by background threads; never raises."""
    try:
        _deliver_email_raw(to_addr, subject, text_body, html_body, unsubscribe_url)
        mail_log.info('Email sent to %s (%s)', to_addr, subject)
    except Exception as exc:  # network / auth / rejected recipient
        mail_log.error('Email to %s failed: %s', to_addr, exc)
        print(f'[mail] FAILED to send "{subject}" to {to_addr}: {exc}', flush=True)


def send_email_now(to_addr, subject, text_body, html_body=None):
    """Send immediately and report the reason on failure (for the admin "test email" button)."""
    if not mail_configured():
        return False, 'Email is not configured (set BREVO_API_KEY, RESEND_API_KEY or MAIL_SERVER, plus MAIL_FROM).'
    if not is_valid_email(to_addr):
        return False, f'Invalid recipient address: {to_addr!r}'
    try:
        _deliver_email_raw(to_addr, subject, text_body, html_body)
        return True, None
    except Exception as exc:
        return False, f'{type(exc).__name__}: {exc}'


def send_email(to_addr, subject, text_body, html_body=None, unsubscribe_url=None):
    """Queue an email in a background thread so the request is not slowed down.

    Returns False when mail is not configured or the address is not valid.
    """
    if not to_addr or not mail_configured() or not is_valid_email(to_addr):
        return False
    if app.testing:
        _deliver_email(to_addr, subject, text_body, html_body, unsubscribe_url)
    else:
        threading.Thread(target=_deliver_email, args=(to_addr, subject, text_body, html_body, unsubscribe_url),
                         daemon=True).start()
    return True


def send_many(jobs):
    """jobs = list of kwargs for _deliver_email. One background thread, sent one by one."""
    if not jobs or not mail_configured():
        return 0

    def run():
        for j in jobs:
            _deliver_email(**j)
    if app.testing:
        run()
    else:
        threading.Thread(target=run, daemon=True).start()
    return len(jobs)


def external_url(endpoint, **values):
    """Absolute URL; uses PUBLIC_SITE_URL when set (correct https domain behind Render's proxy)."""
    path = url_for(endpoint, **values)
    base = os.environ.get('PUBLIC_SITE_URL', '').strip().rstrip('/')
    if base:
        return base + path
    return url_for(endpoint, _external=True, **values)


def _email_shell(heading, body_html, button_label=None, button_url=None, unsubscribe_url=None):
    button = ''
    if button_label and button_url:
        button = (
            f'<p style="margin:24px 0;"><a href="{html_escape(button_url)}" '
            'style="background:#0d7a4f;color:#ffffff;padding:12px 22px;border-radius:8px;'
            f'text-decoration:none;font-weight:600;display:inline-block;">{html_escape(button_label)}</a></p>'
        )
    unsub = ''
    if unsubscribe_url:
        unsub = (f'<br><a href="{html_escape(unsubscribe_url)}" style="color:#6b7280;">'
                 'Unsubscribe from update emails</a> (password and security emails are always sent)')
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;'
        'border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;">'
        '<div style="background:#0d7a4f;color:#fff;padding:16px 24px;font-size:18px;font-weight:700;">FAATN-GATE</div>'
        f'<div style="padding:24px;color:#1f2937;line-height:1.55;"><h2 style="margin-top:0;color:#065f3c;">{html_escape(heading)}</h2>'
        f'{body_html}{button}</div>'
        '<div style="background:#f9fafb;color:#6b7280;padding:12px 24px;font-size:12px;">'
        f'Federation of Artisans and Technicians of Nigeria{unsub}</div></div>'
    )


def send_verification_email(user, token):
    """E-mail the verification link to a registered user. Returns True if queued."""
    link = external_url('verify_email', token=token)
    name = user.full_name or 'there'
    text = (
        f'Hello {name},\n\n'
        'Welcome to FAATN-GATE. Please verify your email address by opening this link:\n\n'
        f'{link}\n\n'
        'If you did not create this account, you can ignore this message.\n\n'
        '— FAATN-GATE'
    )
    html = _email_shell(
        'Verify your email address',
        f'<p>Hello {html_escape(name)},</p>'
        '<p>Welcome to FAATN-GATE. Please confirm your email address to finish setting up your account.</p>',
        'Verify my email', link,
    ) + f'<p style="font-size:12px;color:#6b7280;">Or copy this link: {html_escape(link)}</p>'
    sent = send_email(user.email, 'Verify your FAATN-GATE email address', text, html)
    if not sent:
        # Mail is not configured: keep the link in the server log only (never show it on the page).
        print(f'[mail] Email not configured. Verification link for {user.email}: {link}', flush=True)
    return sent



def send_reset_email(user, token):
    """E-mail the password-reset link (valid 2 hours). Returns True if queued."""
    link = external_url('reset_password', token=token)
    name = user.full_name or 'there'
    text = (
        f'Hello {name},\n\n'
        'We received a request to reset your FAATN-GATE password. Open this link within 2 hours:\n\n'
        f'{link}\n\n'
        'If you did not ask for this, ignore this message - your password stays the same.\n\n'
        '- FAATN-GATE'
    )
    html = _email_shell(
        'Reset your password',
        f'<p>Hello {html_escape(name)},</p>'
        '<p>We received a request to reset your FAATN-GATE password. The link works for 2 hours.</p>'
        '<p>If you did not ask for this, ignore this email - your password stays the same.</p>',
        'Reset my password', link,
    ) + f'<p style="font-size:12px;color:#6b7280;">Or copy this link: {html_escape(link)}</p>'
    sent = send_email(user.email, 'Reset your FAATN-GATE password', text, html)
    if not sent:
        print(f'[mail] Email not configured. Reset link for {user.email}: {link}', flush=True)
    return sent


def _unsub_serializer():
    return URLSafeSerializer(app.config['SECRET_KEY'], salt='faatn-email-unsub')


def unsubscribe_token(user_id):
    return _unsub_serializer().dumps(user_id)


def unsubscribe_link(user_id):
    return external_url('email_unsubscribe', token=unsubscribe_token(user_id))


def send_password_changed_email(user, by_admin=False):
    """Security notice. NEVER contains the password itself."""
    who = 'a FAATN administrator' if by_admin else 'you'
    link = external_url('login')
    text = (f'Hello {user.full_name or "there"},\n\nThe password for your FAATN-GATE account was just changed by {who}.\n\n'
            'If this was not expected, contact FAATN at faatnigeria@gmail.com straight away.\n\n- FAATN-GATE')
    html = _email_shell('Your password was changed',
                        f'<p>Hello {html_escape(user.full_name or "there")},</p>'
                        f'<p>The password for your FAATN-GATE account was just changed by {html_escape(who)}.</p>'
                        '<p>If this was not expected, contact FAATN at faatnigeria@gmail.com straight away.</p>',
                        'Sign in', link)
    return send_email(user.email, 'Your FAATN-GATE password was changed', text, html)


def send_welcome_email(user, token, hours):
    """Admin-created account: the user chooses their own password through a one-time link."""
    link = external_url('reset_password', token=token)
    text = (f'Hello {user.full_name},\n\nA FAATN administrator created a {ROLES.get(user.role, user.role)} account for you '
            f'on FAATN-GATE ({user.email}).\n\nChoose your password here (valid {hours} hours):\n{link}\n\n- FAATN-GATE')
    html = _email_shell('Your FAATN-GATE account is ready',
                        f'<p>Hello {html_escape(user.full_name)},</p>'
                        f'<p>A FAATN administrator created a {html_escape(ROLES.get(user.role, user.role))} account for you ({html_escape(user.email)}).</p>'
                        f'<p>Use the button below to choose your own password (valid {hours} hours).</p>',
                        'Set my password', link) + f'<p style="font-size:12px;color:#6b7280;">Or copy this link: {html_escape(link)}</p>'
    return send_email(user.email, 'Your FAATN-GATE account', text, html)


def email_notify_admin(subject, lines):
    if not ADMIN_NOTIFY_EMAIL:
        return False
    link = external_url('admin_dashboard')
    text = '\n'.join(lines) + f'\n\n{link}'
    html = _email_shell(subject, ''.join(f'<p>{html_escape(x)}</p>' for x in lines), 'Open admin dashboard', link)
    return send_email(ADMIN_NOTIFY_EMAIL, f'[FAATN-GATE] {subject}', text, html)


def broadcast_event_email(event):
    """Email a newly published Events / News item to every member who has not opted out."""
    link = external_url('events_news_detail', event_id=event.id)
    snippet = (event.description or '')[:400] + ('...' if len(event.description or '') > 400 else '')
    jobs = []
    for u in User.query.filter(User.email.isnot(None)).all():
        if u.email_notifications is False or not is_valid_email(u.email):
            continue
        unsub = unsubscribe_link(u.id)
        text = f'Hello {u.full_name},\n\n{event.title}\n\n{snippet}\n\nRead more: {link}\n\nUnsubscribe: {unsub}\n\n- FAATN-GATE'
        html = _email_shell(event.title, f'<p>Hello {html_escape(u.full_name or "")},</p><p style="white-space:pre-line;">{html_escape(snippet)}</p>',
                            'Read more', link, unsubscribe_url=unsub)
        jobs.append({'to_addr': u.email, 'subject': f'FAATN-GATE: {event.title}', 'text_body': text,
                     'html_body': html, 'unsubscribe_url': unsub})
    return send_many(jobs)


# ==================== MODELS ====================

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(20))
    role = db.Column(db.String(50), default='artisan')  # artisan, technician, engineer, institution, government, industry, partner, admin
    location_state = db.Column(db.String(50))
    location_lga = db.Column(db.String(50))
    location_community = db.Column(db.String(100))
    occupation = db.Column(db.String(100))
    specialty = db.Column(db.String(150))
    skills = db.Column(db.Text)  # JSON-like or comma separated
    experience_years = db.Column(db.Integer, default=0)
    portfolio = db.Column(db.Text)
    needs = db.Column(db.Text)
    verified = db.Column(db.Boolean, default=False)  # admin/platform verification (legacy flag)
    listing_category = db.Column(db.String(30), default='public')  # public | registered | verified | partner
    email_verified = db.Column(db.Boolean, default=False)
    verification_token = db.Column(db.String(64), nullable=True)
    reset_token = db.Column(db.String(64), nullable=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)
    profile_pic = db.Column(db.String(200), nullable=True)  # filename in uploads/avatars
    availability = db.Column(db.String(50), default='Available')  # Available | Busy | On project
    business_name = db.Column(db.String(150))
    workshop_address = db.Column(db.Text)
    certifications = db.Column(db.Text)
    references_text = db.Column(db.Text)
    whatsapp = db.Column(db.String(20))
    opening_hours = db.Column(db.String(120))
    products_supplied = db.Column(db.Text)  # for suppliers
    supplier_category = db.Column(db.String(80))  # SUPPLIER_CATEGORIES
    institution_type = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    # False = member opted out of update emails (password / security emails are always sent)
    email_notifications = db.Column(db.Boolean, default=True)

    def avatar_url(self):
        if self.profile_pic:
            return f'/static/uploads/avatars/{self.profile_pic}'
        return None

    # Relationships
    trainings = db.relationship('TrainingEnrollment', backref='user', lazy=True)
    innovations = db.relationship('Innovation', backref='user', lazy=True)
    applications = db.relationship('OpportunityApplication', backref='user', lazy=True)
    messages = db.relationship('Message', backref='recipient', lazy=True, foreign_keys='Message.recipient_id')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def listing_label(self):
        return LISTING_CATEGORIES.get(self.listing_category or 'public', 'Public Listing')

    @property
    def is_faatn_listed(self):
        """True for FAATN-Registered or FAATN-Verified members only."""
        return (self.listing_category or 'public') in ('registered', 'verified', 'accredited')

    def badge_class(self):
        return {
            'accredited': 'badge-accredited',
            'verified': 'badge-verified',
            'registered': 'badge-registered',
            'partner': 'badge-partner',
            'public': 'badge-public',
        }.get(self.listing_category or 'public', 'badge-public')


class Training(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    provider = db.Column(db.String(150))
    description = db.Column(db.Text)
    duration = db.Column(db.String(50))
    skill_gap = db.Column(db.String(100))
    location = db.Column(db.String(100))
    start_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class TrainingEnrollment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    training_id = db.Column(db.Integer, db.ForeignKey('training.id'), nullable=False)
    status = db.Column(db.String(30), default='enrolled')  # enrolled, completed, certified
    enrolled_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    certificate_code = db.Column(db.String(50))
    training = db.relationship('Training', backref='enrollments')


class Innovation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    problem = db.Column(db.Text)
    status = db.Column(db.String(50), default='submitted')  # submitted, screening, assessment, prototype, testing, demonstration, deployment
    stage = db.Column(db.String(50), default='idea')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Opportunity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    type = db.Column(db.String(50))  # job, contract, grant, project
    requirements = db.Column(db.Text)
    location = db.Column(db.String(100))
    skills_needed = db.Column(db.String(200))
    posted_by = db.Column(db.String(150))
    deadline = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class OpportunityApplication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    opportunity_id = db.Column(db.Integer, db.ForeignKey('opportunity.id'), nullable=False)
    status = db.Column(db.String(30), default='pending')  # pending, shortlisted, accepted, rejected
    cover_note = db.Column(db.Text)
    applied_at = db.Column(db.DateTime, default=datetime.utcnow)
    opportunity = db.relationship('Opportunity', backref='applications')


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # None = system message
    sender_name = db.Column(db.String(100))  # display name (system or user)
    subject = db.Column(db.String(200))
    body = db.Column(db.Text)
    image_filename = db.Column(db.String(200), nullable=True)  # optional chat image
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_messages')



class Event(db.Model):
    """FAATN Events / News — long write-up + optional image. Publish: admin only."""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)  # full article up to ~2000 words
    category = db.Column(db.String(20), default='event')  # event | news
    location = db.Column(db.String(150))
    event_date = db.Column(db.Date)
    event_time = db.Column(db.String(50))
    image_filename = db.Column(db.String(200), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship('User', foreign_keys=[created_by_id], backref='events_created')

    def image_url(self):
        if self.image_filename:
            return f'/static/uploads/events/{self.image_filename}'
        return None

    def word_count(self):
        if not self.description:
            return 0
        return len(self.description.split())


class GalleryItem(db.Model):
    """Public gallery images — upload restricted to admin (one publisher role)."""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    caption = db.Column(db.Text)
    image_filename = db.Column(db.String(200), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship('User', foreign_keys=[created_by_id], backref='gallery_items')

    def image_url(self):
        return f'/static/uploads/gallery/{self.image_filename}' 




class Product(db.Model):
    """Artisan / technician marketplace product or service with image gallery."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(80), default='product')  # product | service
    price = db.Column(db.String(80))  # free-text e.g. "₦5,000" or "Negotiable"
    image_filename = db.Column(db.String(200), nullable=True)  # legacy primary cover
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = db.relationship('User', backref=db.backref('products', lazy=True))
    images = db.relationship(
        'ProductImage',
        backref='product',
        lazy=True,
        cascade='all, delete-orphan',
        order_by='ProductImage.sort_order',
    )

    def image_url(self):
        """Cover image: first gallery image, else legacy single filename."""
        if self.images:
            return self.images[0].url()
        if self.image_filename:
            return f'/static/uploads/products/{self.image_filename}'
        return None

    def gallery_urls(self):
        """All image URLs for public gallery display."""
        urls = [img.url() for img in self.images]
        if not urls and self.image_filename:
            urls = [f'/static/uploads/products/{self.image_filename}']
        return urls


class ProductImage(db.Model):
    """One photo in a product/service gallery (multiple per listing)."""
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def url(self):
        return f'/static/uploads/products/{self.filename}'


class Review(db.Model):
    """Public reviews for marketplace products/services and for artisans."""
    id = db.Column(db.Integer, primary_key=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    rating = db.Column(db.Integer, nullable=False)  # 1–5
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    reviewer = db.relationship('User', foreign_keys=[reviewer_id], backref=db.backref('reviews_written', lazy=True))
    product = db.relationship('Product', backref=db.backref('reviews', lazy=True, cascade='all, delete-orphan'))
    target_user = db.relationship('User', foreign_keys=[target_user_id], backref=db.backref('reviews_received', lazy=True))

class HelpRequest(db.Model):
    """I Need Help — route problems to suitable registered technicians."""
    id = db.Column(db.Integer, primary_key=True)
    requester_name = db.Column(db.String(150))
    requester_phone = db.Column(db.String(20))
    requester_email = db.Column(db.String(120))
    location_state = db.Column(db.String(50))
    location_lga = db.Column(db.String(50))
    location_town = db.Column(db.String(100))
    problem_category = db.Column(db.String(100))
    description = db.Column(db.Text, nullable=False)
    urgency = db.Column(db.String(20), default='normal')  # normal | urgent
    status = db.Column(db.String(30), default='open')    # open | assigned | closed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(150))
    message = db.Column(db.Text)
    type = db.Column(db.String(30), default='info')  # info, success, warning, opportunity, training
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='notifications')


class TrashedUser(db.Model):
    """A deleted member kept in Trash (full copy of their data) until an admin
    permanently deletes it or restores it."""
    id = db.Column(db.Integer, primary_key=True)
    original_user_id = db.Column(db.Integer)
    email = db.Column(db.String(120))
    full_name = db.Column(db.String(150))
    role = db.Column(db.String(50))
    summary = db.Column(db.Text)            # human readable, e.g. "3 messages, 2 products"
    snapshot = db.Column(db.Text, nullable=False)  # JSON copy of the user and related rows
    deleted_at = db.Column(db.DateTime, default=datetime.utcnow)
    deleted_by_name = db.Column(db.String(150))


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def deliver_to_inbox(recipient_id, body, subject=None, sender_id=None, sender_name=None,
                     image_filename=None, notif_title=None, notif_type='info', commit=True):
    """Always put a message in the recipient's Messages inbox and create a notification.

    Used for peer chat, admin broadcasts, and system messages so artisans /
    technicians / anyone messaged sees it under Dashboard → Messages.
    """
    if sender_name is None and sender_id:
        sender = User.query.get(sender_id)
        sender_name = sender.full_name if sender else 'Member'
    if sender_name is None:
        sender_name = 'FAATN System'

    msg = Message(
        recipient_id=recipient_id,
        sender_id=sender_id,
        sender_name=sender_name,
        subject=subject or f'Message from {sender_name}',
        body=body or ('[Image]' if image_filename else ''),
        image_filename=image_filename,
    )
    db.session.add(msg)

    preview = (body or '')[:120]
    if body and len(body) > 120:
        preview += '…'
    if not preview and image_filename:
        preview = 'Sent an image'

    notif = Notification(
        user_id=recipient_id,
        title=notif_title or f'New message from {sender_name}',
        message=preview or subject or 'You have a new message in your inbox.',
        type=notif_type,
    )
    db.session.add(notif)

    if commit:
        db.session.commit()
    return msg


@app.route('/email/unsubscribe/<token>')
def email_unsubscribe(token):
    try:
        uid = _unsub_serializer().loads(token)
    except BadSignature:
        flash('That unsubscribe link is not valid.', 'danger')
        return redirect(url_for('index'))
    user = User.query.get(uid)
    if user:
        user.email_notifications = False
        db.session.commit()
    flash('You will no longer get update emails. Password and security emails are still sent.', 'info')
    return redirect(url_for('index'))


# ==================== ROUTES ====================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/robots.txt')
def robots_txt():
    """Search-engine robots file (Google, Bing, etc.)."""
    lines = [
        'User-agent: *',
        'Allow: /',
        'Disallow: /dashboard',
        'Disallow: /login',
        'Disallow: /register',
        'Disallow: /forgot-password',
        'Disallow: /reset-password/',
        'Disallow: /verify-email/',
        '',
        'User-agent: Googlebot',
        'Allow: /',
        '',
        'User-agent: bingbot',
        'Allow: /',
        '',
    ]
    site = os.environ.get('PUBLIC_SITE_URL', '').rstrip('/') or request.url_root.rstrip('/')
    lines.append(f'Sitemap: {site}/sitemap.xml')
    lines.append('')
    return app.response_class('\n'.join(lines), mimetype='text/plain')


@app.route('/sitemap.xml')
def sitemap_xml():
    """Sitemap for Google Search Console and Bing Webmaster Tools."""
    site = os.environ.get('PUBLIC_SITE_URL', '').rstrip('/') or request.url_root.rstrip('/')
    pages = [
        ('index', 1.0, 'daily'),
        ('about', 0.8, 'monthly'),
        ('gate', 0.8, 'monthly'),
        ('contact', 0.6, 'monthly'),
        ('marketplace', 0.8, 'daily'),
        ('events_news_public', 0.7, 'daily'),
        ('gallery_public', 0.6, 'weekly'),
    ]
    urls = []
    for endpoint, priority, freq in pages:
        try:
            urls.append((site + url_for(endpoint), None, freq, priority))
        except Exception:
            continue
    try:
        for ev in Event.query.order_by(Event.created_at.desc()).limit(500).all():
            lastmod = ev.created_at.strftime('%Y-%m-%d') if ev.created_at else None
            urls.append((site + url_for('events_news_detail', event_id=ev.id), lastmod, 'monthly', 0.5))
    except Exception:
        pass
    try:
        for (ts, ls), n in _seo_counts().items():
            if n > 0:
                slug = ts if ls is None else f'{ts}-in-{ls}'
                urls.append((site + url_for('seo_landing', slug=slug), None, 'weekly', 0.8 if ls else 0.7))
    except Exception:
        pass
    try:
        urls.append((site + url_for('find_artisans'), None, 'daily', 0.9))
    except Exception:
        pass
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, lastmod, freq, priority in urls:
        xml.append('  <url>')
        xml.append(f'    <loc>{loc}</loc>')
        if lastmod:
            xml.append(f'    <lastmod>{lastmod}</lastmod>')
        xml.append(f'    <changefreq>{freq}</changefreq>')
        xml.append(f'    <priority>{priority}</priority>')
        xml.append('  </url>')
    xml.append('</urlset>')
    return app.response_class('\n'.join(xml), mimetype='application/xml')



# ==================== SEO LANDING PAGES (trade x location) ====================
# URLs look like /electricians-in-abuja, /solar-installers-in-lagos, /electricians (nationwide).
# Add or remove entries here; sitemap, links and pages update automatically.
# slug: (occupation stored in DB, plural label, singular label, what they do, what to check)
SEO_TRADES = {
    'electricians': ('Electrician', 'Electricians', 'electrician',
                     'wiring, rewiring, fault finding, distribution boards, lighting and inverter or generator changeover installation',
                     'Ask about previous wiring jobs, whether they use properly rated cables and breakers, and whether they will test the installation before handover.'),
    'plumbers': ('Plumber', 'Plumbers', 'plumber',
                 'pipe installation, leak repair, water tank and pump connections, bathroom fittings and drainage',
                 'Agree the scope and materials list up front, and ask whether pipe and fitting costs are included in the quote.'),
    'welders': ('Welder / Fabricator', 'Welders & Fabricators', 'welder or fabricator',
                'gates, burglar proofing, roofing frames, tanks stands, trailers and general metal fabrication',
                'Ask to see finished work, agree the steel gauge and finish (primer or paint), and confirm the delivery timeline.'),
    'solar-installers': ('Solar Technician', 'Solar Installers', 'solar technician',
                         'solar panel, inverter and battery installation, solar pumps, system sizing and maintenance',
                         'Request a written load calculation, brand and warranty details for panels, inverter and batteries, and ask who handles after-install faults.'),
    'ac-technicians': ('Refrigeration / AC Technician', 'AC & Refrigeration Technicians', 'AC or refrigeration technician',
                       'air-conditioner installation, gas refilling, servicing, cold-room and refrigerator repair',
                       'Ask for a diagnosis before gas refilling, and confirm whether replacement parts carry any warranty.'),
    'auto-mechanics': ('Automobile Mechanic', 'Auto Mechanics', 'automobile mechanic',
                       'engine repair, servicing, brakes, suspension, electrical faults and diagnostics',
                       'Get a written estimate, ask for replaced parts to be shown to you, and confirm whether the repair is guaranteed.'),
    'generator-technicians': ('Generator Technician', 'Generator Technicians', 'generator technician',
                              'generator servicing, overhaul, AVR and carburettor repair, and installation',
                              'Ask about the generator brand experience, whether spare parts are genuine, and how long the repair should take.'),
    'carpenters': ('Carpenter', 'Carpenters', 'carpenter',
                   'doors, wardrobes, roofing timber, furniture and fittings',
                   'Agree the wood type, design drawings and a payment schedule tied to progress.'),
    'tilers': ('Tiler', 'Tilers', 'tiler',
               'floor and wall tiling, screeding, grouting and finishing',
               'Confirm who supplies tiles and adhesive, the measured area, and whether the price is per square metre.'),
    'painters': ('Painter', 'Painters', 'painter',
                 'interior and exterior painting, screeding, POP finishing and surface preparation',
                 'Agree the paint brand, number of coats and whether surface preparation is included.'),
    'masons': ('Mason', 'Masons & Bricklayers', 'mason',
               'block laying, plastering, foundations, fencing and general building work',
               'Agree the scope per stage, who supplies materials, and inspect completed stages before releasing payment.'),
    'borehole-technicians': ('Borehole Technician', 'Borehole Technicians', 'borehole technician',
                             'borehole drilling, pump installation, water treatment and pump repair',
                             'Ask for the drilling depth, casing and pump specification in writing, and check for a water-yield or workmanship guarantee.'),
}

# slug: (state value stored in DB, display name)
SEO_LOCATIONS = {
    'abuja': ('FCT', 'Abuja'),
    'lagos': ('Lagos', 'Lagos'),
    'port-harcourt': ('Rivers', 'Port Harcourt'),
    'kano': ('Kano', 'Kano'),
    'ibadan': ('Oyo', 'Ibadan'),
    'enugu': ('Enugu', 'Enugu'),
    'owerri': ('Imo', 'Owerri'),
    'onitsha': ('Anambra', 'Onitsha'),
    'kaduna': ('Kaduna', 'Kaduna'),
    'benin-city': ('Edo', 'Benin City'),
    'asaba': ('Delta', 'Asaba'),
    'uyo': ('Akwa Ibom', 'Uyo'),
}

SEO_LISTED = ['registered', 'verified', 'accredited', 'partner']


def _seo_parse(slug):
    """Return (trade_slug, location_slug|None) for a landing slug, or None."""
    if slug in SEO_TRADES:
        return slug, None
    if '-in-' in slug:
        t, l = slug.split('-in-', 1)
        if t in SEO_TRADES and l in SEO_LOCATIONS:
            return t, l
    return None


def _seo_listed_query(trade_slug, loc_slug=None):
    occupation = SEO_TRADES[trade_slug][0]
    q = User.query.filter(
        User.role.in_(['artisan', 'technician', 'engineer']),
        User.listing_category.in_(SEO_LISTED),
        User.occupation.ilike(f'%{occupation}%'),
    )
    if loc_slug:
        q = q.filter(User.location_state.ilike(f'%{SEO_LOCATIONS[loc_slug][0]}%'))
    return q


def _seo_counts():
    """{(trade_slug, loc_slug|None): n} for every combination, in one query."""
    rows = User.query.with_entities(User.occupation, User.location_state).filter(
        User.role.in_(['artisan', 'technician', 'engineer']),
        User.listing_category.in_(SEO_LISTED),
    ).all()
    counts = {}
    for occ, st in rows:
        occ_l, st_l = (occ or '').lower(), (st or '').lower()
        for ts, (db_occ, *_rest) in SEO_TRADES.items():
            if db_occ.lower() not in occ_l:
                continue
            counts[(ts, None)] = counts.get((ts, None), 0) + 1
            for ls, (db_st, _name) in SEO_LOCATIONS.items():
                if db_st.lower() in st_l:
                    counts[(ts, ls)] = counts.get((ts, ls), 0) + 1
    return counts


@app.route('/<slug>')
def seo_landing(slug):
    """Trade / location landing pages, e.g. /electricians-in-abuja."""
    from flask import abort
    parsed = _seo_parse(slug)
    if not parsed:
        abort(404)
    trade_slug, loc_slug = parsed
    db_occ, plural, singular, does, check = SEO_TRADES[trade_slug]
    place = SEO_LOCATIONS[loc_slug][1] if loc_slug else 'Nigeria'
    members = _seo_listed_query(trade_slug, loc_slug).order_by(
        User.listing_category.desc(), User.full_name).limit(24).all()
    counts = _seo_counts()
    total = counts.get((trade_slug, loc_slug), 0)

    # Related links: same trade in other cities, other trades in this city
    other_places = [(ls, SEO_LOCATIONS[ls][1]) for ls in SEO_LOCATIONS if ls != loc_slug]
    other_trades = [(ts, SEO_TRADES[ts][1]) for ts in SEO_TRADES if ts != trade_slug]

    find_params = {'occupation': db_occ}
    if loc_slug:
        find_params['state'] = SEO_LOCATIONS[loc_slug][0]

    return render_template(
        'seo_landing.html',
        trade_slug=trade_slug, loc_slug=loc_slug,
        plural=plural, singular=singular, does=does, check=check,
        place=place, members=members, total=total,
        other_places=other_places, other_trades=other_trades,
        find_params=find_params,
        # Thin pages stay out of the index until at least one member is listed
        noindex=(total == 0),
    )


@app.route('/favicon.ico')
def favicon_ico():
    """Browsers and crawlers request /favicon.ico by default."""
    return app.send_static_file('favicon/favicon.ico')


@app.route('/site.webmanifest')
def site_webmanifest():
    return app.send_static_file('favicon/site.webmanifest')


@app.route('/<path:filename>.html')
def google_html_verification(filename):
    """Serves Google's HTML-file verification (set GOOGLE_HTML_FILE=googleXXXX.html)."""
    full = filename + '.html'
    if GOOGLE_HTML_FILE and full == GOOGLE_HTML_FILE:
        return app.response_class('google-site-verification: ' + GOOGLE_HTML_FILE, mimetype='text/html')
    from flask import abort
    abort(404)


@app.route('/BingSiteAuth.xml')
def bing_site_auth():
    """Serves Bing's XML-file verification (set BING_AUTH_CODE=your-code)."""
    if not BING_AUTH_CODE:
        from flask import abort
        abort(404)
    xml = ('<?xml version="1.0"?>\n<users>\n\t<user>' + BING_AUTH_CODE + '</user>\n</users>')
    return app.response_class(xml, mimetype='application/xml')


@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/contact')
def contact():
    return render_template('contact.html')


@app.route('/gate')
def gate():
    return render_template('gate.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password')
        full_name = request.form.get('full_name')
        phone = request.form.get('phone')
        role = request.form.get('role', 'artisan')
        # block admin registration from public form (RBAC)
        if role not in STAKEHOLDER_ROLES:
            role = 'artisan'
        location_state = request.form.get('location_state')
        location_lga = request.form.get('location_lga')
        location_community = request.form.get('location_community')
        occupation = request.form.get('occupation')
        specialty = request.form.get('specialty')
        skills = request.form.get('skills')
        experience_years = request.form.get('experience_years', 0)
        needs = request.form.get('needs')

        if User.query.filter_by(email=email).first():
            flash('Email already registered. Please login.', 'warning')
            return redirect(url_for('login'))

        token = secrets.token_urlsafe(32)
        user = User(
            email=email,
            full_name=full_name,
            phone=phone,
            role=role,
            location_state=location_state,
            location_lga=location_lga,
            location_community=location_community,
            occupation=occupation,
            specialty=specialty,
            skills=skills,
            experience_years=int(experience_years) if experience_years else 0,
            needs=needs,
            email_verified=False,
            whatsapp=request.form.get('whatsapp') or phone,
            business_name=request.form.get('business_name'),
            workshop_address=request.form.get('workshop_address'),
            certifications=request.form.get('certifications'),
            references_text=request.form.get('references_text'),
            supplier_category=request.form.get('supplier_category'),
            products_supplied=request.form.get('products_supplied'),
            opening_hours=request.form.get('opening_hours'),
            institution_type=request.form.get('institution_type'),
            listing_category=(
                'partner' if role in ('industry', 'partner', 'supplier') else
                'registered' if role in MEMBER_ROLES else
                'public'
            ),
            verification_token=token
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        # Welcome notification
        notif = Notification(
            user_id=user.id,
            title='Welcome to FAATN-GATE!',
            message='Please verify your email, then complete your profile and explore opportunities.',
            type='success'
        )
        db.session.add(notif)
        db.session.commit()

        email_notify_admin('New registration', [f'{user.full_name} ({user.email}) registered as {user.role}.'])

        # Send the verification link by email
        if send_verification_email(user, token):
            flash(f'Registration successful! We sent a verification link to {email}. '
                  'Please check your inbox (and spam folder).', 'success')
        else:
            flash('Registration successful! We could not send the verification email right now. '
                  'Log in and use "Resend verification" on your profile page.', 'warning')
        return redirect(url_for('login'))

    return render_template(
        'register.html',
        occupations=OCCUPATIONS,
        states=NIGERIA_STATES,
        supplier_categories=SUPPLIER_CATEGORIES,
        institution_types=INSTITUTION_TYPES,
    )


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user, remember=remember)
            user.last_login = datetime.utcnow()
            db.session.commit()
            flash(f'Welcome back, {user.full_name}!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard'))
        else:
            flash('Invalid email or password.', 'danger')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


@app.route('/verify-email/<token>')
def verify_email(token):
    user = User.query.filter_by(verification_token=token).first()
    if not user:
        flash('Invalid or expired verification link.', 'danger')
        return redirect(url_for('login'))
    if user.email_verified:
        flash('Email already verified. You can log in.', 'info')
        return redirect(url_for('login'))
    user.email_verified = True
    user.verification_token = None
    db.session.commit()
    flash('Email verified successfully! You can now log in.', 'success')
    return redirect(url_for('login'))


@app.route('/dashboard/profile/password', methods=['POST'])
@login_required
def change_password():
    """Any signed-in member (including the admin) changes their own password."""
    current = request.form.get('current_password', '')
    new = request.form.get('new_password', '')
    confirm = request.form.get('confirm_password', '')
    if not current_user.check_password(current):
        flash('Your current password is not correct. Password not changed.', 'danger')
    elif len(new) < 8:
        flash('The new password must be at least 8 characters.', 'danger')
    elif new in KNOWN_PUBLIC_PASSWORDS:
        flash('That password is publicly known. Choose a different one.', 'danger')
    elif new != confirm:
        flash('The new passwords do not match.', 'danger')
    else:
        current_user.set_password(new)
        current_user.reset_token = None
        current_user.reset_token_expires = None
        db.session.commit()
        send_password_changed_email(current_user)
        flash('Your password was changed.', 'success')
    return redirect(url_for('profile') + '#password')


@app.route('/dashboard/resend-verification', methods=['POST'])
@login_required
def resend_verification():
    if current_user.email_verified:
        flash('Your email is already verified.', 'info')
        return redirect(url_for('profile'))
    token = secrets.token_urlsafe(32)
    current_user.verification_token = token
    db.session.commit()
    if send_verification_email(current_user, token):
        flash(f'Verification email sent to {current_user.email}. Please check your inbox (and spam folder).', 'success')
    else:
        flash('Email service is not available right now. Please try again later or contact FAATN support.', 'warning')
    return redirect(url_for('profile'))


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter_by(email=email).first()
        # Throttle: at most one reset email per account every 5 minutes (stops inbox-flooding someone else)
        recently_sent = bool(user and user.reset_token_expires and
                             user.reset_token_expires > datetime.utcnow() + timedelta(hours=2) - timedelta(minutes=5))
        if user and not recently_sent:
            token = secrets.token_urlsafe(32)
            user.reset_token = token
            user.reset_token_expires = datetime.utcnow() + timedelta(hours=2)
            db.session.commit()
            send_reset_email(user, token)
        # Same message whether or not the email exists (don't reveal who is registered)
        flash('If that email is registered, a password reset link has been sent. '
              'Please check your inbox (and spam folder).', 'info')
        return redirect(url_for('forgot_password'))
    return render_template('forgot_password.html')


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).first()
    if not user or not user.reset_token_expires or user.reset_token_expires < datetime.utcnow():
        flash('Invalid or expired reset link. Please request a new one.', 'danger')
        return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
        elif password != confirm:
            flash('Passwords do not match.', 'danger')
        else:
            user.set_password(password)
            user.reset_token = None
            user.reset_token_expires = None
            user.email_verified = True  # they just proved they own this inbox
            db.session.commit()
            send_password_changed_email(user)
            flash('Password updated. You can log in now.', 'success')
            return redirect(url_for('login'))
    return render_template('reset_password.html', token=token)


@app.route('/dashboard')
@login_required
def dashboard():
    # Role-based dashboard routing
    if is_admin(current_user):
        return redirect(url_for('admin_dashboard'))
    if is_member(current_user) or has_role(current_user, *STAKEHOLDER_ROLES):
        return redirect(url_for('artisan_dashboard'))
    return redirect(url_for('artisan_dashboard'))


@app.route('/dashboard/artisan')
@login_required
def artisan_dashboard():
    # Stats
    trainings_count = TrainingEnrollment.query.filter_by(user_id=current_user.id).count()
    innovations_count = Innovation.query.filter_by(user_id=current_user.id).count()
    applications_count = OpportunityApplication.query.filter_by(user_id=current_user.id).count()
    unread_messages = Message.query.filter_by(recipient_id=current_user.id, is_read=False).count()
    unread_notifs = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()

    # Recent items
    recent_trainings = TrainingEnrollment.query.filter_by(user_id=current_user.id).order_by(TrainingEnrollment.enrolled_at.desc()).limit(3).all()
    recent_opportunities = Opportunity.query.filter_by(is_active=True).order_by(Opportunity.created_at.desc()).limit(4).all()
    recent_innovations = Innovation.query.filter_by(user_id=current_user.id).order_by(Innovation.updated_at.desc()).limit(3).all()
    notifications = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(5).all()
    messages = Message.query.filter_by(recipient_id=current_user.id).order_by(Message.created_at.desc()).limit(5).all()

    return render_template(
        'dashboard_artisan.html',
        trainings_count=trainings_count,
        innovations_count=innovations_count,
        applications_count=applications_count,
        unread_messages=unread_messages,
        unread_notifs=unread_notifs,
        recent_trainings=recent_trainings,
        recent_opportunities=recent_opportunities,
        recent_innovations=recent_innovations,
        notifications=notifications,
        messages=messages
    )


@app.route('/dashboard/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.full_name = request.form.get('full_name', current_user.full_name)
        current_user.phone = request.form.get('phone', current_user.phone)
        current_user.location_state = request.form.get('location_state', current_user.location_state)
        current_user.location_lga = request.form.get('location_lga', current_user.location_lga)
        current_user.location_community = request.form.get('location_community', current_user.location_community)
        current_user.occupation = request.form.get('occupation', current_user.occupation)
        current_user.specialty = request.form.get('specialty', current_user.specialty)
        current_user.skills = request.form.get('skills', current_user.skills)
        current_user.experience_years = int(request.form.get('experience_years') or 0)
        current_user.portfolio = request.form.get('portfolio', current_user.portfolio)
        current_user.needs = request.form.get('needs', current_user.needs)
        current_user.email_notifications = bool(request.form.get('email_notifications'))

        # Profile picture upload
        file = request.files.get('profile_pic')
        if file and file.filename and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = secure_filename(f"user_{current_user.id}_{secrets.token_hex(4)}.{ext}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            # Remove old pic if exists
            if current_user.profile_pic:
                old_path = os.path.join(app.config['UPLOAD_FOLDER'], current_user.profile_pic)
                if os.path.isfile(old_path):
                    try:
                        os.remove(old_path)
                    except OSError:
                        pass
            file.save(filepath)
            current_user.profile_pic = filename

        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile'))

    return render_template('profile.html')


@app.route('/dashboard/trainings')
@login_required
def trainings():
    available = Training.query.filter_by(is_active=True).all()
    my_enrollments = TrainingEnrollment.query.filter_by(user_id=current_user.id).all()
    enrolled_ids = {e.training_id for e in my_enrollments}
    return render_template('trainings.html', available=available, my_enrollments=my_enrollments, enrolled_ids=enrolled_ids)


@app.route('/dashboard/trainings/enroll/<int:training_id>', methods=['POST'])
@login_required
def enroll_training(training_id):
    existing = TrainingEnrollment.query.filter_by(user_id=current_user.id, training_id=training_id).first()
    if existing:
        flash('You are already enrolled in this training.', 'warning')
    else:
        enrollment = TrainingEnrollment(user_id=current_user.id, training_id=training_id)
        db.session.add(enrollment)
        notif = Notification(
            user_id=current_user.id,
            title='Training Enrollment Successful',
            message=f'You have been enrolled. Check your dashboard for details.',
            type='training'
        )
        db.session.add(notif)
        db.session.commit()
        flash('Successfully enrolled!', 'success')
    return redirect(url_for('trainings'))


@app.route('/dashboard/opportunities')
@login_required
def opportunities():
    all_opps = Opportunity.query.filter_by(is_active=True).order_by(Opportunity.created_at.desc()).all()
    my_apps = OpportunityApplication.query.filter_by(user_id=current_user.id).all()
    applied_ids = {a.opportunity_id for a in my_apps}
    return render_template('opportunities.html', opportunities=all_opps, my_apps=my_apps, applied_ids=applied_ids)


@app.route('/dashboard/opportunities/apply/<int:opp_id>', methods=['POST'])
@login_required
def apply_opportunity(opp_id):
    existing = OpportunityApplication.query.filter_by(user_id=current_user.id, opportunity_id=opp_id).first()
    if existing:
        flash('You have already applied to this opportunity.', 'warning')
    else:
        cover = request.form.get('cover_note', '')
        app_entry = OpportunityApplication(
            user_id=current_user.id,
            opportunity_id=opp_id,
            cover_note=cover
        )
        db.session.add(app_entry)
        notif = Notification(
            user_id=current_user.id,
            title='Application Submitted',
            message='Your application has been received and is under review.',
            type='opportunity'
        )
        db.session.add(notif)
        db.session.commit()
        flash('Application submitted successfully!', 'success')
    return redirect(url_for('opportunities'))



@app.route('/events-news', methods=['GET', 'POST'])
def events_news_public():
    """Public Events / News list. Admin can publish write-ups + images from this page."""
    can_post = can_upload_content(current_user)

    if request.method == 'POST':
        if not can_post:
            flash('Only the official FAATN publisher account can publish Events / News.', 'danger')
            return redirect(url_for('events_news_public'))

        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        category = request.form.get('category', 'event').strip().lower()
        if category not in ('event', 'news'):
            category = 'event'
        location = request.form.get('location', '').strip()
        event_date_str = request.form.get('event_date', '').strip()
        event_time = request.form.get('event_time', '').strip()

        if not title:
            flash('Title is required.', 'danger')
            return redirect(url_for('events_news_public'))

        wc = word_count(description)
        if wc > MAX_NEWS_WORDS:
            flash(f'Text is too long ({wc} words). Maximum is {MAX_NEWS_WORDS} words.', 'danger')
            return redirect(url_for('events_news_public'))

        event_date = None
        if event_date_str:
            try:
                event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date()
            except ValueError:
                flash('Invalid date format.', 'danger')
                return redirect(url_for('events_news_public'))

        image_filename = None
        file = request.files.get('image')
        if file and file.filename and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            image_filename = secure_filename(f"event_{current_user.id}_{secrets.token_hex(6)}.{ext}")
            file.save(os.path.join(app.config['EVENT_UPLOAD_FOLDER'], image_filename))

        event = Event(
            title=title,
            description=description,
            category=category,
            location=location or None,
            event_date=event_date,
            event_time=event_time or None,
            image_filename=image_filename,
            created_by_id=current_user.id,
            is_active=True,
        )
        db.session.add(event)
        db.session.commit()
        if request.form.get('notify_members'):
            flash(f'Events / News published. Emailing {broadcast_event_email(event)} member(s).', 'success')
        else:
            flash('Events / News published successfully.', 'success')
        return redirect(url_for('events_news_public'))

    items = Event.query.filter_by(is_active=True).order_by(Event.created_at.desc()).all()
    return render_template(
        'events_news_public.html',
        events=items,
        can_post=can_post,
        max_words=MAX_NEWS_WORDS,
    )


@app.route('/events-news/<int:event_id>')
def events_news_detail(event_id):
    item = Event.query.filter_by(id=event_id, is_active=True).first_or_404()
    return render_template('events_news_detail.html', event=item)


@app.route('/gallery', methods=['GET', 'POST'])
def gallery_public():
    """Public gallery. Admin can upload images from this page."""
    can_post = can_upload_content(current_user)

    if request.method == 'POST':
        if not can_post:
            flash('Only the official FAATN publisher account can upload gallery images.', 'danger')
            return redirect(url_for('gallery_public'))

        title = request.form.get('title', '').strip()
        caption = request.form.get('caption', '').strip()
        file = request.files.get('image')

        if not file or not file.filename or not allowed_file(file.filename):
            flash('Please choose a valid image (JPG, PNG, GIF, WebP).', 'danger')
            return redirect(url_for('gallery_public'))

        ext = file.filename.rsplit('.', 1)[1].lower()
        image_filename = secure_filename(f"gal_{current_user.id}_{secrets.token_hex(6)}.{ext}")
        file.save(os.path.join(app.config['GALLERY_UPLOAD_FOLDER'], image_filename))

        item = GalleryItem(
            title=title or 'Gallery photo',
            caption=caption,
            image_filename=image_filename,
            created_by_id=current_user.id,
            is_active=True,
        )
        db.session.add(item)
        db.session.commit()
        flash('Gallery image uploaded.', 'success')
        return redirect(url_for('gallery_public'))

    items = GalleryItem.query.filter_by(is_active=True).order_by(GalleryItem.created_at.desc()).all()
    return render_template('gallery_public.html', items=items, can_post=can_post)


@app.route('/dashboard/events', methods=['GET', 'POST'])
@login_required
def events():
    """Events / News board. Only admin (publisher) may post long write-ups + images."""
    can_post = can_upload_content(current_user)

    if request.method == 'POST':
        if not can_post:
            flash('Only the official FAATN publisher account can post Events / News.', 'danger')
            return redirect(url_for('login'))

        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        category = request.form.get('category', 'event').strip().lower()
        if category not in ('event', 'news'):
            category = 'event'
        location = request.form.get('location', '').strip()
        event_date_str = request.form.get('event_date', '').strip()
        event_time = request.form.get('event_time', '').strip()

        if not title:
            flash('Title is required.', 'danger')
            return redirect(url_for('events'))

        wc = word_count(description)
        if wc > MAX_NEWS_WORDS:
            flash(f'Text is too long ({wc} words). Maximum is {MAX_NEWS_WORDS} words.', 'danger')
            return redirect(url_for('events'))

        event_date = None
        if event_date_str:
            try:
                event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date()
            except ValueError:
                flash('Invalid date format. Use YYYY-MM-DD.', 'danger')
                return redirect(url_for('events'))

        image_filename = None
        file = request.files.get('image')
        if file and file.filename and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            image_filename = secure_filename(f"event_{current_user.id}_{secrets.token_hex(6)}.{ext}")
            file.save(os.path.join(app.config['EVENT_UPLOAD_FOLDER'], image_filename))

        event = Event(
            title=title,
            description=description,
            category=category,
            location=location or None,
            event_date=event_date,
            event_time=event_time or None,
            image_filename=image_filename,
            created_by_id=current_user.id,
            is_active=True,
        )
        db.session.add(event)
        db.session.commit()
        if request.form.get('notify_members'):
            flash(f'Events / News item published. Emailing {broadcast_event_email(event)} member(s).', 'success')
        else:
            flash('Events / News item published.', 'success')
        return redirect(url_for('events'))

    all_events = Event.query.filter_by(is_active=True).order_by(
        Event.created_at.desc()
    ).all()
    return render_template('events.html', events=all_events, can_post=can_post, max_words=MAX_NEWS_WORDS)


@app.route('/dashboard/events/delete/<int:event_id>', methods=['POST'])
@login_required
def delete_event(event_id):
    event = Event.query.get_or_404(event_id)
    if not is_publisher(current_user) and event.created_by_id != current_user.id:
        flash('You cannot delete this item.', 'danger')
        return redirect(url_for('events'))
    event.is_active = False
    db.session.commit()
    flash('Item removed.', 'info')
    return redirect(url_for('events'))


@app.route('/dashboard/gallery', methods=['GET', 'POST'])
@login_required
def gallery_manage():
    """Gallery upload — admin (publisher) only."""
    can_post = can_upload_content(current_user)

    if request.method == 'POST':
        if not can_post:
            flash('Only the official FAATN publisher account can upload gallery images.', 'danger')
            return redirect(url_for('login'))

        title = request.form.get('title', '').strip()
        caption = request.form.get('caption', '').strip()
        file = request.files.get('image')

        if not file or not file.filename or not allowed_file(file.filename):
            flash('Please choose a valid image (JPG, PNG, GIF, WebP).', 'danger')
            return redirect(url_for('gallery_manage'))

        ext = file.filename.rsplit('.', 1)[1].lower()
        image_filename = secure_filename(f"gal_{current_user.id}_{secrets.token_hex(6)}.{ext}")
        file.save(os.path.join(app.config['GALLERY_UPLOAD_FOLDER'], image_filename))

        item = GalleryItem(
            title=title or 'Gallery photo',
            caption=caption,
            image_filename=image_filename,
            created_by_id=current_user.id,
            is_active=True,
        )
        db.session.add(item)
        db.session.commit()
        flash('Gallery image uploaded.', 'success')
        return redirect(url_for('gallery_manage'))

    items = GalleryItem.query.filter_by(is_active=True).order_by(GalleryItem.created_at.desc()).all()
    return render_template('gallery_manage.html', items=items, can_post=can_post)


@app.route('/dashboard/gallery/delete/<int:item_id>', methods=['POST'])
@login_required
def delete_gallery_item(item_id):
    item = GalleryItem.query.get_or_404(item_id)
    if not is_publisher(current_user) and item.created_by_id != current_user.id:
        flash('You can only remove your own gallery images.', 'danger')
        return redirect(url_for('gallery_manage'))
    item.is_active = False
    db.session.commit()
    flash('Gallery image removed.', 'info')
    return redirect(url_for('gallery_manage'))


@app.route('/dashboard/innovations', methods=['GET', 'POST'])
@login_required
def innovations():
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        problem = request.form.get('problem')
        if title and description:
            innov = Innovation(
                user_id=current_user.id,
                title=title,
                description=description,
                problem=problem
            )
            db.session.add(innov)
            notif = Notification(
                user_id=current_user.id,
                title='Innovation Submitted',
                message=f'Your idea "{title}" has entered the Innovation Route.',
                type='success'
            )
            db.session.add(notif)
            db.session.commit()
            flash('Innovation submitted successfully! It is now in the screening stage.', 'success')
            return redirect(url_for('innovations'))
        else:
            flash('Title and description are required.', 'danger')

    my_innovations = Innovation.query.filter_by(user_id=current_user.id).order_by(Innovation.updated_at.desc()).all()
    return render_template('innovations.html', innovations=my_innovations)




@app.route('/find/suppliers')
def find_suppliers():
    """FIND PARTS & SUPPLIERS — FAATN retains master data; maps are integration only."""
    q = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()
    state = request.args.get('state', '').strip()
    town = request.args.get('town', '').strip()

    query = User.query.filter(
        db.or_(User.role.in_(['industry', 'partner', 'supplier']), User.listing_category == 'partner')
    )
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(
            User.business_name.ilike(like),
            User.products_supplied.ilike(like),
            User.full_name.ilike(like),
            User.supplier_category.ilike(like),
        ))
    if category:
        query = query.filter(User.supplier_category.ilike(f'%{category}%'))
    if state:
        query = query.filter(User.location_state.ilike(f'%{state}%'))
    if town:
        query = query.filter(User.location_community.ilike(f'%{town}%'))

    results = query.order_by(User.business_name.nullslast(), User.full_name).limit(80).all()
    return render_template(
        'find_suppliers.html',
        results=results,
        categories=SUPPLIER_CATEGORIES,
        states=NIGERIA_STATES,
        q=q, category=category, state=state, town=town,
        searched=bool(request.args),
    )


@app.route('/need-help', methods=['GET', 'POST'])
def need_help():
    """I Need Help — describe a problem; FAATN routes to suitable registered technicians."""
    if request.method == 'POST':
        desc = request.form.get('description', '').strip()
        if not desc:
            flash('Please describe the problem.', 'danger')
            return redirect(url_for('need_help'))
        hr = HelpRequest(
            requester_name=request.form.get('requester_name', '').strip(),
            requester_phone=request.form.get('requester_phone', '').strip(),
            requester_email=request.form.get('requester_email', '').strip(),
            location_state=request.form.get('location_state', '').strip(),
            location_lga=request.form.get('location_lga', '').strip(),
            location_town=request.form.get('location_town', '').strip(),
            problem_category=request.form.get('problem_category', '').strip(),
            description=desc,
            urgency=request.form.get('urgency', 'normal'),
            user_id=current_user.id if current_user.is_authenticated else None,
        )
        db.session.add(hr)
        db.session.commit()
        visitor = (hr.requester_email or '').strip().lower()
        if is_valid_email(visitor):
            recent = HelpRequest.query.filter(db.func.lower(HelpRequest.requester_email) == visitor,
                                              HelpRequest.created_at >= datetime.utcnow() - timedelta(hours=1)).count()
            if recent <= 3:  # stops the form being used to spam someone else's inbox
                body = (f'Hello {hr.requester_name or "there"},\n\nThank you for contacting FAATN-GATE. Your request was received and '
                        f'FAATN will route it to suitable registered technicians.\n\nSummary: {(hr.description or "")[:200]}\n\n'
                        '(You received this one-time message because this address was entered on the FAATN-GATE "I Need Help" form.)')
                html = _email_shell('We received your request',
                                    f'<p>Hello {html_escape(hr.requester_name or "there")},</p>'
                                    '<p>Thank you for contacting FAATN-GATE. Your request was received and FAATN will route it to suitable registered technicians.</p>'
                                    f'<p><em>{html_escape((hr.description or "")[:200])}</em></p>')
                send_email(visitor, 'FAATN-GATE: we received your request', body, html)
        email_notify_admin('New help request', [f'{hr.requester_name or "Someone"} ({hr.requester_phone or "no phone"}) in {hr.location_state or "?"}: {(hr.description or "")[:200]}'])
        flash('Your request has been submitted. FAATN will route it to suitable registered technicians.', 'success')
        return redirect(url_for('need_help'))

    matches = []
    # Optional preview matches if query args
    cat = request.args.get('problem_category', '').strip()
    state = request.args.get('location_state', '').strip()
    if cat or state:
        q = User.query.filter(
            User.role.in_(['artisan', 'technician', 'engineer']),
            User.listing_category.in_(['registered', 'verified', 'accredited']),
        )
        if cat:
            q = q.filter(db.or_(User.occupation.ilike(f'%{cat}%'), User.specialty.ilike(f'%{cat}%'), User.skills.ilike(f'%{cat}%')))
        if state:
            q = q.filter(User.location_state.ilike(f'%{state}%'))
        matches = q.limit(12).all()

    return render_template(
        'need_help.html',
        occupations=OCCUPATIONS,
        states=NIGERIA_STATES,
        matches=matches,
    )




@app.route('/market-hub')
def market_hub():
    """Market Hub — central place for products, services, artisans, suppliers and help."""
    q = request.args.get('q', '').strip()
    state = request.args.get('state', '').strip()

    # Featured marketplace products
    prod_query = Product.query.filter_by(is_active=True).join(User)
    if q:
        like = f'%{q}%'
        prod_query = prod_query.filter(db.or_(
            Product.title.ilike(like),
            Product.description.ilike(like),
            User.full_name.ilike(like),
            User.business_name.ilike(like),
            User.specialty.ilike(like),
        ))
    if state:
        prod_query = prod_query.filter(User.location_state.ilike(f'%{state}%'))
    products = prod_query.order_by(Product.created_at.desc()).limit(8).all()

    # Artisans / technicians sample
    art_query = User.query.filter(
        User.role.in_(['artisan', 'technician', 'engineer']),
        User.listing_category.in_(['registered', 'verified', 'accredited', 'partner']),
    )
    if q:
        like = f'%{q}%'
        art_query = art_query.filter(db.or_(
            User.full_name.ilike(like),
            User.occupation.ilike(like),
            User.specialty.ilike(like),
            User.skills.ilike(like),
        ))
    if state:
        art_query = art_query.filter(User.location_state.ilike(f'%{state}%'))
    artisans = art_query.order_by(User.listing_category.desc(), User.full_name).limit(6).all()

    # Suppliers
    sup_query = User.query.filter(
        db.or_(User.role.in_(['industry', 'partner', 'supplier']), User.listing_category == 'partner')
    )
    if q:
        like = f'%{q}%'
        sup_query = sup_query.filter(db.or_(
            User.business_name.ilike(like),
            User.products_supplied.ilike(like),
            User.full_name.ilike(like),
        ))
    if state:
        sup_query = sup_query.filter(User.location_state.ilike(f'%{state}%'))
    suppliers = sup_query.order_by(User.full_name).limit(6).all()

    product_count = Product.query.filter_by(is_active=True).count()
    artisan_count = User.query.filter(
        User.role.in_(['artisan', 'technician', 'engineer']),
        User.listing_category.in_(['registered', 'verified', 'accredited', 'partner']),
    ).count()

    return render_template(
        'market_hub.html',
        products=products,
        artisans=artisans,
        suppliers=suppliers,
        q=q,
        state=state,
        states=NIGERIA_STATES,
        product_count=product_count,
        artisan_count=artisan_count,
    )


@app.route('/marketplace')
def marketplace():
    """Public artisan marketplace — products and services with images."""
    q = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip().lower()
    state = request.args.get('state', '').strip()
    sort = request.args.get('sort', 'newest').strip().lower()
    min_rating = request.args.get('min_rating', '').strip()
    query = Product.query.filter_by(is_active=True).join(User)
    if q:
        like = f'%{q}%'
        query = query.filter(
            db.or_(
                Product.title.ilike(like),
                Product.description.ilike(like),
                Product.price.ilike(like),
                User.full_name.ilike(like),
                User.business_name.ilike(like),
                User.specialty.ilike(like),
                User.occupation.ilike(like),
            )
        )
    if category in ('product', 'service'):
        query = query.filter(Product.category == category)
    if state:
        query = query.filter(User.location_state.ilike(f'%{state}%'))
    if sort == 'oldest':
        query = query.order_by(Product.created_at.asc())
    elif sort == 'title':
        query = query.order_by(Product.title.asc())
    else:
        query = query.order_by(Product.created_at.desc())
    products = query.limit(120).all()
    # Attach average rating for display / optional filter
    product_ids = [p.id for p in products]
    ratings_map = {}
    if product_ids:
        rows = db.session.query(
            Review.product_id,
            db.func.avg(Review.rating),
            db.func.count(Review.id)
        ).filter(Review.product_id.in_(product_ids)).group_by(Review.product_id).all()
        for pid, avg_r, cnt in rows:
            ratings_map[pid] = {'avg': round(float(avg_r), 1), 'count': int(cnt)}
    if min_rating.isdigit():
        mr = int(min_rating)
        products = [p for p in products if ratings_map.get(p.id, {}).get('avg', 0) >= mr]
    return render_template(
        'marketplace.html',
        products=products,
        ratings_map=ratings_map,
        q=q,
        category=category,
        state=state,
        sort=sort,
        min_rating=min_rating,
        states=NIGERIA_STATES,
    )


@app.route('/marketplace/<int:product_id>', methods=['GET', 'POST'])
def marketplace_detail(product_id):
    """Single product/service page with images and user reviews."""
    product = Product.query.filter_by(id=product_id, is_active=True).first_or_404()
    if request.method == 'POST':
        if not current_user.is_authenticated:
            flash('Please log in to leave a review.', 'warning')
            return redirect(url_for('login', next=request.url))
        if product.user_id == current_user.id:
            flash('You cannot review your own listing.', 'warning')
            return redirect(url_for('marketplace_detail', product_id=product_id))
        try:
            rating = int(request.form.get('rating', 0))
        except (TypeError, ValueError):
            rating = 0
        comment = (request.form.get('comment') or '').strip()
        if rating < 1 or rating > 5:
            flash('Please choose a rating from 1 to 5 stars.', 'danger')
            return redirect(url_for('marketplace_detail', product_id=product_id))
        existing = Review.query.filter_by(reviewer_id=current_user.id, product_id=product_id).first()
        if existing:
            existing.rating = rating
            existing.comment = comment or existing.comment
            flash('Your review was updated.', 'success')
        else:
            review = Review(
                reviewer_id=current_user.id,
                product_id=product_id,
                target_user_id=product.user_id,
                rating=rating,
                comment=comment or None,
            )
            db.session.add(review)
            flash('Thank you for your review!', 'success')
        db.session.commit()
        return redirect(url_for('marketplace_detail', product_id=product_id))
    reviews = Review.query.filter_by(product_id=product_id).order_by(Review.created_at.desc()).all()
    avg = None
    if reviews:
        avg = round(sum(r.rating for r in reviews) / len(reviews), 1)
    user_review = None
    if current_user.is_authenticated:
        user_review = Review.query.filter_by(reviewer_id=current_user.id, product_id=product_id).first()
    return render_template(
        'marketplace_detail.html',
        product=product,
        reviews=reviews,
        avg_rating=avg,
        user_review=user_review,
    )


@app.route('/dashboard/products', methods=['GET', 'POST'])
@login_required
def manage_products():
    """Registered artisan/technician manages own products & services with image gallery."""
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        description = (request.form.get('description') or '').strip()
        category = (request.form.get('category') or 'product').strip().lower()
        if category not in ('product', 'service'):
            category = 'product'
        price = (request.form.get('price') or '').strip()
        if not title:
            flash('Title is required.', 'danger')
            return redirect(url_for('manage_products'))

        product = Product(
            user_id=current_user.id,
            title=title,
            description=description,
            category=category,
            price=price or None,
            is_active=True,
        )
        db.session.add(product)
        db.session.flush()  # get product.id

        files = request.files.getlist('images')
        if not files:
            single = request.files.get('image')
            files = [single] if single else []
        saved = 0
        for idx, file in enumerate(files):
            if not file or not file.filename or not allowed_file(file.filename):
                continue
            safe = secure_filename(file.filename)
            filename = f"{current_user.id}_{product.id}_{secrets.token_hex(6)}_{safe}"
            file.save(os.path.join(app.config['PRODUCT_UPLOAD_FOLDER'], filename))
            db.session.add(ProductImage(product_id=product.id, filename=filename, sort_order=idx))
            if saved == 0:
                product.image_filename = filename  # keep legacy cover in sync
            saved += 1
            if saved >= 12:
                break
        db.session.commit()
        flash(f'Listing published with {saved} photo{"s" if saved != 1 else ""}.', 'success')
        return redirect(url_for('manage_products'))
    my_products = Product.query.filter_by(user_id=current_user.id).order_by(Product.created_at.desc()).all()
    return render_template('manage_products.html', products=my_products)


@app.route('/dashboard/products/<int:product_id>/images', methods=['POST'])
@login_required
def add_product_images(product_id):
    """Add more photos to an existing product gallery."""
    product = Product.query.get_or_404(product_id)
    if product.user_id != current_user.id and current_user.role != 'admin':
        flash('Not allowed.', 'danger')
        return redirect(url_for('manage_products'))
    files = request.files.getlist('images')
    existing = len(product.images)
    if existing == 0 and product.image_filename:
        existing = 1
    saved = 0
    start = len(product.images)
    for file in files:
        if not file or not file.filename or not allowed_file(file.filename):
            continue
        if existing + saved >= 12:
            flash('Maximum 12 photos per listing.', 'warning')
            break
        safe = secure_filename(file.filename)
        filename = f"{current_user.id}_{product.id}_{secrets.token_hex(6)}_{safe}"
        file.save(os.path.join(app.config['PRODUCT_UPLOAD_FOLDER'], filename))
        db.session.add(ProductImage(product_id=product.id, filename=filename, sort_order=start + saved))
        if not product.image_filename:
            product.image_filename = filename
        saved += 1
    db.session.commit()
    flash(f'Added {saved} photo{"s" if saved != 1 else ""} to the gallery.', 'success')
    return redirect(url_for('manage_products'))


@app.route('/dashboard/products/image/<int:image_id>/delete', methods=['POST'])
@login_required
def delete_product_image(image_id):
    img = ProductImage.query.get_or_404(image_id)
    product = img.product
    if product.user_id != current_user.id and current_user.role != 'admin':
        flash('Not allowed.', 'danger')
        return redirect(url_for('manage_products'))
    path = os.path.join(app.config['PRODUCT_UPLOAD_FOLDER'], img.filename)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass
    was_cover = product.image_filename == img.filename
    db.session.delete(img)
    db.session.flush()
    if was_cover:
        remaining = ProductImage.query.filter_by(product_id=product.id).order_by(ProductImage.sort_order).first()
        product.image_filename = remaining.filename if remaining else None
    db.session.commit()
    flash('Photo removed from gallery.', 'success')
    return redirect(url_for('manage_products'))


@app.route('/dashboard/products/delete/<int:product_id>', methods=['POST'])
@login_required
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    if product.user_id != current_user.id and current_user.role != 'admin':
        flash('You can only remove your own listings.', 'danger')
        return redirect(url_for('manage_products'))
    filenames = [img.filename for img in product.images]
    if product.image_filename and product.image_filename not in filenames:
        filenames.append(product.image_filename)
    for fn in filenames:
        path = os.path.join(app.config['PRODUCT_UPLOAD_FOLDER'], fn)
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
    db.session.delete(product)
    db.session.commit()
    flash('Listing removed.', 'success')
    return redirect(url_for('manage_products'))


@app.route('/dashboard/products/toggle/<int:product_id>', methods=['POST'])
@login_required
def toggle_product(product_id):
    product = Product.query.get_or_404(product_id)
    if product.user_id != current_user.id and current_user.role != 'admin':
        flash('Not allowed.', 'danger')
        return redirect(url_for('manage_products'))
    product.is_active = not product.is_active
    db.session.commit()
    flash('Listing ' + ('published' if product.is_active else 'hidden') + '.', 'success')
    return redirect(url_for('manage_products'))


@app.route('/institutions')
def institutions():
    """Connect artisans/technicians with tertiary institutions, agencies and industry."""
    itype = request.args.get('type', '').strip()
    state = request.args.get('state', '').strip()
    query = User.query.filter(User.role == 'institution')
    if itype:
        query = query.filter(User.institution_type.ilike(f'%{itype}%'))
    if state:
        query = query.filter(User.location_state.ilike(f'%{state}%'))
    results = query.order_by(User.full_name).limit(80).all()
    return render_template(
        'institutions.html',
        results=results,
        types=INSTITUTION_TYPES,
        states=NIGERIA_STATES,
        itype=itype,
        state=state,
    )



BOT_UA_MARKERS = (
    'bot', 'crawl', 'spider', 'slurp', 'bingpreview', 'facebookexternalhit', 'whatsapp',
    'telegram', 'preview', 'headless', 'python-requests', 'curl/', 'wget', 'monitor', 'uptime',
)
VISIT_COOLDOWN = timedelta(hours=1)


def notify_profile_visit(member):
    """Tell a member (in-app + email) that someone opened their public profile.

    Skips the owner viewing their own page, non-GET requests and obvious crawlers /
    link-preview bots. One alert per visitor per profile per hour; at most one email per hour.
    """
    try:
        if request.method != 'GET':
            return
        ua = (request.headers.get('User-Agent') or '').lower()
        if not ua or any(m in ua for m in BOT_UA_MARKERS):
            return
        if current_user.is_authenticated and current_user.id == member.id:
            return

        now = datetime.utcnow()
        seen = session.get('profile_visits', {})
        last = seen.get(str(member.id))
        if last:
            try:
                if now - datetime.fromisoformat(last) < VISIT_COOLDOWN:
                    return
            except ValueError:
                pass

        if current_user.is_authenticated:
            visitor = current_user.full_name or 'A FAATN member'
            role_label = ROLES.get(current_user.role, '')
            who = f'{visitor} ({role_label})' if role_label else visitor
            message = f'{who} viewed your profile.'
        else:
            who = 'A visitor'
            message = 'A visitor viewed your public profile.'

        # Was there already a visit alert recently? (used to avoid flooding the inbox/email)
        recent = Notification.query.filter(
            Notification.user_id == member.id,
            Notification.type == 'visit',
            Notification.created_at > now - VISIT_COOLDOWN,
        ).first()

        db.session.add(Notification(
            user_id=member.id, title='Someone visited your profile',
            message=message, type='visit',
        ))
        db.session.commit()

        seen[str(member.id)] = now.isoformat()
        # keep the cookie small
        if len(seen) > 30:
            for k in sorted(seen, key=seen.get)[:len(seen) - 30]:
                seen.pop(k, None)
        session['profile_visits'] = seen

        if VISIT_EMAIL and not recent and member.email and member.email_notifications is not False:
            link = external_url('notifications')
            unsub_visit = unsubscribe_link(member.id)
            text = (
                f'Hello {member.full_name},\n\n{message}\n\n'
                f'See your notifications: {link}\n\nUnsubscribe from update emails: {unsub_visit}\n\n— FAATN-GATE'
            )
            html = _email_shell(
                'Someone visited your profile',
                f'<p>Hello {html_escape(member.full_name or "")},</p><p>{html_escape(message)}</p>',
                'View notifications', link, unsubscribe_url=unsub_visit,
            )
            send_email(member.email, 'Someone visited your FAATN-GATE profile', text, html, unsubscribe_url=unsub_visit)
    except Exception as exc:  # never break the public page because of a notification
        db.session.rollback()
        print(f'[visit] notification failed: {exc}', flush=True)


@app.route('/member/<int:user_id>')
def public_profile(user_id):
    """Public SEO profile — FAATN is master DB; Maps is integration only."""
    user = User.query.get_or_404(user_id)
    if user.role == 'admin':
        flash('Profile not available.', 'info')
        return redirect(url_for('gate'))
    notify_profile_visit(user)
    # Prefer listed members for public discovery
    return render_template('public_profile.html', member=user)


@app.route('/find')
def find_artisans():
    """Principal function: Find an Artisan / Technician by occupation, location, specialisation."""
    occupation = request.args.get('occupation', '').strip()
    state = request.args.get('state', '').strip()
    lga = request.args.get('lga', '').strip()
    town = request.args.get('town', '').strip()
    specialty = request.args.get('specialty', '').strip()
    role = request.args.get('role', '').strip()  # artisan | technician | ''
    listing = request.args.get('listing', '').strip()

    # Only FAATN-listed by default (credibility)
    query = User.query.filter(
        User.role.in_(['artisan', 'technician', 'engineer']),
        User.listing_category.in_(['registered', 'verified', 'accredited', 'partner']),
    )
    if listing and listing in LISTING_CATEGORIES:
        query = query.filter(User.listing_category == listing)
    if role in ('artisan', 'technician', 'engineer'):
        query = query.filter(User.role == role)
    if occupation:
        query = query.filter(User.occupation.ilike(f'%{occupation}%'))
    if state:
        query = query.filter(User.location_state.ilike(f'%{state}%'))
    if lga:
        query = query.filter(User.location_lga.ilike(f'%{lga}%'))
    if town:
        query = query.filter(User.location_community.ilike(f'%{town}%'))
    if specialty:
        like = f'%{specialty}%'
        query = query.filter(
            db.or_(User.specialty.ilike(like), User.skills.ilike(like), User.occupation.ilike(like))
        )

    results = query.order_by(User.listing_category.desc(), User.full_name).limit(80).all()

    return render_template(
        'find.html',
        results=results,
        occupations=OCCUPATIONS,
        states=NIGERIA_STATES,
        occupation=occupation,
        state=state,
        lga=lga,
        town=town,
        specialty=specialty,
        role=role,
        listing=listing,
        listing_categories=LISTING_CATEGORIES,
        searched=bool(request.args),
    )


@app.route('/dashboard/directory')
@login_required
def directory():
    """Member directory — badges show FAATN-Registered / Verified / Partner / Public."""
    q = request.args.get('q', '').strip()
    role_filter = request.args.get('role', '')
    state_filter = request.args.get('state', '')
    listing_filter = request.args.get('listing', '')

    query = User.query.filter(
        User.id != current_user.id,
        User.role.in_(list(STAKEHOLDER_ROLES)),
    )

    # Default: show FAATN-Registered + Verified + Partner (not raw public-only unless filtered)
    if listing_filter:
        query = query.filter(User.listing_category == listing_filter)
    else:
        query = query.filter(User.listing_category.in_(['registered', 'verified', 'accredited', 'partner']))

    if q:
        like = f'%{q}%'
        query = query.filter(
            db.or_(
                User.full_name.ilike(like),
                User.occupation.ilike(like),
                User.specialty.ilike(like),
                User.skills.ilike(like),
                User.location_state.ilike(like),
            )
        )
    if role_filter:
        query = query.filter(User.role == role_filter)
    if state_filter:
        query = query.filter(User.location_state.ilike(f'%{state_filter}%'))

    members = query.order_by(User.full_name).limit(100).all()
    return render_template(
        'directory.html',
        members=members,
        q=q,
        role_filter=role_filter,
        state_filter=state_filter,
        listing_filter=listing_filter,
        listing_categories=LISTING_CATEGORIES,
    )


@app.route('/dashboard/messages')
@login_required
def messages():
    """Inbox: every message sent to this user appears here (peer + system/admin)."""
    # Incoming
    incoming = Message.query.filter_by(recipient_id=current_user.id).order_by(Message.created_at.desc()).all()
    # Outgoing peer messages
    outgoing = Message.query.filter_by(sender_id=current_user.id).order_by(Message.created_at.desc()).all()

    # Build unique conversation partners
    # System/admin messages group by sender_name so each broadcast is readable in inbox
    partners = {}
    for m in incoming:
        if m.sender_id:
            key = f'user-{m.sender_id}'
        else:
            key = f'system-{(m.sender_name or "System").strip()}'
        if key not in partners:
            partners[key] = {
                'user': m.sender if m.sender_id else None,
                'name': m.sender_name or 'System',
                'last_msg': m,
                'unread': 0,
                'is_system': m.sender_id is None,
            }
        if not m.is_read:
            partners[key]['unread'] += 1
        if m.created_at > partners[key]['last_msg'].created_at:
            partners[key]['last_msg'] = m

    for m in outgoing:
        key = f'user-{m.recipient_id}'
        if key not in partners:
            recipient = User.query.get(m.recipient_id)
            partners[key] = {
                'user': recipient,
                'name': recipient.full_name if recipient else 'Unknown',
                'last_msg': m,
                'unread': 0,
                'is_system': False,
            }
        if m.created_at > partners[key]['last_msg'].created_at:
            partners[key]['last_msg'] = m

    # Opening inbox marks all received messages as read
    for m in incoming:
        if not m.is_read:
            m.is_read = True
    db.session.commit()

    # Sort by last message time
    conv_list = sorted(partners.values(), key=lambda x: x['last_msg'].created_at, reverse=True)
    return render_template('messages.html', conversations=conv_list)


@app.route('/dashboard/chat/<int:user_id>', methods=['GET', 'POST'])
@login_required
def chat(user_id):
    """Chat thread with another member (text + optional image)."""
    other = User.query.get_or_404(user_id)
    if other.id == current_user.id:
        flash('You cannot chat with yourself.', 'warning')
        return redirect(url_for('directory'))

    if request.method == 'POST':
        body = request.form.get('body', '').strip()
        file = request.files.get('image')
        image_filename = None

        if file and file.filename and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            image_filename = secure_filename(f"chat_{current_user.id}_{secrets.token_hex(6)}.{ext}")
            file.save(os.path.join(app.config['CHAT_UPLOAD_FOLDER'], image_filename))

        if body or image_filename:
            # Deliver to recipient's Messages inbox + notification
            deliver_to_inbox(
                recipient_id=other.id,
                body=body,
                subject=f'Chat with {current_user.full_name}',
                sender_id=current_user.id,
                sender_name=current_user.full_name,
                image_filename=image_filename,
                notif_title=f'New message from {current_user.full_name}',
                notif_type='info',
            )
            flash('Message sent to their inbox.', 'success')
            return redirect(url_for('chat', user_id=other.id))
        else:
            flash('Write a message or attach an image.', 'danger')

    thread = Message.query.filter(
        db.or_(
            db.and_(Message.sender_id == current_user.id, Message.recipient_id == other.id),
            db.and_(Message.sender_id == other.id, Message.recipient_id == current_user.id)
        )
    ).order_by(Message.created_at.asc()).all()

    for m in thread:
        if m.recipient_id == current_user.id and not m.is_read:
            m.is_read = True
    db.session.commit()

    return render_template('chat.html', other=other, thread=thread)


@app.route('/dashboard/notifications')
@login_required
def notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    for n in notifs:
        n.is_read = True
    db.session.commit()
    return render_template('notifications.html', notifications=notifs)


# Admin simple view
def get_connection_metrics():
    """SQLAlchemy pool stats + PostgreSQL session counts (admin monitoring)."""
    metrics = {
        'pool': {},
        'postgres': {},
        'error': None,
    }
    try:
        engine = db.engine
        pool = engine.pool
        # QueuePool status (SQLAlchemy 1.4/2.0)
        metrics['pool'] = {
            'driver': str(engine.url.drivername),
            'database': engine.url.database,
            'host': engine.url.host,
            'pool_class': pool.__class__.__name__,
            'size': pool.size() if hasattr(pool, 'size') else app.config.get('SQLALCHEMY_ENGINE_OPTIONS', {}).get('pool_size'),
            'checked_in': pool.checkedin() if hasattr(pool, 'checkedin') else None,
            'checked_out': pool.checkedout() if hasattr(pool, 'checkedout') else None,
            'overflow': pool.overflow() if hasattr(pool, 'overflow') else None,
            'status': pool.status() if hasattr(pool, 'status') else None,
        }

        # Live PostgreSQL metrics
        with engine.connect() as conn:
            row = conn.exec_driver_sql(
                "SELECT count(*) AS total, "
                "count(*) FILTER (WHERE state = 'active') AS active, "
                "count(*) FILTER (WHERE state = 'idle') AS idle, "
                "count(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_tx "
                "FROM pg_stat_activity WHERE datname = current_database()"
            ).mappings().first()
            if row:
                metrics['postgres'] = dict(row)

            max_conn = conn.exec_driver_sql("SHOW max_connections").scalar()
            metrics['postgres']['max_connections'] = int(max_conn) if max_conn else None

            version = conn.exec_driver_sql("SHOW server_version").scalar()
            metrics['postgres']['server_version'] = version
    except Exception as e:
        metrics['error'] = str(e)
    return metrics


@app.route('/dashboard/admin')
@admin_required
def admin_dashboard():
    search = (request.args.get('q') or '').strip()
    uq = User.query.order_by(User.created_at.desc())
    if search:
        like = f'%{search}%'
        uq = uq.filter(db.or_(User.full_name.ilike(like), User.email.ilike(like),
                              User.phone.ilike(like), User.role.ilike(like)))
    users = uq.limit(100 if search else 30).all()
    total_users = User.query.count()
    total_opps = Opportunity.query.count()
    total_innov = Innovation.query.count()
    stats = {
        'artisans': User.query.filter_by(role='artisan').count(),
        'technicians': User.query.filter_by(role='technician').count(),
        'suppliers': User.query.filter(db.or_(User.role.in_(['supplier', 'industry']), User.listing_category == 'partner')).count(),
        'verified': User.query.filter_by(listing_category='verified').count(),
        'accredited': User.query.filter_by(listing_category='accredited').count(),
        'registered': User.query.filter_by(listing_category='registered').count(),
        'states_covered': db.session.query(User.location_state).filter(User.location_state.isnot(None), User.location_state != '').distinct().count(),
        'lgas_covered': db.session.query(User.location_lga).filter(User.location_lga.isnot(None), User.location_lga != '').distinct().count(),
        'help_open': HelpRequest.query.filter_by(status='open').count() if 'HelpRequest' in dir() else 0,
    }
    try:
        stats['help_open'] = HelpRequest.query.filter_by(status='open').count()
    except Exception:
        stats['help_open'] = 0
    db_metrics = get_connection_metrics()
    n_admins = admin_count()
    return render_template(
        'dashboard_admin.html',
        users=users,
        search=search,
        trash_count=TrashedUser.query.count(),
        total_users=total_users,
        total_opps=total_opps,
        total_innov=total_innov,
        db_metrics=db_metrics,
        listing_categories=LISTING_CATEGORIES,
        stats=stats,
        roles=ROLES,
        stakeholder_roles=STAKEHOLDER_ROLES,
        occupations=OCCUPATIONS,
        admin_count=n_admins,
        max_admins=MAX_ADMINS,
        can_create_admin=n_admins < MAX_ADMINS,
        mail_transport=mail_transport(),
        weak_password=any(current_user.check_password(p) for p in KNOWN_PUBLIC_PASSWORDS),
    )



@app.route('/dashboard/admin/listing/<int:user_id>', methods=['POST'])
@admin_required
def set_listing_category(user_id):
    """Admin sets credibility category: public | registered | verified | partner."""
    user = User.query.get_or_404(user_id)
    cat = request.form.get('listing_category', 'public').strip().lower()
    if cat not in LISTING_CATEGORIES:
        flash('Invalid listing category.', 'danger')
        return redirect(url_for('admin_dashboard'))
    user.listing_category = cat
    user.verified = (cat == 'verified')
    db.session.commit()
    flash(f'{user.full_name} is now marked: {LISTING_CATEGORIES[cat]}.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/dashboard/admin/send-notification', methods=['GET', 'POST'])
@admin_required
def admin_send_notification():
    """Admin sends a notification (in-app inbox + notification bell, optionally email)
    to registered users.

    Audience options:
      * one specific registered user (``user_id``), or
      * a group: all registered users, or one role, optionally narrowed by a keyword
        matching occupation / specialty / skills / needs (e.g. 'massage').
    """
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        message = (request.form.get('message') or '').strip()
        notif_type = (request.form.get('type') or 'info').strip()
        keyword = (request.form.get('keyword') or '').strip().lower()
        target_role = (request.form.get('target_role') or 'all').strip().lower()
        target_user_id = (request.form.get('user_id') or '').strip()
        also_email = request.form.get('send_email') == '1'

        if not title or not message:
            flash('Title and message are required.', 'danger')
            return redirect(url_for('admin_send_notification', user_id=target_user_id or None))

        allowed_types = {'info', 'success', 'warning', 'opportunity', 'training'}
        if notif_type not in allowed_types:
            notif_type = 'info'

        if target_user_id:
            # One specific registered user
            single = User.query.get(int(target_user_id)) if target_user_id.isdigit() else None
            if not single:
                flash('That user no longer exists.', 'danger')
                return redirect(url_for('admin_send_notification'))
            recipients = [single]
        else:
            # Every registered user except admins; optionally one role
            q = User.query.filter(User.role != 'admin')
            if target_role in STAKEHOLDER_ROLES:
                q = q.filter(User.role == target_role)
            if keyword:
                like = f'%{keyword}%'
                q = q.filter(
                    db.or_(
                        User.occupation.ilike(like),
                        User.specialty.ilike(like),
                        User.skills.ilike(like),
                        User.needs.ilike(like),
                    )
                )
            recipients = q.all()

        if not recipients:
            flash('No registered users match that selection.', 'warning')
            return redirect(url_for('admin_send_notification'))

        emailed = 0
        link = external_url('notifications')
        for u in recipients:
            # Goes to Messages inbox AND Notifications
            deliver_to_inbox(
                recipient_id=u.id,
                body=message,
                subject=title,
                sender_id=None,
                sender_name='FAATN Admin',
                notif_title=title,
                notif_type=notif_type,
                commit=False,
            )
        db.session.commit()

        if also_email:
            for u in recipients:
                if not u.email or u.email_notifications is False:
                    continue
                unsub = unsubscribe_link(u.id)
                text = f'Hello {u.full_name},\n\n{message}\n\nOpen your notifications: {link}\n\nUnsubscribe from update emails: {unsub}\n\n- FAATN-GATE'
                html = _email_shell(
                    title,
                    f'<p>Hello {html_escape(u.full_name or "")},</p>'
                    f'<p style="white-space:pre-line;">{html_escape(message)}</p>',
                    'View notifications', link, unsubscribe_url=unsub,
                )
                if send_email(u.email, title, text, html, unsubscribe_url=unsub):
                    emailed += 1

        if len(recipients) == 1:
            result = f'Notification sent to {recipients[0].full_name}.'
        else:
            result = (f'Notification delivered to {len(recipients)} registered user(s)'
                      + (f' matching "{keyword}"' if keyword else '') + '.')
        if also_email:
            result += (f' Email queued for {emailed}.' if mail_configured()
                       else ' Email is not configured on the server, so only in-app delivery was made.')
        flash(result, 'success')
        return redirect(url_for('admin_dashboard'))

    selected_user = None
    uid = request.args.get('user_id', '')
    if uid.isdigit():
        selected_user = User.query.get(int(uid))
    return render_template(
        'admin_send_notification.html',
        occupations=OCCUPATIONS,
        roles=ROLES,
        stakeholder_roles=STAKEHOLDER_ROLES,
        selected_user=selected_user,
    )


@app.route('/dashboard/admin/create-user', methods=['POST'])
@admin_required
def admin_create_user():
    """Admin creates an account (member, or a 2nd admin: max MAX_ADMINS).

    The new user is emailed a one-time link to choose their OWN password; the password itself is
    never put in an email. Leave the password blank to have a strong one generated."""
    email = (request.form.get('email') or '').strip().lower()
    full_name = (request.form.get('full_name') or '').strip()
    typed = request.form.get('password') or ''
    role = (request.form.get('role') or 'artisan').strip().lower()
    phone = (request.form.get('phone') or '').strip()
    location_state = (request.form.get('location_state') or '').strip()
    occupation = (request.form.get('occupation') or '').strip()
    send_welcome = request.form.get('send_welcome') == '1'

    if not full_name:
        flash('Full name is required.', 'danger')
        return redirect(url_for('admin_dashboard'))
    if not is_valid_email(email):
        flash('Enter a valid email address.', 'danger')
        return redirect(url_for('admin_dashboard'))
    if typed and len(typed) < 6:
        flash('Password must be at least 6 characters (or leave it blank to generate one).', 'danger')
        return redirect(url_for('admin_dashboard'))
    if role not in list(STAKEHOLDER_ROLES) + ['admin']:
        flash('Invalid role.', 'danger')
        return redirect(url_for('admin_dashboard'))
    if User.query.filter(db.func.lower(User.email) == email).first():
        flash(f'Email {email} is already registered.', 'warning')
        return redirect(url_for('admin_dashboard'))
    if role == 'admin' and not can_create_admin():
        flash(f'Maximum of {MAX_ADMINS} administrator accounts allowed. Cannot create another admin.', 'danger')
        return redirect(url_for('admin_dashboard'))

    password = typed or secrets.token_urlsafe(9)
    user = User(
        email=email,
        full_name=full_name,
        phone=phone or None,
        role=role,
        location_state=location_state or None,
        occupation=occupation or None,
        verified=(role == 'admin'),
        email_verified=True,  # an administrator vouches for this address
        listing_category='verified' if role == 'admin' else (
            'registered' if role in MEMBER_ROLES else 'public'
        ),
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    msg = f'User {full_name} ({email}) created as {ROLES.get(role, role)}.'
    link = None
    if send_welcome:
        token = secrets.token_urlsafe(32)
        user.reset_token = token
        user.reset_token_expires = datetime.utcnow() + timedelta(hours=48)
        db.session.commit()
        if send_welcome_email(user, token, 48):
            msg += ' A welcome email with a set-your-password link was sent to their inbox.'
        elif mail_configured():
            msg += ' The welcome email could not be queued.'
        else:
            link = external_url('reset_password', token=token)
            msg += f' Email is not configured, so share this set-password link yourself (valid 48 hours): {link}'
    if not typed:
        msg += f' Temporary password (shown once): {password}'
    flash(msg, 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/dashboard/admin/user/<int:user_id>/reset-password', methods=['POST'])
@admin_required
def admin_reset_password(user_id):
    """Admin resets a user's password: email them a reset link, or set a new one.

    The user is always told (by email) that the password changed, but the email never contains it."""
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('To change your own password use the "Change password" card on your Profile page.', 'warning')
        return redirect(url_for('admin_dashboard'))

    mode = (request.form.get('mode') or 'link').strip().lower()  # link | set
    new_password = (request.form.get('new_password') or '').strip()

    if mode == 'set':
        if user.role == 'admin':
            flash("For safety you cannot set another administrator's password. Send them a reset link instead.", 'danger')
            return redirect(url_for('admin_dashboard'))
        if new_password and len(new_password) < 6:
            flash('New password must be at least 6 characters (or leave it blank to generate one).', 'danger')
            return redirect(url_for('admin_dashboard'))
        password = new_password or secrets.token_urlsafe(9)
        user.set_password(password)
        user.reset_token = None
        user.reset_token_expires = None
        db.session.commit()
        send_password_changed_email(user, by_admin=True)
        flash(f'New password for {user.full_name} (shown once, share it privately): {password}', 'warning')
        return redirect(url_for('admin_dashboard'))

    token = secrets.token_urlsafe(32)
    user.reset_token = token
    user.reset_token_expires = datetime.utcnow() + timedelta(hours=2)
    db.session.commit()
    if send_reset_email(user, token):
        flash(f'Password reset link emailed to {user.email} (valid 2 hours).', 'success')
    elif mail_configured():
        flash(f'Reset link generated but email failed for {user.email}. Check mail logs.', 'warning')
    else:
        flash(f'Email not configured. Share this reset link securely (valid 2 hours): {external_url("reset_password", token=token)}', 'info')
    return redirect(url_for('admin_dashboard'))


@app.route('/dashboard/admin/test-email', methods=['POST'])
@admin_required
def admin_test_email():
    html = _email_shell('Test email', '<p>If you can read this, FAATN-GATE email delivery works.</p>')
    ok, err = send_email_now(current_user.email, 'FAATN-GATE test email',
                             'If you can read this, FAATN-GATE email delivery works.', html)
    flash(f'Test email sent to {current_user.email}. Check the inbox (and spam).' if ok else f'Test email FAILED: {err}',
          'success' if ok else 'danger')
    return redirect(url_for('admin_dashboard'))


@app.route('/dashboard/admin/user/<int:user_id>/delete', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    """Admin removes a registered user. A full copy is kept in Trash until an admin
    permanently deletes it (or restores it)."""
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('admin_dashboard'))
    if user.role == 'admin':
        flash('Admin accounts cannot be deleted from here.', 'danger')
        return redirect(url_for('admin_dashboard'))

    name, email = user.full_name, user.email
    try:
        trash_user(user, current_user)
    except Exception as exc:
        db.session.rollback()
        print(f'[admin] move user {user_id} to trash failed: {exc}', flush=True)
        flash('Could not delete that user. Nothing was changed.', 'danger')
        return redirect(url_for('admin_dashboard'))
    flash(f'{name} ({email}) was removed and a copy was kept in Trash. '
          'Open Trash to restore or permanently delete.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/dashboard/admin/trash')
@admin_required
def admin_trash():
    items = TrashedUser.query.order_by(TrashedUser.deleted_at.desc()).all()
    return render_template('admin_trash.html', items=items)


@app.route('/dashboard/admin/trash/<int:trash_id>/restore', methods=['POST'])
@admin_required
def admin_trash_restore(trash_id):
    item = TrashedUser.query.get_or_404(trash_id)
    name = item.full_name
    try:
        ok, msg = restore_user(item)
    except Exception as exc:
        db.session.rollback()
        print(f'[admin] restore trash {trash_id} failed: {exc}', flush=True)
        ok, msg = False, 'Restore failed. Nothing was changed.'
    flash(msg if not ok else f'{name} was restored with their data.', 'success' if ok else 'danger')
    return redirect(url_for('admin_trash'))


@app.route('/dashboard/admin/trash/<int:trash_id>/delete', methods=['POST'])
@admin_required
def admin_trash_delete(trash_id):
    """Final approval: permanently erase the Trash copy (database record + files)."""
    item = TrashedUser.query.get_or_404(trash_id)
    name, email = item.full_name, item.email
    tid = item.id
    db.session.delete(item)
    db.session.commit()
    shutil.rmtree(os.path.join(app.config['TRASH_FOLDER'], str(tid)), ignore_errors=True)
    flash(f'{name} ({email}) was permanently deleted. This cannot be undone.', 'success')
    return redirect(url_for('admin_trash'))


@app.route('/dashboard/admin/db-metrics')
@admin_required
def admin_db_metrics():
    """JSON endpoint for connection pool monitoring (admin only)."""
    if not is_admin(current_user):
        return jsonify({'error': 'Access denied'}), 403
    return jsonify(get_connection_metrics())


# ==================== SEED DATA ====================

DEFAULT_ADMIN_EMAIL = 'admin@faatn.ng'   # the old default admin (public password) - see retire_default_admin()
KNOWN_PUBLIC_PASSWORDS = ('change-me-on-first-login', 'Admin@FAATN2026')


def create_admin_account(email, full_name, password):
    """Create an administrator. Returns (user, error). Enforces MAX_ADMINS."""
    email = (email or '').strip().lower()
    if not is_valid_email(email):
        return None, 'Enter a valid email address.'
    if len(password or '') < 8:
        return None, 'Admin password must be at least 8 characters.'
    if not can_create_admin():
        return None, f'The maximum of {MAX_ADMINS} administrators is already in use.'
    if User.query.filter(db.func.lower(User.email) == email).first():
        return None, 'That email is already registered.'
    admin = User(
        email=email, full_name=(full_name or 'FAATN Administrator').strip(), role='admin',
        location_state='FCT', occupation='System Admin', verified=True, email_verified=True,
        listing_category='verified',
    )
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    return admin, None


def _seed_sample_content(admin):
    """Sample trainings / opportunities / event (NOT accounts), created only with the very first admin."""
    # Trainings
    trainings = [
        Training(title='Advanced Woodworking & CNC Operation', provider='FAATN Skills Hub - Anambra', description='Master modern CNC machines and precision woodworking techniques for high-value furniture production.', duration='6 weeks', skill_gap='CNC & Digital Fabrication', location='Awka, Anambra'),
        Training(title='Solar Hybrid Systems Certification', provider='NSE / FAATN Partnership', description='Comprehensive training on hybrid solar systems, battery management and grid-tie installations.', duration='4 weeks', skill_gap='Renewable Energy Systems', location='Kano & Online'),
        Training(title='Business & Market Access for Artisans', provider='FAATN Enterprise Unit', description='Learn pricing, packaging, digital marketing and how to win contracts from industry partners.', duration='3 weeks', skill_gap='Business Skills', location='Nationwide (Hybrid)'),
        Training(title='Welding & Metal Fabrication (Advanced)', provider='Industrial Training Centre', description='TIG/MIG welding, structural fabrication and quality control for construction and manufacturing.', duration='8 weeks', skill_gap='Metalwork', location='Lagos'),
    ]
    for t in trainings:
        db.session.add(t)

    # Opportunities
    opps = [
        Opportunity(title='Furniture Supply Contract - Hotel Renovation', description='Supply and install custom furniture for a 40-room boutique hotel in Enugu. Quality Nigerian hardwood preferred.', type='contract', requirements='Proven furniture portfolio, ability to deliver within 8 weeks, registered business preferred.', location='Enugu', skills_needed='Carpentry, Furniture Making', posted_by='GreenStay Hotels Ltd', deadline=datetime(2026, 11, 30).date()),
        Opportunity(title='Solar Installation Team - 50 Households', description='Seeking certified solar technicians for a community solar project in Northern Nigeria.', type='project', requirements='Solar installation experience, ability to work in teams, valid ID.', location='Kano / Katsina', skills_needed='Solar PV, Electrical', posted_by='Rural Electrification Agency Partner', deadline=datetime(2026, 10, 15).date()),
        Opportunity(title='Artisan Innovation Grant 2026', description='Grants of ₦500,000 – ₦2,000,000 for innovative products or processes developed by Nigerian artisans.', type='grant', requirements='Registered on FAATN-GATE, clear innovation proposal, prototype preferred.', location='Nationwide', skills_needed='Any technical skill + Innovation', posted_by='FAATN Innovation Fund', deadline=datetime(2026, 12, 31).date()),
        Opportunity(title='Maintenance Technician - Manufacturing Plant', description='Full-time electrical/mechanical technician for a food processing plant.', type='job', requirements='Minimum 3 years experience, technical certificate, readiness to relocate.', location='Ogun State', skills_needed='Electrical, Mechanical Maintenance', posted_by='AgroProcess Industries', deadline=datetime(2026, 9, 30).date()),
    ]
    for o in opps:
        db.session.add(o)

    db.session.commit()

    # Sample FAATN event
    sample_event = Event(
        title='FAATN Skills & Innovation Fair 2026',
        description='National gathering of artisans, technicians and engineers. Exhibitions, live demos, training sign-ups and partner networking.',
        location='Umuaka, Njaba LGA, Imo State',
        event_date=datetime(2026, 11, 15).date(),
        event_time='9:00 AM',
        created_by_id=admin.id,
        is_active=True,
    )
    db.session.add(sample_event)

    db.session.commit()
    print('✅ Database seeded successfully!')


def seed_data():
    """No demo accounts and NO default password.

    The first administrator comes from ADMIN_EMAIL + ADMIN_PASSWORD (or `flask create-admin`).
    With ADMIN_EMAIL + ADMIN_PASSWORD set, a missing admin is also added later (max MAX_ADMINS)."""
    email = os.environ.get('ADMIN_EMAIL', '').strip().lower()
    password = os.environ.get('ADMIN_PASSWORD', '')
    first_run = admin_count() == 0
    if not password:
        if first_run:
            print('⚠️  No administrator exists. Set ADMIN_EMAIL and ADMIN_PASSWORD, or run: flask create-admin you@example.com', flush=True)
        return
    email = email or DEFAULT_ADMIN_EMAIL
    if not first_run and User.query.filter(db.func.lower(User.email) == email).first():
        return  # already created on an earlier start
    admin, err = create_admin_account(email, os.environ.get('ADMIN_NAME', 'FAATN Administrator'), password)
    if not admin:
        print(f'⚠️  Administrator from environment not created: {err}', flush=True)
        return
    print(f'✅ Administrator {admin.email} created from environment.', flush=True)
    if first_run:
        _seed_sample_content(admin)


@app.cli.command('create-admin')
@click.argument('email')
@click.option('--name', default='FAATN Administrator', show_default=True)
@click.password_option()
def create_admin_command(email, name, password):
    """Create an administrator (max 2):  flask create-admin you@example.com"""
    admin, err = create_admin_account(email, name, password)
    print(f'Administrator {admin.email} created.' if admin else f'Not created: {err}')


def retire_default_admin():
    """Remove admin@faatn.ng, but ONLY if it still uses a publicly known password AND another
    administrator exists. If you changed its password it is left alone."""
    old = User.query.filter(db.func.lower(User.email) == DEFAULT_ADMIN_EMAIL, User.role == 'admin').first()
    if not old or not any(old.check_password(p) for p in KNOWN_PUBLIC_PASSWORDS):
        return
    if User.query.filter(User.role == 'admin', User.id != old.id).count() == 0:
        print('⚠️  SECURITY: admin@faatn.ng still uses a public default password. Set ADMIN_EMAIL and '
              'ADMIN_PASSWORD (a different email) and restart: it will then be removed automatically.', flush=True)
        return
    purge_users([old.id])
    print('🧹 Removed the default admin account (it used a public password).', flush=True)


# Legacy demo accounts (removed safely on every app start)
DEMO_EMAILS = (
    'artisan@demo.ng',
    'tech@demo.ng',
    'engineer@demo.ng',
    'demo@faatn.ng',
    'demo@demo.ng',
    'test@demo.ng',
)


def _safe_remove(folder, filename):
    """Delete an uploaded file; ignore missing files and path tricks."""
    if not filename:
        return
    try:
        path = os.path.join(folder, os.path.basename(filename))
        if os.path.isfile(path):
            os.remove(path)
    except OSError as exc:
        print(f'[cleanup] could not remove {filename}: {exc}', flush=True)


def purge_users(ids):
    """Permanently delete users and everything tied to them (DB rows + uploaded files).

    Used by the admin "Delete user" action and by remove_demo_data().
    Raises on failure (caller should rollback).
    """
    ids = list(ids)
    if not ids:
        return

    users = User.query.filter(User.id.in_(ids)).all()
    emails = [u.email for u in users if u.email]

    # Collect uploaded files first; remove them only after the DB commit succeeds
    avatar_files = [u.profile_pic for u in users if u.profile_pic]
    chat_files = [
        m.image_filename for m in Message.query.filter(
            db.or_(Message.recipient_id.in_(ids), Message.sender_id.in_(ids)),
            Message.image_filename.isnot(None),
        ).all()
    ]
    product_files = []

    # Their marketplace listings (images and reviews of those products cascade)
    for prod in Product.query.filter(Product.user_id.in_(ids)).all():
        if prod.image_filename:
            product_files.append(prod.image_filename)
        product_files.extend(img.filename for img in prod.images)
        db.session.delete(prod)
    db.session.flush()

    TrainingEnrollment.query.filter(TrainingEnrollment.user_id.in_(ids)).delete(synchronize_session=False)
    Innovation.query.filter(Innovation.user_id.in_(ids)).delete(synchronize_session=False)
    OpportunityApplication.query.filter(OpportunityApplication.user_id.in_(ids)).delete(synchronize_session=False)
    Notification.query.filter(Notification.user_id.in_(ids)).delete(synchronize_session=False)
    Message.query.filter(
        db.or_(Message.recipient_id.in_(ids), Message.sender_id.in_(ids))
    ).delete(synchronize_session=False)
    Review.query.filter(
        db.or_(Review.reviewer_id.in_(ids), Review.target_user_id.in_(ids))
    ).delete(synchronize_session=False)

    # Help requests the user submitted (linked by account or by their email address)
    help_filter = HelpRequest.user_id.in_(ids)
    if emails:
        help_filter = db.or_(help_filter, db.func.lower(HelpRequest.requester_email).in_([e.lower() for e in emails]))
    HelpRequest.query.filter(help_filter).delete(synchronize_session=False)

    # Public content keeps existing, just no longer points at a deleted user
    Event.query.filter(Event.created_by_id.in_(ids)).update({'created_by_id': None}, synchronize_session=False)
    GalleryItem.query.filter(GalleryItem.created_by_id.in_(ids)).update({'created_by_id': None}, synchronize_session=False)

    for u in users:
        db.session.delete(u)
    db.session.commit()

    for fn in avatar_files:
        _safe_remove(app.config['UPLOAD_FOLDER'], fn)
    for fn in chat_files:
        _safe_remove(app.config['CHAT_UPLOAD_FOLDER'], fn)
    for fn in product_files:
        _safe_remove(app.config['PRODUCT_UPLOAD_FOLDER'], fn)


def _row_to_json(obj):
    out = {}
    for col in obj.__table__.columns:
        v = getattr(obj, col.name)
        if isinstance(v, (datetime, date)):
            v = v.isoformat()
        out[col.name] = v
    return out


def _row_from_json(model, row, **overrides):
    """Build a model instance from a snapshot row (id dropped so a fresh one is assigned)."""
    kwargs = {}
    for col in model.__table__.columns:
        if col.name == 'id' or col.name not in row:
            continue
        v = row[col.name]
        if isinstance(v, str):
            try:
                pt = col.type.python_type
                if pt is datetime:
                    v = datetime.fromisoformat(v)
                elif pt is date:
                    v = date.fromisoformat(v)
            except (NotImplementedError, ValueError):
                pass
        kwargs[col.name] = v
    kwargs.update(overrides)
    return model(**kwargs)


_TRASH_FILE_FOLDERS = {
    'avatars': 'UPLOAD_FOLDER',
    'chat': 'CHAT_UPLOAD_FOLDER',
    'products': 'PRODUCT_UPLOAD_FOLDER',
}


def trash_user(user, admin):
    """Copy a user's data + files into Trash, then remove them from the live site."""
    uid = user.id
    emails = [user.email.lower()] if user.email else []

    prods = Product.query.filter(Product.user_id == uid).all()
    pids = [p.id for p in prods]
    msgs = Message.query.filter(db.or_(Message.recipient_id == uid, Message.sender_id == uid)).all()
    rev_filter = db.or_(Review.reviewer_id == uid, Review.target_user_id == uid)
    if pids:
        rev_filter = db.or_(rev_filter, Review.product_id.in_(pids))
    reviews = Review.query.filter(rev_filter).all()
    help_filter = HelpRequest.user_id == uid
    if emails:
        help_filter = db.or_(help_filter, db.func.lower(HelpRequest.requester_email).in_(emails))
    helps = HelpRequest.query.filter(help_filter).all()

    snap = {
        'user': _row_to_json(user),
        'enrollments': [_row_to_json(x) for x in TrainingEnrollment.query.filter_by(user_id=uid)],
        'innovations': [_row_to_json(x) for x in Innovation.query.filter_by(user_id=uid)],
        'applications': [_row_to_json(x) for x in OpportunityApplication.query.filter_by(user_id=uid)],
        'notifications': [_row_to_json(x) for x in Notification.query.filter_by(user_id=uid)],
        'messages': [_row_to_json(x) for x in msgs],
        'products': [dict(_row_to_json(p), _images=[_row_to_json(i) for i in p.images]) for p in prods],
        'reviews': [_row_to_json(x) for x in reviews],
        'help_requests': [_row_to_json(x) for x in helps],
        'event_ids': [e.id for e in Event.query.filter_by(created_by_id=uid)],
        'gallery_ids': [g.id for g in GalleryItem.query.filter_by(created_by_id=uid)],
    }
    summary_bits = [
        (len(msgs), 'message'), (len(prods), 'product'), (len(reviews), 'review'),
        (len(snap['innovations']), 'innovation'), (len(snap['applications']), 'application'),
        (len(snap['notifications']), 'notification'), (len(helps), 'help request'),
    ]
    summary = ', '.join(f'{n} {w}{"" if n == 1 else "s"}' for n, w in summary_bits if n) or 'profile only'

    item = TrashedUser(
        original_user_id=uid, email=user.email, full_name=user.full_name, role=user.role,
        summary=summary, snapshot=json.dumps(snap), deleted_by_name=getattr(admin, 'full_name', None),
    )
    db.session.add(item)
    db.session.flush()  # get item.id

    # Copy uploaded files into the (non-public) trash folder
    files = {'avatars': [user.profile_pic] if user.profile_pic else [],
             'chat': [m.image_filename for m in msgs if m.image_filename],
             'products': [p.image_filename for p in prods if p.image_filename]
                         + [i.filename for p in prods for i in p.images]}
    trash_dir = os.path.join(app.config['TRASH_FOLDER'], str(item.id))
    try:
        for kind, names in files.items():
            for fn in names:
                src = os.path.join(app.config[_TRASH_FILE_FOLDERS[kind]], os.path.basename(fn))
                if os.path.isfile(src):
                    os.makedirs(os.path.join(trash_dir, kind), exist_ok=True)
                    shutil.copy2(src, os.path.join(trash_dir, kind, os.path.basename(fn)))
        purge_users([uid])   # commits the TrashedUser row and the deletion together
    except Exception:
        db.session.rollback()
        shutil.rmtree(trash_dir, ignore_errors=True)
        raise


def restore_user(item):
    """Bring a trashed user back with their data. Returns (ok, message)."""
    snap = json.loads(item.snapshot)
    u = snap['user']
    if User.query.filter(db.func.lower(User.email) == (u.get('email') or '').lower()).first():
        return False, (f'Cannot restore: the email {u.get("email")} is now used by another account. '
                       'Delete or change that account first.')

    old_uid = u['id']
    new_user = _row_from_json(User, u)
    if not User.query.get(old_uid):
        new_user.id = old_uid          # keep the original id when it is still free
    db.session.add(new_user)
    db.session.flush()
    new_uid = new_user.id

    def user_exists(i):
        return i is None or i == old_uid or User.query.get(i) is not None

    def map_user(i):
        return new_uid if i == old_uid else i

    for r in snap['enrollments']:
        if Training.query.get(r['training_id']):
            db.session.add(_row_from_json(TrainingEnrollment, r, user_id=new_uid))
    for r in snap['innovations']:
        db.session.add(_row_from_json(Innovation, r, user_id=new_uid))
    for r in snap['applications']:
        if Opportunity.query.get(r['opportunity_id']):
            db.session.add(_row_from_json(OpportunityApplication, r, user_id=new_uid))
    for r in snap['notifications']:
        db.session.add(_row_from_json(Notification, r, user_id=new_uid))

    prod_map = {}
    for r in snap['products']:
        p = _row_from_json(Product, r, user_id=new_uid)
        db.session.add(p)
        db.session.flush()
        prod_map[r['id']] = p.id
        for img in r.get('_images', []):
            db.session.add(_row_from_json(ProductImage, img, product_id=p.id))

    for r in snap['reviews']:
        reviewer, target = map_user(r['reviewer_id']), map_user(r['target_user_id'])
        if not (user_exists(reviewer) and user_exists(target)):
            continue
        pid = r['product_id']
        if pid is not None:
            pid = prod_map.get(pid, pid)
            if not Product.query.get(pid):
                continue
        db.session.add(_row_from_json(Review, r, reviewer_id=reviewer, target_user_id=target, product_id=pid))

    for r in snap['messages']:
        rec, snd = map_user(r['recipient_id']), map_user(r['sender_id'])
        if rec is None or not user_exists(rec) or not user_exists(snd):
            continue
        db.session.add(_row_from_json(Message, r, recipient_id=rec, sender_id=snd))

    for r in snap['help_requests']:
        db.session.add(_row_from_json(HelpRequest, r, user_id=new_uid if r.get('user_id') == old_uid else None))

    Event.query.filter(Event.id.in_(snap['event_ids']), Event.created_by_id.is_(None)) \
        .update({'created_by_id': new_uid}, synchronize_session=False)
    GalleryItem.query.filter(GalleryItem.id.in_(snap['gallery_ids']), GalleryItem.created_by_id.is_(None)) \
        .update({'created_by_id': new_uid}, synchronize_session=False)

    tid = item.id
    db.session.delete(item)
    db.session.commit()

    # Put the uploaded files back, then clear the trash copy
    trash_dir = os.path.join(app.config['TRASH_FOLDER'], str(tid))
    for kind, cfg in _TRASH_FILE_FOLDERS.items():
        d = os.path.join(trash_dir, kind)
        if os.path.isdir(d):
            for fn in os.listdir(d):
                shutil.copy2(os.path.join(d, fn), os.path.join(app.config[cfg], fn))
    shutil.rmtree(trash_dir, ignore_errors=True)
    return True, 'Restored.'


def remove_demo_data():
    """Delete the old demo accounts (and everything tied to them) from an existing database.

    Safe to run on every start: it does nothing once the demo users are gone.
    """
    demo_users = User.query.filter(User.email.in_(DEMO_EMAILS)).all()
    if demo_users:
        purge_users([u.id for u in demo_users])
        print(f'🧹 Removed {len(demo_users)} demo user(s) and their data.')
    retire_default_admin()


def ensure_schema_updates():
    """db.create_all() never alters existing tables, so add new columns by hand (SQLite and PostgreSQL)."""
    from sqlalchemy import inspect as sa_inspect, text
    cols = {c['name'] for c in sa_inspect(db.engine).get_columns('user')}
    if 'email_notifications' not in cols:
        with db.engine.begin() as conn:
            conn.execute(text('ALTER TABLE "user" ADD COLUMN email_notifications BOOLEAN DEFAULT TRUE'))


# ==================== INIT ====================

with app.app_context():
    db.create_all()
    ensure_schema_updates()
    seed_data()
    remove_demo_data()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', port=port, debug=debug)
