"""
Public pages
"""
from datetime import date

from flask import Blueprint, render_template
from sqlalchemy import or_

from app.models import Form

main_bp = Blueprint('main', __name__)


def open_positions():
    """Ads that are published and not past their closing date, newest first"""
    return (Form.query
            .filter(Form.is_active.is_(True),
                    or_(Form.closes_at.is_(None), Form.closes_at >= date.today()))
            .order_by(Form.created_at.desc()).all())


@main_bp.route('/')
def index():
    """Home page with the list of open positions"""
    return render_template('index.html', jobs=open_positions())


@main_bp.route('/about')
def about():
    """About page"""
    return render_template('about.html')
