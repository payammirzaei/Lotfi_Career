"""
Application entry point
"""
import os
from app import create_app
from config import config

# Get environment or default to development
env = os.environ.get('FLASK_ENV', 'development')
app = create_app(config.get(env, config['default']))

if __name__ == '__main__':
    # For development only
    app.run(debug=True, host='0.0.0.0', port=80)

