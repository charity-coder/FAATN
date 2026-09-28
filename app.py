from flask import Flask, render_template, redirect, url_for, flash, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os
import secrets

try:
    from dotenv import load_dotenv
    load_dotenv()  # loads .env for local DATABASE_URL / SECRET_KEY
except ImportError:
    pass

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'faatn-gate-secret-key-change-in-production-2026')
app.config['TEMPLATES_AUTO_RELOAD'] = True

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

MAX_NEWS_WORDS = 2000

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


def word_count(text):
    if not text:
        return 0
    return len(text.strip().split())

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'


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


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ==================== ROUTES ====================

@app.route('/')
def index():
    return render_template('index.html')


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

        # In production: send email with link. For demo we show the link.
        verify_url = url_for('verify_email', token=token, _external=True)
        flash(f'Registration successful! Please verify your email. (Demo link: {verify_url})', 'success')
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


@app.route('/dashboard/resend-verification', methods=['POST'])
@login_required
def resend_verification():
    if current_user.email_verified:
        flash('Your email is already verified.', 'info')
        return redirect(url_for('profile'))
    token = secrets.token_urlsafe(32)
    current_user.verification_token = token
    db.session.commit()
    verify_url = url_for('verify_email', token=token, _external=True)
    flash(f'Verification link (demo): {verify_url}', 'success')
    return redirect(url_for('profile'))


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            token = secrets.token_urlsafe(32)
            user.reset_token = token
            user.reset_token_expires = datetime.utcnow() + timedelta(hours=2)
            db.session.commit()
            reset_url = url_for('reset_password', token=token, _external=True)
            # Demo: show link (production would email it)
            flash(f'Password reset link (demo): {reset_url}', 'success')
        else:
            # Don't reveal whether email exists
            flash('If that email is registered, a reset link has been generated.', 'info')
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
            db.session.commit()
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


