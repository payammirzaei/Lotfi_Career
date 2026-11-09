"""
Configuration management for Flask app.

Production uses PostgreSQL (DATABASE_URL) and a persistent volume for uploads
(UPLOAD_PATH). Nothing silently falls back to ephemeral storage such as /tmp.
"""
import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _database_url(default=None):
    """Read DATABASE_URL and normalise it for SQLAlchemy 2 + psycopg 3.

    Hosts hand out postgres:// or postgresql:// URLs; both are pinned to the
    psycopg (v3) driver that requirements.txt installs.
    """
    url = os.environ.get('DATABASE_URL') or default
    if url:
        for prefix in ('postgres://', 'postgresql://'):
            if url.startswith(prefix):
                url = 'postgresql+psycopg://' + url[len(prefix):]
                break
    return url


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


class Config:
    """Base configuration"""
    SECRET_KEY = os.environ.get('SECRET_KEY')
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        # Drop dead connections (DB restarts, idle timeouts on managed Postgres)
        'pool_pre_ping': True,
        'pool_recycle': 280,
    }

    # Multi-application support: each app sharing one PostgreSQL database gets
    # its own schema (namespace) so table names never collide. Empty = "public".
    DB_SCHEMA = os.environ.get('DB_SCHEMA', '').strip()

    # Run Alembic migrations automatically on startup
    AUTO_MIGRATE = _env_bool('AUTO_MIGRATE', True)

    # CSRF (Flask-WTF)
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None  # token valid for the session lifetime

    # Session / cookie hardening
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_DURATION = timedelta(days=14)

    # Number of reverse proxies in front of the app (for correct client IP / https detection)
    PROXY_FIX_COUNT = int(os.environ.get('PROXY_FIX_COUNT', '1'))
    # Header the hosting platform sets to the real visitor IP (e.g. X-Real-IP). Empty = remote_addr.
    CLIENT_IP_HEADER = os.environ.get('CLIENT_IP_HEADER', '').strip()
    LOG_PROXY_HEADERS = _env_bool('LOG_PROXY_HEADERS', False)

    # Rate limiting (per worker process unless RATELIMIT_STORAGE_URI points at Redis)
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')
    RATELIMIT_HEADERS_ENABLED = True

    # Pagination
    POSTS_PER_PAGE = 10

    # File upload settings
    UPLOAD_FOLDER = os.environ.get('UPLOAD_PATH') or os.path.join(BASE_DIR, 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max request size
    ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'xls', 'xlsx', 'zip'}

    # Logging
    LOG_TO_STDOUT = os.environ.get('LOG_TO_STDOUT')


class DevelopmentConfig(Config):
    """Development configuration (local machine)"""
    DEBUG = True
    TESTING = False
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-only-insecure-key'
    # Local Postgres is preferred; SQLite is only a convenience fallback for dev.
    SQLALCHEMY_DATABASE_URI = _database_url(
        'sqlite:///' + os.path.join(BASE_DIR, 'app', 'db', 'app.db'))
    UPLOAD_FOLDER = os.environ.get('UPLOAD_PATH') or os.path.join(BASE_DIR, 'app', 'uploads')


class ProductionConfig(Config):
    """Production configuration: PostgreSQL + persistent upload volume"""
    DEBUG = False
    TESTING = False

    SESSION_COOKIE_SECURE = _env_bool('SESSION_COOKIE_SECURE', True)
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    PREFERRED_URL_SCHEME = 'https'

    # Persistent volume. Liara mounts the "uploads" disk at /usr/src/app/uploads;
    # docker-compose mounts the "uploads" volume at the same path.
    UPLOAD_FOLDER = os.environ.get('UPLOAD_PATH') or '/usr/src/app/uploads'

    @staticmethod
    def validate(app):
        """Fail fast instead of running with insecure/ephemeral settings."""
        if not app.config.get('SECRET_KEY'):
            raise RuntimeError('SECRET_KEY environment variable must be set in production.')
        uri = app.config.get('SQLALCHEMY_DATABASE_URI') or ''
        if not uri.startswith('postgresql'):
            raise RuntimeError(
                'DATABASE_URL must point to a PostgreSQL database in production '
                '(e.g. postgresql://user:pass@host:5432/dbname).')


class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    SECRET_KEY = 'testing'
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    SQLALCHEMY_DATABASE_URI = _database_url('sqlite:///:memory:')
    SQLALCHEMY_ENGINE_OPTIONS = {}


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
