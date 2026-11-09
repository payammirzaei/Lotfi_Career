"""
Flask application factory
"""
import logging
import os
import re
import zlib
from datetime import datetime

from flask import Flask
from flask_limiter import Limiter
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()


def client_ip():
    """Real visitor IP.

    Behind a platform proxy (Railway, Liara, Cloudflare...) remote_addr can be
    the proxy's own address, which changes between requests and is shared by
    all visitors. Set CLIENT_IP_HEADER to the header the platform overwrites
    with the client address (e.g. X-Real-IP on Railway).
    """
    from flask import current_app, request
    header = current_app.config.get('CLIENT_IP_HEADER')
    if header:
        value = (request.headers.get(header) or '').split(',')[0].strip()
        if value:
            return value[:45]
    return (request.remote_addr or '')[:45]


limiter = Limiter(key_func=client_ip)
login_manager = LoginManager()
login_manager.login_view = 'admin.login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'
# 'basic' (Flask-Login default): 'strong' logged users out whenever the proxy
# address in front of the app changed, e.g. mid-way through filling in a form.
login_manager.session_protection = 'basic'

MIGRATIONS_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'migrations')
_MIGRATION_LOCK_ID = 74210931  # arbitrary constant for pg_advisory_lock
_SCHEMA_RE = re.compile(r'^[a-z_][a-z0-9_]{0,62}$')

log = logging.getLogger(__name__)


@login_manager.user_loader
def load_user(user_id):
    """Load user by ID for Flask-Login"""
    from app.models import User
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


def _init_database(app):
    """Bring the schema up to date with Alembic.

    On PostgreSQL an advisory lock makes sure only one gunicorn worker runs
    migrations at a time. Databases created earlier by db.create_all() (no
    alembic_version table) are stamped instead of re-created.
    """
    from flask_migrate import stamp, upgrade
    from sqlalchemy import inspect, text

    schema = app.config.get('DB_SCHEMA') or ''
    lock_id = _MIGRATION_LOCK_ID ^ zlib.crc32(schema.encode())  # per-app lock

    with app.app_context():
        engine = db.engine
        is_pg = engine.dialect.name == 'postgresql'
        with engine.connect() as conn:
            if is_pg:
                conn.execute(text('SELECT pg_advisory_lock(:id)'), {'id': lock_id})
                if schema:
                    conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
                conn.commit()
            try:
                insp = inspect(conn)
                if insp.has_table('users') and not insp.has_table('alembic_version'):
                    stamp(directory=MIGRATIONS_DIR)
                else:
                    upgrade(directory=MIGRATIONS_DIR)
            finally:
                if is_pg:
                    conn.execute(text('SELECT pg_advisory_unlock(:id)'), {'id': lock_id})
                    conn.commit()


