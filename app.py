from flask import Flask, render_template, redirect, url_for, flash, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os
import secrets

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'faatn-gate-secret-key-change-in-production-2026')

# Database: use Render PostgreSQL if available, otherwise local SQLite
database_url = os.environ.get('DATABASE_URL')
if database_url:
    # Fix for Render (postgres:// → postgresql://)
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # Local development
    os.makedirs(app.instance_path, exist_ok=True)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'faatn_gate.db')

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads', 'avatars')
app.config['CHAT_UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads', 'chat')
app.config['BG_UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'images', 'backgrounds')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB max
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['CHAT_UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['BG_UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
    verified = db.Column(db.Boolean, default=False)  # admin/platform verification
    email_verified = db.Column(db.Boolean, default=False)
    verification_token = db.Column(db.String(64), nullable=True)
    reset_token = db.Column(db.String(64), nullable=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)
    profile_pic = db.Column(db.String(200), nullable=True)  # filename in uploads/avatars
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

    return render_template('register.html')


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
    # Role-based dashboard — artisans, technicians, engineers share member portal
    if current_user.role in ['artisan', 'technician', 'engineer']:
        return redirect(url_for('artisan_dashboard'))
    elif current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    else:
        return redirect(url_for('artisan_dashboard'))  # fallback


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


@app.route('/dashboard/directory')
@login_required
def directory():
    """Browse artisans and technicians to connect and chat for assistance."""
    q = request.args.get('q', '').strip()
    role_filter = request.args.get('role', '')
    state_filter = request.args.get('state', '')

    query = User.query.filter(User.id != current_user.id, User.role.in_(['artisan', 'technician', 'engineer']))
    if q:
        like = f'%{q}%'
        query = query.filter(
            db.or_(
                User.full_name.ilike(like),
                User.occupation.ilike(like),
                User.specialty.ilike(like),
                User.skills.ilike(like),
                User.location_state.ilike(like),
                User.location_lga.ilike(like)
            )
        )
    if role_filter:
        query = query.filter(User.role == role_filter)
    if state_filter:
        query = query.filter(User.location_state.ilike(f'%{state_filter}%'))

    members = query.order_by(User.full_name).limit(50).all()
    return render_template('directory.html', members=members, q=q, role_filter=role_filter, state_filter=state_filter)


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
@app.route('/dashboard/admin')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    users = User.query.order_by(User.created_at.desc()).limit(20).all()
    total_users = User.query.count()
    total_opps = Opportunity.query.count()
    total_innov = Innovation.query.count()
    return render_template('dashboard_admin.html', users=users, total_users=total_users, total_opps=total_opps, total_innov=total_innov)


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
        email_verified=True
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
        email_verified=True
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
        email_verified=True
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
        email_verified=True
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

    db.session.commit()
    print('✅ Database seeded successfully!')


# ==================== INIT ====================

with app.app_context():
    db.create_all()
    seed_data()


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
