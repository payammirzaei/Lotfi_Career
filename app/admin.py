"""
Admin routes and user management
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, current_app
from flask_login import login_required, current_user
from app import db
from app.models import User, Form
from functools import wraps
import os
import re
import shutil
import sqlite3
import zipfile
import tempfile
from datetime import datetime
from werkzeug.utils import secure_filename
from io import BytesIO

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(f):
    """Decorator to require admin access"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('admin.login'))
        if not current_user.is_admin:
            flash('You do not have permission to access this page.', 'error')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function


def approved_required(f):
    """Decorator to require approved user"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('admin.login'))
        if not current_user.is_approved:
            flash('Your account is pending approval. Please wait for an administrator to approve your account.', 'info')
            return redirect(url_for('admin.pending_approval'))
        return f(*args, **kwargs)
    return decorated_function


@admin_bp.route('/pending')
@login_required
def pending_approval():
    """Show pending approval message"""
    if current_user.is_approved:
        return redirect(url_for('main.index'))
    return render_template('admin/pending.html')


@admin_bp.route('/users')
@login_required
@admin_required
def users():
    """List all users"""
    users_list = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users_list)


@admin_bp.route('/users/<int:user_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_user(user_id):
    """Approve a user"""
    user = User.query.get_or_404(user_id)
    user.is_approved = True
    try:
        db.session.commit()
        flash(f'User {user.username} has been approved.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('An error occurred while approving the user.', 'error')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/reject', methods=['POST'])
@login_required
@admin_required
def reject_user(user_id):
    """Reject/delete a user"""
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot reject your own account.', 'error')
        return redirect(url_for('admin.users'))
    try:
        db.session.delete(user)
        db.session.commit()
        flash(f'User {user.username} has been rejected and removed.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('An error occurred while rejecting the user.', 'error')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/toggle-admin', methods=['POST'])
@login_required
@admin_required
def toggle_admin(user_id):
    """Toggle admin status"""
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot change your own admin status.', 'error')
        return redirect(url_for('admin.users'))
    user.is_admin = not user.is_admin
    try:
        db.session.commit()
        status = 'granted admin access' if user.is_admin else 'removed admin access'
        flash(f'User {user.username} has been {status}.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('An error occurred while updating admin status.', 'error')
    return redirect(url_for('admin.users'))


@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    """Admin dashboard"""
    total_users = User.query.count()
    pending_users = User.query.filter_by(is_approved=False).count()
    total_forms = Form.query.count()
    active_forms = Form.query.filter_by(is_active=True).count()
    
    stats = {
        'total_users': total_users,
        'pending_users': pending_users,
        'total_forms': total_forms,
        'active_forms': active_forms
    }
    
    return render_template('admin/dashboard.html', stats=stats)


@admin_bp.route('/database')
@login_required
@admin_required
def database_management():
    """Database backup/restore management page"""
    # Get database file info
    db_uri = current_app.config['SQLALCHEMY_DATABASE_URI']
    db_info = {}
    
    if db_uri.startswith('sqlite:///'):
        db_path = db_uri.replace('sqlite:///', '')
        if os.path.exists(db_path):
            db_info['exists'] = True
            db_info['size'] = os.path.getsize(db_path)
            db_info['modified'] = datetime.fromtimestamp(os.path.getmtime(db_path))
            db_info['path'] = db_path
        else:
            db_info['exists'] = False
            db_info['path'] = db_path
    else:
        db_info['type'] = 'non-sqlite'
        db_info['uri'] = db.engine.dialect.name  # never expose host/credentials
    
    return render_template('admin/database.html', db_info=db_info)


@admin_bp.route('/database/download')
@login_required
@admin_required
def download_database():
    """Download database backup"""
    db_uri = current_app.config['SQLALCHEMY_DATABASE_URI']
    
    if not db_uri.startswith('sqlite:///'):
        flash('Database download is only available for SQLite databases.', 'error')
        return redirect(url_for('admin.database_management'))
    
    db_path = db_uri.replace('sqlite:///', '')
    
    if not os.path.exists(db_path):
        flash('Database file not found.', 'error')
        return redirect(url_for('admin.database_management'))
    
    # Generate filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'app_backup_{timestamp}.db'
    
    try:
        return send_file(
            db_path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/x-sqlite3'
        )
    except Exception:
        current_app.logger.exception('Error downloading database')
        flash('Error downloading database.', 'error')
        return redirect(url_for('admin.database_management'))


def validate_sqlite_database(file_path):
    """Validate that the uploaded file is a valid SQLite database"""
    try:
        # Try to open the database
        conn = sqlite3.connect(file_path)
        cursor = conn.cursor()
        
        # Check if it's a valid SQLite database
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        
        # Check for required tables (at least users table should exist)
        table_names = [table[0] for table in tables]
        
        # Verify database structure by trying to query users table
        if 'users' in table_names:
            cursor.execute("SELECT COUNT(*) FROM users LIMIT 1")
            cursor.fetchone()
        elif 'user' in table_names:  # Fallback for old table name
            cursor.execute("SELECT COUNT(*) FROM user LIMIT 1")
            cursor.fetchone()
        else:
            return False, "Required 'users' table not found in database"
        
        conn.close()
        return True, "Database is valid"
    except sqlite3.Error as e:
        return False, f"Invalid SQLite database: {str(e)}"
    except Exception as e:
        return False, f"Error validating database: {str(e)}"


@admin_bp.route('/database/upload', methods=['POST'])
@login_required
@admin_required
def upload_database():
    """Upload and restore database backup"""
    db_uri = current_app.config['SQLALCHEMY_DATABASE_URI']
    
    if not db_uri.startswith('sqlite:///'):
        flash('Database upload is only available for SQLite databases.', 'error')
        return redirect(url_for('admin.database_management'))
    
    db_path = db_uri.replace('sqlite:///', '')
    db_dir = os.path.dirname(db_path)
    
    if 'database' not in request.files:
        flash('No file provided.', 'error')
        return redirect(url_for('admin.database_management'))
    
    file = request.files['database']
    
    if file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('admin.database_management'))
    
    # Check file extension
    if not file.filename.lower().endswith('.db'):
        flash('Invalid file type. Please upload a .db file.', 'error')
        return redirect(url_for('admin.database_management'))
    
    try:
        # Save uploaded file to temporary location
        temp_path = os.path.join(db_dir, 'temp_upload.db')
        file.save(temp_path)
        
        # Validate the database
        is_valid, message = validate_sqlite_database(temp_path)
        if not is_valid:
            os.remove(temp_path)
            flash(f'Invalid database file: {message}', 'error')
            return redirect(url_for('admin.database_management'))
        
        # Create backup of current database if it exists
        if os.path.exists(db_path):
            backup_path = os.path.join(db_dir, f'app_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db')
            shutil.copy2(db_path, backup_path)
        
        # Close all database connections
        db.session.close()
        
        # Replace current database with uploaded one
        if os.path.exists(db_path):
            os.remove(db_path)
        shutil.move(temp_path, db_path)
        
        # Verify the database by checking user count
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            # Try users table first, fallback to user
            try:
                cursor.execute("SELECT COUNT(*) FROM users")
                user_count = cursor.fetchone()[0]
            except sqlite3.OperationalError:
                cursor.execute("SELECT COUNT(*) FROM user")
                user_count = cursor.fetchone()[0]
            conn.close()
            flash(f'Database restored successfully! Found {user_count} user(s) in the database.', 'success')
        except Exception as e:
            flash(f'Database restored but verification had issues: {str(e)}. Please verify manually.', 'warning')
        
        flash('Database has been successfully restored. You may need to refresh the page or restart the application for changes to take full effect.', 'info')
        return redirect(url_for('admin.database_management'))
        
    except Exception as e:
        # Clean up temp file if it exists
        temp_path = os.path.join(db_dir, 'temp_upload.db')
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        flash(f'Error uploading database: {str(e)}', 'error')
        return redirect(url_for('admin.database_management'))


BACKUP_DIR_NAME = '.backups'
_UPLOAD_MEMBER_RE = re.compile(r'^\d+/[^/\\]+$')


def _iter_upload_files(upload_folder):
    """Yield (abs_path, relative_path) for uploaded files, skipping internal backups."""
    for item in os.listdir(upload_folder):
        item_path = os.path.join(upload_folder, item)
        if item == BACKUP_DIR_NAME or not os.path.isdir(item_path):
            continue
        for name in os.listdir(item_path):
            file_path = os.path.join(item_path, name)
            if os.path.isfile(file_path):
                yield file_path, f'{item}/{name}'


@admin_bp.route('/files')
@login_required
@admin_required
def files_management():
    """Files backup/restore management page"""
    upload_folder = current_app.config.get('UPLOAD_FOLDER')
    files_info = {}

    if upload_folder and os.path.exists(upload_folder):
        files_info['exists'] = True
        files_info['path'] = upload_folder
        try:
            total_files = 0
            total_size = 0
            dirs = set()
            for file_path, rel in _iter_upload_files(upload_folder):
                total_files += 1
                total_size += os.path.getsize(file_path)
                dirs.add(rel.split('/', 1)[0])
            files_info['total_files'] = total_files
            files_info['total_size'] = total_size
            files_info['form_directories'] = len(dirs)
        except OSError:
            current_app.logger.exception('Error reading upload folder')
            files_info['error'] = 'Could not read the upload folder.'
    else:
        files_info['exists'] = False
        files_info['path'] = upload_folder if upload_folder else 'Not configured'

    return render_template('admin/files.html', files_info=files_info)


@admin_bp.route('/files/download')
@login_required
@admin_required
def download_files():
    """Download all uploaded files as ZIP"""
    upload_folder = current_app.config.get('UPLOAD_FOLDER')

    if not upload_folder or not os.path.exists(upload_folder):
        flash('Upload folder not found.', 'error')
        return redirect(url_for('admin.files_management'))

    try:
        # Spool to disk above 32MB instead of holding everything in memory
        temp_zip = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
        with zipfile.ZipFile(temp_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_path, rel in _iter_upload_files(upload_folder):
                zipf.write(file_path, rel)
        temp_zip.seek(0)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return send_file(
            temp_zip,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f'uploads_backup_{timestamp}.zip'
        )
    except Exception:
        current_app.logger.exception('Error creating files backup')
        flash('Error creating files backup.', 'error')
        return redirect(url_for('admin.files_management'))


@admin_bp.route('/files/upload', methods=['POST'])
@login_required
@admin_required
def upload_files():
    """Upload and restore files backup (ZIP file)"""
    upload_folder = current_app.config.get('UPLOAD_FOLDER')

    if not upload_folder:
        flash('Upload folder is not configured.', 'error')
        return redirect(url_for('admin.files_management'))

    file = request.files.get('files')
    if not file or file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('admin.files_management'))

    if not file.filename.lower().endswith('.zip'):
        flash('Invalid file type. Please upload a .zip file.', 'error')
        return redirect(url_for('admin.files_management'))

    temp_dir = tempfile.mkdtemp()
    try:
        temp_zip_path = os.path.join(temp_dir, 'uploads_backup.zip')
        file.save(temp_zip_path)

        # Validate: only "<form_id>/<filename>" entries, no traversal, bounded size
        max_total = 2 * 1024 * 1024 * 1024  # 2GB uncompressed (zip-bomb guard)
        try:
            with zipfile.ZipFile(temp_zip_path, 'r') as zipf:
                members = [m for m in zipf.infolist() if not m.is_dir()]
                bad = [m.filename for m in members if not _UPLOAD_MEMBER_RE.match(m.filename)]
                if bad:
                    raise zipfile.BadZipFile(f'unexpected entry "{bad[0][:80]}"')
                if sum(m.file_size for m in members) > max_total:
                    raise zipfile.BadZipFile('archive is too large when extracted')
                if zipf.testzip():
                    raise zipfile.BadZipFile('archive is corrupted')
        except zipfile.BadZipFile as e:
            flash(f'Invalid ZIP file: {e}', 'error')
            return redirect(url_for('admin.files_management'))

        os.makedirs(upload_folder, exist_ok=True)

        # Back up current files inside the volume (so the backup is persistent too)
        backup_dir = os.path.join(upload_folder, BACKUP_DIR_NAME)
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, f'before_restore_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip')
        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as bz:
            for file_path, rel in _iter_upload_files(upload_folder):
                bz.write(file_path, rel)

        # Clear current contents (not the folder itself: it may be a mount point)
        for item in os.listdir(upload_folder):
            if item == BACKUP_DIR_NAME:
                continue
            item_path = os.path.join(upload_folder, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)

        with zipfile.ZipFile(temp_zip_path, 'r') as zipf:
            members = [m for m in zipf.infolist() if not m.is_dir()]
            zipf.extractall(upload_folder, members=members)
            restored_files = len(members)

        flash(f'Files restored successfully! {restored_files} file(s) extracted. '
              f'Previous files were saved to {BACKUP_DIR_NAME}/{os.path.basename(backup_path)}.', 'success')
        return redirect(url_for('admin.files_management'))

    except Exception:
        current_app.logger.exception('Error restoring files')
        flash('Error restoring files. Check the server logs for details.', 'error')
        return redirect(url_for('admin.files_management'))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@admin_bp.route('/sms', methods=['GET', 'POST'])
@login_required
@admin_required
def sms():
    """Admin-only SMS sending page"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        from_number = request.form.get('from_number', '').strip()
        to_numbers_text = request.form.get('to_numbers', '').strip()
        text = request.form.get('text', '').strip()
        is_flash = request.form.get('is_flash') == 'on'
        
        # Validate required fields
        if not all([username, password, from_number, to_numbers_text, text]):
            flash('Please fill in all required fields.', 'error')
            return render_template('admin/sms.html')
        
        # Parse TO numbers (split by newline or comma)
        to_numbers = []
        for line in to_numbers_text.replace(',', '\n').split('\n'):
            number = line.strip()
            if number:
                to_numbers.append(number)
        
        if not to_numbers:
            flash('Please provide at least one recipient number.', 'error')
            return render_template('admin/sms.html')
        
        if len(to_numbers) > 100:
            flash('Maximum 100 recipients allowed.', 'error')
            return render_template('admin/sms.html')
        
        # Send SMS
        try:
            from zeep import Client
            from zeep.transports import Transport
            from requests import Session
            
            session = Session()
            transport = Transport(session=session, cache=None)
            
            wsdl_url = "https://api.payamak-panel.com/post/Send.asmx?wsdl"
            client = Client(wsdl=wsdl_url, transport=transport)
            
            data = {
                "username": username,
                "password": password,
                "to": to_numbers,
                "from": from_number,
                "text": text,
                "isflash": is_flash
            }
            
            result = client.service.SendSimpleSMS(**data)
            
            if result == 1:
                flash(f'✅ SMS sent successfully to {len(to_numbers)} recipient(s)!', 'success')
            else:
                flash(f'❌ SMS failed. Error code: {result}', 'error')
                
        except Exception:
            current_app.logger.exception('Error sending SMS')
            flash('Error sending SMS. Check the server logs for details.', 'error')
        
        return render_template('admin/sms.html')
    
    return render_template('admin/sms.html')


