"""
WSGI entry point for production deployment
"""
import os
from app import create_app
from config import config

# Get environment or default to production
env = os.environ.get('FLASK_ENV', 'production')
app = create_app(config.get(env, config['default']))

if __name__ == '__main__':
    app.run()