@app.route('/member/<int:user_id>')
def public_profile(user_id):
    """Public SEO profile — FAATN is master DB; Maps is integration only."""
    user = User.query.get_or_404(user_id)
    if user.role == 'admin':
        flash('Profile not available.', 'info')
        return redirect(url_for('gate'))
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
    """Inbox: conversations list (peer + system)."""
    # Incoming
    incoming = Message.query.filter_by(recipient_id=current_user.id).order_by(Message.created_at.desc()).all()
    # Outgoing peer messages
    outgoing = Message.query.filter_by(sender_id=current_user.id).order_by(Message.created_at.desc()).all()

    # Build unique conversation partners
    partners = {}
    for m in incoming:
        key = m.sender_id if m.sender_id else f'system-{m.id}'
        if key not in partners:
            partners[key] = {
                'user': m.sender if m.sender_id else None,
                'name': m.sender_name or 'System',
                'last_msg': m,
                'unread': 0,
                'is_system': m.sender_id is None
            }
        if not m.is_read:
            partners[key]['unread'] += 1
        if m.created_at > partners[key]['last_msg'].created_at:
            partners[key]['last_msg'] = m

    for m in outgoing:
        key = m.recipient_id
        if key not in partners:
            recipient = User.query.get(m.recipient_id)
            partners[key] = {
                'user': recipient,
                'name': recipient.full_name if recipient else 'Unknown',
                'last_msg': m,
                'unread': 0,
                'is_system': False
            }
        if m.created_at > partners[key]['last_msg'].created_at:
            partners[key]['last_msg'] = m

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
            msg = Message(
                recipient_id=other.id,
                sender_id=current_user.id,
                sender_name=current_user.full_name,
                subject=f'Chat with {current_user.full_name}',
                body=body or ('[Image]' if image_filename else ''),
                image_filename=image_filename
            )
            db.session.add(msg)
            preview = body[:120] if body else 'Sent an image'
            notif = Notification(
                user_id=other.id,
                title=f'New message from {current_user.full_name}',
                message=preview + ('…' if body and len(body) > 120 else ''),
                type='info'
            )
            db.session.add(notif)
            db.session.commit()
            flash('Message sent.', 'success')
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
    users = User.query.order_by(User.created_at.desc()).limit(30).all()
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
    return render_template(
        'dashboard_admin.html',
        users=users,
        total_users=total_users,
        total_opps=total_opps,
        total_innov=total_innov,
        db_metrics=db_metrics,
        listing_categories=LISTING_CATEGORIES,
        stats=stats,
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

@app.route('/dashboard/admin/db-metrics')
@admin_required
def admin_db_metrics():
    """JSON endpoint for connection pool monitoring (admin only)."""
    if not is_admin(current_user):
        return jsonify({'error': 'Access denied'}), 403
    return jsonify(get_connection_metrics())


# ==================== SEED DATA ====================

def seed_data():
    if User.query.filter_by(email='admin@faatn.ng').first():
        return

    # Admin
    admin = User(
        email='admin@faatn.ng',
        full_name='FAATN Administrator',
        role='admin',
        location_state='FCT',
        occupation='System Admin',
        verified=True,
        email_verified=True,
        listing_category='verified',
    )
    admin.set_password('Admin@FAATN2026')
    db.session.add(admin)

    # Demo Artisan
    artisan = User(
        email='artisan@demo.ng',
        full_name='Chinedu Okoro',
        phone='+234 803 123 4567',
        role='artisan',
        location_state='Anambra',
        location_lga='Awka South',
        location_community='Amawbia',
        occupation='Carpentry',
        specialty='Furniture Making & Woodwork',
        skills='Carpentry, Joinery, Finishing, Design, Measurement',
        experience_years=8,
        portfolio='Built over 200 custom furniture pieces. Specialist in modern Nigerian-style living room sets.',
        needs='Advanced CNC training, Market access for export quality products',
        verified=True,
        email_verified=True,
        listing_category='verified',
    )
    artisan.set_password('Artisan@123')
    db.session.add(artisan)

    # Demo Technician
    tech = User(
        email='tech@demo.ng',
        full_name='Amina Yusuf',
        phone='+234 802 987 6543',
        role='technician',
        location_state='Kano',
        location_lga='Nassarawa',
        location_community='Bompai',
        occupation='Electrical Technician',
        specialty='Solar Installation & Maintenance',
        skills='Solar PV, Inverters, Wiring, Troubleshooting, Battery Systems',
        experience_years=5,
        portfolio='Installed 45+ residential solar systems across Kano.',
        needs='Certification in advanced hybrid systems',
        verified=True,
        email_verified=True,
        listing_category='verified',
    )
    tech.set_password('Tech@123')
    db.session.add(tech)

    # Demo Engineer / Technical Professional
    engineer = User(
        email='engineer@demo.ng',
        full_name='Engr. Tunde Adebayo',
        phone='+234 805 111 2233',
        role='engineer',
        location_state='Lagos',
        location_lga='Ikeja',
        location_community='Alausa',
        occupation='Mechanical Engineer',
        specialty='Industrial Equipment & Fabrication Support',
        skills='CAD, Fabrication Design, Quality Control, Technical Mentoring, NSE Standards',
        experience_years=12,
        portfolio='Supports artisans with design drawings, load calculations and workshop process improvement across SW Nigeria.',
        needs='Link with skilled welders and CNC operators for pilot projects',
        verified=True,
        email_verified=True,
        listing_category='verified',
    )
    engineer.set_password('Engineer@123')
    db.session.add(engineer)

    db.session.commit()

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

    # Sample system messages for artisan
    msg1 = Message(recipient_id=artisan.id, sender_id=None, sender_name='FAATN Matching Engine', subject='New Opportunity Match', body='A furniture contract in Enugu matches your skills profile (95% match). Apply now from your Opportunities page.')
    msg2 = Message(recipient_id=artisan.id, sender_id=None, sender_name='Training Coordinator', subject='CNC Training Starting Soon', body='The Advanced Woodworking & CNC course begins in two weeks. Confirm your attendance.')
    db.session.add_all([msg1, msg2])

    # Peer-to-peer sample chat: technician asks artisan for woodworking help
    peer1 = Message(
        recipient_id=artisan.id,
        sender_id=tech.id,
        sender_name=tech.full_name,
        subject='Need woodworking advice',
        body='Hello Chinedu, I am installing a solar system for a client who also needs custom mounting frames. Can you advise on durable local hardwood that works outdoors?'
    )
    peer2 = Message(
        recipient_id=tech.id,
        sender_id=artisan.id,
        sender_name=artisan.full_name,
        subject='Re: Need woodworking advice',
        body='Hi Amina, yes — Iroko or Mahogany treated with weather-resistant varnish works well for outdoor frames. I can supply cut pieces if needed. Let’s discuss sizes.'
    )
    db.session.add_all([peer1, peer2])

    n1 = Notification(user_id=artisan.id, title='Profile Verification Complete', message='Your artisan profile has been verified. You now have full access to matching and opportunities.', type='success')
    n2 = Notification(user_id=artisan.id, title='New Grant Opportunity', message='Artisan Innovation Grant 2026 is now open. Submit your ideas via the Innovation module.', type='opportunity')
    n3 = Notification(user_id=artisan.id, title='New message from Amina Yusuf', message='Hello Chinedu, I am installing a solar system for a client who also needs custom mounting frames…', type='info')
    db.session.add_all([n1, n2, n3])

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


# ==================== INIT ====================

with app.app_context():
    db.create_all()
    seed_data()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', port=port, debug=debug)
