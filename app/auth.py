"""
Authentication routes
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import User
from sqlalchemy.exc import IntegrityError
import re
from urllib.parse import urlsplit

auth_bp = Blueprint('auth', __name__, url_prefix='/admin')


def validate_email(email):
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def validate_password(password):
    """Validate password (8-128 characters)"""
    return 8 <= len(password) <= 128


def home_for(user):
    """Where a user lands after login"""
    if user.is_admin:
        return url_for('admin.dashboard')
    if user.is_approved:
        return url_for('forms.index')
    return url_for('admin.pending_approval')


def is_safe_redirect(target):
    """Only allow relative, same-site redirect targets (prevents open redirects)"""
    if not target or '\\' in target:
        return False
    parts = urlsplit(target)
    return not parts.scheme and not parts.netloc and target.startswith('/') and not target.startswith('//')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """User registration"""
    if current_user.is_authenticated:
        return redirect(home_for(current_user))
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        # Validation
        errors = []
        
        if not name or len(name) < 3:
            errors.append('Name must be at least 3 characters long.')
        elif len(name) > 80:
            errors.append('Name must be at most 80 characters long.')
        
        if not email:
            errors.append('Email is required.')
        elif len(email) > 120 or not validate_email(email):
            errors.append('Please enter a valid email address.')
        
        if not password:
            errors.append('Password is required.')
        elif not validate_password(password):
            errors.append('Password must be between 8 and 128 characters long.')
        
        if password != confirm_password:
            errors.append('Passwords do not match.')
        
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('auth/register.html', 
                                 name=name, email=email)
        
        # Check if user already exists
        if User.query.filter_by(email=email).first():
            flash('An account with this email already exists.', 'error')
            return render_template('auth/register.html', 
                                 name=name, email=email)
        
        if User.query.filter_by(username=name).first():
            flash('This username is already taken.', 'error')
            return render_template('auth/register.html', 
                                 name=name, email=email)
        
        # Check if this is the first user (no users exist).
        # NOTE: on a fresh deployment, register your admin account immediately.
        is_first_user = User.query.count() == 0
        
        # Create new user
        try:
            user = User(
                username=name, 
                email=email, 
                is_approved=is_first_user,  # Auto-approve first user
                is_admin=is_first_user  # Make first user admin
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            
            if is_first_user:
                flash('Registration successful! You have been automatically approved as the first administrator.', 'success')
                login_user(user, remember=True)
                return redirect(url_for('admin.dashboard'))
            else:
                flash('Registration successful! Your account is pending approval. You will be notified once an administrator approves your account.', 'info')
                return redirect(url_for('admin.pending_approval'))
        except IntegrityError:
            db.session.rollback()
            flash('An error occurred during registration. Please try again.', 'error')
            return render_template('auth/register.html')
        except Exception as e:
            db.session.rollback()
            flash('An unexpected error occurred. Please try again.', 'error')
            return render_template('auth/register.html')
    
    return render_template('auth/register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login"""
    if current_user.is_authenticated:
        return redirect(home_for(current_user))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        if not email or not password:
            flash('Please enter both email and password.', 'error')
            return render_template('auth/login.html', email=email)
        
        user = User.query.filter_by(email=email).first()
        
        if user and len(password) <= 128 and user.check_password(password):
            if not user.is_active:
                flash('Your account is inactive. Please contact support.', 'error')
                return render_template('auth/login.html', email=email)
            
            if not user.is_approved:
                flash('Your account is pending approval. Please wait for an administrator to approve your account.', 'info')
                return redirect(url_for('admin.pending_approval'))
            
            session.clear()  # prevent session fixation
            login_user(user, remember=True)
            next_page = request.args.get('next')
            flash(f'Welcome back, {user.username}!', 'success')
            if is_safe_redirect(next_page):
                return redirect(next_page)
            return redirect(home_for(user))
        else:
            flash('Invalid email or password.', 'error')
            return render_template('auth/login.html', email=email)
    
    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """User logout"""
    # clear first: logout_user() then marks the remember-me cookie for deletion
    session.clear()
    logout_user()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('main.index'))

