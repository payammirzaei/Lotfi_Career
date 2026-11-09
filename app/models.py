"""
Database models
"""
from datetime import datetime
from flask_login import UserMixin
from app import db
from werkzeug.security import generate_password_hash, check_password_hash


class User(UserMixin, db.Model):
    """User model"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)
    is_approved = db.Column(db.Boolean, default=False)  # Admin must approve new users
    
    # Relationships
    forms = db.relationship('Form', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    
    def set_password(self, password):
        """Hash and set password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check password against hash"""
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.username}>'


class Form(db.Model):
    """Form model - stores form definitions"""
    __tablename__ = 'forms'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    form_template = db.Column(db.Text, nullable=False)  # WPCF7-like template
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    submissions = db.relationship('FormSubmission', backref='form', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Form {self.title}>'


class FormSubmission(db.Model):
    """Form submission model - stores form submissions"""
    __tablename__ = 'form_submissions'
    
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('forms.id'), nullable=False, index=True)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    
    # Relationships
    fields = db.relationship('FormSubmissionField', backref='submission', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<FormSubmission {self.id}>'


class FormSubmissionField(db.Model):
    """Form submission field model - stores individual field values"""
    __tablename__ = 'form_submission_fields'
    
    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('form_submissions.id'), nullable=False, index=True)
    field_name = db.Column(db.String(100), nullable=False, index=True)
    field_value = db.Column(db.Text)
    file_path = db.Column(db.String(500))  # For file uploads
    file_name = db.Column(db.String(255))  # Original filename
    
    def __repr__(self):
        return f'<FormSubmissionField {self.field_name}>'