def create_app(config_class=Config):
    """Application factory pattern"""
    static_folder = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'static')
    app = Flask(__name__, static_folder=static_folder)
    app.config.from_object(config_class)

    validate = getattr(config_class, 'validate', None)
    if callable(validate):
        validate(app)
    if not app.config.get('SECRET_KEY'):
        raise RuntimeError('SECRET_KEY must be set.')
    if not app.config.get('SQLALCHEMY_DATABASE_URI'):
        raise RuntimeError('DATABASE_URL must be set.')

    # Per-application PostgreSQL schema (lets several apps share one database)
    schema = app.config.get('DB_SCHEMA') or ''
    if schema:
        if not _SCHEMA_RE.match(schema):
            raise RuntimeError('DB_SCHEMA must match [a-z_][a-z0-9_]{0,62}.')
        if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgresql'):
            opts = dict(app.config.get('SQLALCHEMY_ENGINE_OPTIONS') or {})
            connect_args = dict(opts.get('connect_args') or {})
            connect_args['options'] = f'-csearch_path={schema}'
            opts['connect_args'] = connect_args
            app.config['SQLALCHEMY_ENGINE_OPTIONS'] = opts

    # Trust X-Forwarded-* from the platform's reverse proxy (correct client IP + https)
    if app.config.get('PROXY_FIX_COUNT'):
        n = app.config['PROXY_FIX_COUNT']
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n, x_host=n)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db, directory=MIGRATIONS_DIR)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)

    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        from app.models import SUBMISSION_STATUSES, EMPLOYMENT_TYPES, FormSubmission
        nav_new_count = 0
        try:
            if current_user.is_authenticated and current_user.is_admin:
                nav_new_count = FormSubmission.query.filter_by(status='new').count()
        except Exception:  # never break page rendering (e.g. on error pages)
            db.session.rollback()
        return {'current_year': datetime.now().year,
                'SUBMISSION_STATUSES': SUBMISSION_STATUSES,
                'EMPLOYMENT_TYPES': EMPLOYMENT_TYPES,
                'nav_new_count': nav_new_count}

    @app.template_filter('nl2br')
    def nl2br_filter(value):
        """Escape the value, then convert newlines to <br> tags"""
        from markupsafe import Markup, escape
        if not value:
            return value
        return Markup('<br>').join(escape(value).split('\n'))

    @app.template_filter('from_json')
    def from_json_filter(value):
        """Parse JSON string to Python object"""
        import json
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value

    if app.config.get('LOG_PROXY_HEADERS'):
        @app.before_request
        def _log_proxy_headers():
            from flask import request
            app.logger.warning('proxy headers: remote_addr=%s XFF=%r X-Real-IP=%r CF=%r Host=%r XFH=%r',
                               request.remote_addr, request.headers.get('X-Forwarded-For'),
                               request.headers.get('X-Real-IP'), request.headers.get('CF-Connecting-IP'),
                               request.headers.get('Host'), request.headers.get('X-Forwarded-Host'))

    @app.after_request
    def set_security_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        if app.config.get('SESSION_COOKIE_SECURE'):
            response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000')
        return response

    # Upload folder must live on a persistent volume in production
    upload_folder = app.config.get('UPLOAD_FOLDER')
    try:
        os.makedirs(upload_folder, exist_ok=True)
    except OSError as exc:
        log.error('Upload folder %s is not writable: %s', upload_folder, exc)
    if not app.debug and not app.testing and not os.path.ismount(upload_folder):
        log.warning('UPLOAD_FOLDER %s is not a mount point - uploaded files will be lost '
                    'on redeploy unless a persistent disk/volume is mounted there.', upload_folder)

    # SQLite (dev only): make sure the directory exists
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    if db_uri.startswith('sqlite:///') and db_uri != 'sqlite:///:memory:':
        os.makedirs(os.path.dirname(db_uri[len('sqlite:///'):]) or '.', exist_ok=True)

    # Register blueprints
    from app.routes import main_bp
    from app.form_routes import form_bp, uploaded_file
    from app.admin import admin_bp
    from app import dashboard as _dashboard  # noqa: F401  (registers dashboard/ads/applications routes)
    from app.auth import login, register, logout

    admin_bp.add_url_rule('/login', 'login',
                          limiter.limit('10 per minute; 50 per hour', methods=['POST'])(login),
                          methods=['GET', 'POST'])
    admin_bp.add_url_rule('/register', 'register',
                          limiter.limit('5 per hour', methods=['POST'])(register),
                          methods=['GET', 'POST'])
    admin_bp.add_url_rule('/logout', 'logout', logout, methods=['GET', 'POST'])

    app.register_blueprint(main_bp)
    app.register_blueprint(form_bp)
    app.register_blueprint(admin_bp)

    # Uploads are served at root level (not under /forms prefix)
    app.add_url_rule('/uploads/<path:filename>', 'uploaded_file', uploaded_file, methods=['GET'])

    from app.errors import register_error_handlers
    register_error_handlers(app)

    if app.config.get('AUTO_MIGRATE'):
        _init_database(app)

    return app
