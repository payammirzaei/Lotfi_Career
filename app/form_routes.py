"""
Form builder and submission routes
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, current_app
from flask_login import login_required, current_user
from app.admin import approved_required
from app import db, limiter, client_ip
from flask_wtf.csrf import generate_csrf
from app.models import Form, FormSubmission, FormSubmissionField, SUBMISSION_STATUSES, EMPLOYMENT_TYPES
from app.applications import can_manage, summarize, parse_date
from app.auth import is_safe_redirect
from app.forms import allowed_file, render_form_from_template, parse_form_template
from flask import url_for
from werkzeug.utils import secure_filename
from datetime import datetime
import logging
import os
import json
import uuid

log = logging.getLogger(__name__)


def _render_public_form(form):
    submit_url = url_for('forms.submit', form_id=form.id)
    return render_form_from_template(form.form_template, form.id, submit_url, generate_csrf())

form_bp = Blueprint('forms', __name__, url_prefix='/forms')


def _label(field_name):
    """'your-name' -> 'your name' for messages shown to applicants"""
    return field_name.replace('-', ' ').replace('_', ' ').strip()


def _apply_ad_details(form, data):
    """Optional job-ad fields shared by create/edit"""
    form.location = (data.get('location') or '').strip()[:120] or None
    employment_type = (data.get('employment_type') or '').strip()
    form.employment_type = employment_type if employment_type in EMPLOYMENT_TYPES else None
    closes = parse_date(data.get('closes_at'))
    form.closes_at = closes.date() if closes else None


DEFAULT_TEMPLATE = '''<div class="max-w-2xl mx-auto p-6 sm:p-8 bg-white rounded-2xl shadow-lg space-y-6">

  <div>
    <label class="block text-sm font-medium text-gray-700 mb-1">Full name *</label>
    [text* full-name class="w-full rounded-lg border-gray-300 focus:border-indigo-500 focus:ring-indigo-500"]
  </div>

  <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
    <div>
      <label class="block text-sm font-medium text-gray-700 mb-1">Email *</label>
      [email* email class="w-full rounded-lg border-gray-300 focus:border-indigo-500 focus:ring-indigo-500"]
    </div>
    <div>
      <label class="block text-sm font-medium text-gray-700 mb-1">Phone *</label>
      [tel* phone class="w-full rounded-lg border-gray-300 focus:border-indigo-500 focus:ring-indigo-500"]
    </div>
  </div>

  <div>
    <label class="block text-sm font-medium text-gray-700 mb-1">Resume / CV (PDF or Word) *</label>
    [file* resume filetypes:pdf|doc|docx class="w-full text-sm"]
  </div>

  <div>
    <label class="block text-sm font-medium text-gray-700 mb-1">Why do you want to join us?</label>
    [textarea cover-letter rows:5 class="w-full rounded-lg border-gray-300 focus:border-indigo-500 focus:ring-indigo-500"]
  </div>

  <div class="pt-2">
    [submit class="w-full bg-indigo-600 text-white py-3 rounded-lg font-semibold hover:bg-indigo-700 transition" "Submit application"]
  </div>

</div>'''


@form_bp.route('/')
@login_required
@approved_required
def index():
    """List the current user's job ads (admins use the admin ads page)"""
    if current_user.is_admin:
        return redirect(url_for('admin.ads'))
    forms = Form.query.filter_by(user_id=current_user.id).order_by(Form.created_at.desc()).all()
    return render_template('forms/index.html', forms=forms)


def _ad_errors(title, form_template):
    errors = []
    if not title:
        errors.append('Job title is required.')
    elif len(title) > 200:
        errors.append('Job title must be at most 200 characters.')
    if not form_template:
        errors.append('The application form cannot be empty.')
    return errors


@form_bp.route('/create', methods=['GET', 'POST'])
@login_required
@approved_required
def create():
    """Create a new job ad"""
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        form_template = request.form.get('form_template', '').strip()

        errors = _ad_errors(title, form_template)
        if errors:
            for error in errors:
                flash(error, 'error')
            # keep everything the user typed
            return render_template('forms/create.html', default_template=form_template)

        form = Form(
            title=title,
            description=description,
            form_template=form_template,
            user_id=current_user.id,
            is_active=True,
        )
        _apply_ad_details(form, request.form)

        try:
            db.session.add(form)
            db.session.commit()
        except Exception:
            db.session.rollback()
            log.exception('Error creating job ad')
            flash('An error occurred while creating the job ad. Please try again.', 'error')
            return render_template('forms/create.html', default_template=form_template)

        flash(f'Job ad "{form.title}" created and published.', 'success')
        if current_user.is_admin:
            return redirect(url_for('admin.ads'))
        return redirect(url_for('forms.index'))

    return render_template('forms/create.html', default_template=DEFAULT_TEMPLATE)


@form_bp.route('/<int:form_id>/edit', methods=['GET', 'POST'])
@login_required
@approved_required
def edit(form_id):
    """Edit a job ad"""
    form = Form.query.get_or_404(form_id)

    if not can_manage(form):
        flash('You do not have permission to edit this job ad.', 'error')
        return redirect(url_for('forms.index'))

    if request.method == 'POST':
        form.title = request.form.get('title', '').strip()
        form.description = request.form.get('description', '').strip()
        form.form_template = request.form.get('form_template', '').strip()
        form.is_active = request.form.get('is_active') == '1'
        _apply_ad_details(form, request.form)

        errors = _ad_errors(form.title, form.form_template)
        if errors:
            for error in errors:
                flash(error, 'error')
            # render with the unsaved edits, then discard them
            with db.session.no_autoflush:
                html = render_template('forms/edit.html', form=form)
            db.session.rollback()
            return html

        try:
            db.session.commit()
            flash('Job ad saved.', 'success')
            return redirect(url_for('forms.edit', form_id=form.id))
        except Exception as e:
            db.session.rollback()
            flash('An error occurred while saving the job ad.', 'error')
            return render_template('forms/edit.html', form=form)

    return render_template('forms/edit.html', form=form)


@form_bp.route('/<int:form_id>/view')
def view(form_id):
    """View and submit a form (public)"""
    form = Form.query.get_or_404(form_id)

    if not form.is_open:
        return render_template('forms/closed.html', form=form), 410

    return render_template('forms/view.html', form=form, form_html=_render_public_form(form))


@form_bp.route('/<int:form_id>/thanks')
def thanks(form_id):
    """Confirmation page shown after a successful application"""
    form = Form.query.get_or_404(form_id)
    return render_template('forms/thanks.html', form=form)


@form_bp.route('/<int:form_id>/submit', methods=['POST'])
@limiter.limit('10 per minute; 100 per hour')
def submit(form_id):
    """Handle form submission"""
    form = Form.query.get_or_404(form_id)

    if not form.is_open:
        return render_template('forms/closed.html', form=form), 410

    # Parse form template to get required fields
    fields = parse_form_template(form.form_template)
    required_fields = {f['name']: f for f in fields if f.get('required', False)}

    # Validate required fields
    errors = []
    for field_name, field_def in required_fields.items():
        if field_def['type'] == 'file':
            if field_name not in request.files or not request.files[field_name].filename:
                errors.append(f'Please attach {_label(field_name)}.')
        elif field_name not in request.form or not request.form[field_name].strip():
            errors.append(f'Please fill in {_label(field_name)}.')

    # Validate quiz fields
    quiz_fields = [f for f in fields if f.get('type') == 'quiz']
    for quiz_field in quiz_fields:
        field_name = quiz_field.get('name')
        if field_name and field_name in request.form:
            # Extract answer from attributes
            attrs = quiz_field.get('attributes', {})
            correct_answer = attrs.get('answer', '')
            user_answer = request.form[field_name].strip()
            if user_answer.lower() != correct_answer.lower():
                errors.append('Quiz answer is incorrect.')

    if errors:
        for error in errors:
            flash(error, 'error')
        # Re-render form with errors
        return render_template('forms/view.html', form=form, form_html=_render_public_form(form))

    # Create submission
    submission = FormSubmission(
        form_id=form.id,
        ip_address=client_ip(),
        user_agent=request.headers.get('User-Agent', '')[:255]
    )
    db.session.add(submission)
    db.session.flush()  # Get submission ID

    # Process form fields
    saved_files = []
    for field in fields:
        field_name = field['name'][:100]
        field_type = field['type']

        if field_type == 'file':
            if field_name in request.files:
                file = request.files[field_name]
                if file and file.filename and allowed_file(file.filename):
                    # Unique, non-guessable name; keep a sanitized original for readability
                    safe_name = secure_filename(file.filename)[-100:] or 'file'
                    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:12]}_{safe_name}"

                    # Ensure base uploads folder exists first
                    upload_folder = current_app.config['UPLOAD_FOLDER']
                    try:
                        os.makedirs(upload_folder, exist_ok=True)
                    except OSError as e:
                        db.session.rollback()
                        log.error('Cannot create upload folder %s: %s', upload_folder, e)
                        flash('File uploads are temporarily unavailable. Please try again later.', 'error')
                        return redirect(url_for('forms.view', form_id=form.id))

                    # Create form-specific upload directory if it doesn't exist (platform-independent)
                    upload_dir = os.path.join(upload_folder, str(form.id))
                    try:
                        os.makedirs(upload_dir, exist_ok=True)
                    except OSError as e:
                        # If directory creation fails, raise a user-friendly error
                        db.session.rollback()
                        log.error('Cannot create upload directory %s: %s', upload_dir, e)
                        flash('File uploads are temporarily unavailable. Please try again later.', 'error')
                        return redirect(url_for('forms.view', form_id=form.id))

                    # Save file using platform-independent path
                    file_path = os.path.join(upload_dir, filename)
                    file.save(file_path)
                    saved_files.append(file_path)

                    # Store relative path (without 'uploads/' prefix since route already has it)
                    # Format: form_id/filename (e.g., "1/filename.pdf")
                    relative_path = f'{form.id}/{filename}'

                    submission_field = FormSubmissionField(
                        submission_id=submission.id,
                        field_name=field_name,
                        file_path=relative_path,
                        file_name=file.filename[:255]
                    )
                    db.session.add(submission_field)

        elif field_type in ['checkbox', 'radio']:
            # Handle multiple values
            values = request.form.getlist(field_name)
            if values:
                submission_field = FormSubmissionField(
                    submission_id=submission.id,
                    field_name=field_name,
                    field_value=json.dumps(values)
                )
                db.session.add(submission_field)

        elif field_name in request.form:
            value = request.form[field_name]
            if value:
                submission_field = FormSubmissionField(
                    submission_id=submission.id,
                    field_name=field_name,
                    field_value=value
                )
                db.session.add(submission_field)

    try:
        db.session.commit()
        return redirect(url_for('forms.thanks', form_id=form.id))
    except Exception:
        db.session.rollback()
        log.exception('Error saving submission for form %s', form.id)
        for path in saved_files:  # don't leave orphaned files behind
            try:
                os.remove(path)
            except OSError:
                pass
        flash('An error occurred while submitting the form. Please try again.', 'error')
        return render_template('forms/view.html', form=form, form_html=_render_public_form(form))


@form_bp.route('/<int:form_id>/submissions')
@login_required
@approved_required
def submissions(form_id):
    """View form submissions"""
    form = Form.query.get_or_404(form_id)

    if not can_manage(form):
        flash('You do not have permission to view these submissions.', 'error')
        return redirect(url_for('forms.index'))

    query = FormSubmission.query.filter_by(form_id=form.id)
    status = request.args.get('status', '')
    if status in SUBMISSION_STATUSES:
        query = query.filter_by(status=status)
    submissions_list = query.order_by(FormSubmission.submitted_at.desc()).all()

    return render_template('forms/submissions.html', form=form, submissions=submissions_list,
                           summaries=summarize(submissions_list), status=status)


@form_bp.route('/<int:form_id>/submissions/<int:submission_id>')
@login_required
@approved_required
def submission_detail(form_id, submission_id):
    """View submission details with review panel and prev/next navigation"""
    form = Form.query.get_or_404(form_id)
    submission = FormSubmission.query.get_or_404(submission_id)

    if not can_manage(form) or submission.form_id != form.id:
        flash('You do not have permission to view this submission.', 'error')
        return redirect(url_for('forms.index'))

    siblings = FormSubmission.query.filter_by(form_id=form.id)
    newer = (siblings.filter(FormSubmission.id > submission.id)
             .order_by(FormSubmission.id.asc()).first())
    older = (siblings.filter(FormSubmission.id < submission.id)
             .order_by(FormSubmission.id.desc()).first())

    return render_template('forms/submission_detail.html', form=form, submission=submission,
                           summary=summarize([submission])[submission.id],
                           newer=newer, older=older)


@form_bp.route('/<int:form_id>/submissions/<int:submission_id>/review', methods=['POST'])
@login_required
@approved_required
def review_submission(form_id, submission_id):
    """Update an application's status and internal notes"""
    form = Form.query.get_or_404(form_id)
    submission = FormSubmission.query.get_or_404(submission_id)
    if not can_manage(form) or submission.form_id != form.id:
        flash('You do not have permission to review this submission.', 'error')
        return redirect(url_for('forms.index'))

    status = request.form.get('status')
    if status in SUBMISSION_STATUSES:
        submission.status = status
    if 'notes' in request.form:
        submission.notes = request.form.get('notes', '').strip()[:5000] or None
    submission.reviewed_at = datetime.utcnow()
    submission.reviewed_by_id = current_user.id
    db.session.commit()
    flash(f'Application #{submission.id} saved as {SUBMISSION_STATUSES[submission.status][0]}.', 'success')

    target = request.form.get('next')
    if is_safe_redirect(target):
        return redirect(target)
    return redirect(url_for('forms.submission_detail', form_id=form.id, submission_id=submission.id))


@form_bp.route('/<int:form_id>/submissions/<int:submission_id>/delete', methods=['POST'])
@login_required
@approved_required
def delete_submission(form_id, submission_id):
    """Delete a submission and its attached files"""
    form = Form.query.get_or_404(form_id)
    submission = FormSubmission.query.get_or_404(submission_id)

    if not can_manage(form) or submission.form_id != form.id:
        flash('You do not have permission to delete this submission.', 'error')
        return redirect(url_for('forms.index'))

    try:
        # Delete all attached files
        upload_folder = current_app.config['UPLOAD_FOLDER']
        files_deleted = 0

        for field in submission.fields:
            if field.file_path:
                # Parse file path: format is "form_id/filename"
                try:
                    parts = field.file_path.split('/', 1)
                    if len(parts) == 2:
                        directory = parts[0]
                        filename = parts[1]
                        file_path = os.path.join(upload_folder, directory, filename)

                        # Delete the file if it exists
                        if os.path.exists(file_path) and os.path.isfile(file_path):
                            os.remove(file_path)
                            files_deleted += 1
                except Exception as e:
                    # Log error but continue with deletion
                    import logging
                    logging.warning(f'Error deleting file {field.file_path}: {str(e)}')

        # Delete the submission (cascade will delete fields)
        db.session.delete(submission)
        db.session.commit()

        flash(f'Submission deleted successfully! {files_deleted} file(s) removed.', 'success')
    except Exception as e:
        db.session.rollback()
        flash('An error occurred while deleting the submission.', 'error')
        import logging
        logging.error(f'Error deleting submission {submission_id}: {str(e)}')

    return redirect(url_for('forms.submissions', form_id=form.id))


@form_bp.route('/<int:form_id>/delete', methods=['POST'])
@login_required
@approved_required
def delete(form_id):
    """Delete a form"""
    form = Form.query.get_or_404(form_id)

    if not can_manage(form):
        flash('You do not have permission to delete this form.', 'error')
        return redirect(url_for('forms.index'))

    try:
        form_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], str(form.id))
        db.session.delete(form)
        db.session.commit()
        # Remove the form's uploaded files so they are not served to a future form with the same id
        import shutil
        shutil.rmtree(form_dir, ignore_errors=True)
        flash('Form deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash('An error occurred while deleting the form.', 'error')

    return redirect(url_for('forms.index'))


@login_required
@approved_required
def uploaded_file(filename):
    """Serve uploaded files - works on both Windows and Linux"""
    from flask import abort
    from urllib.parse import unquote

    # Decode URL-encoded characters (handles %5C for backslash, %2F for forward slash, etc.)
    filename = unquote(filename)

    # Normalize path separators - convert all backslashes to forward slashes for parsing
    # (Windows uses \ but we store URLs with /)
    filename = filename.replace('\\', '/')

    # filename format: uploads/form_id/filename or form_id/filename
    if filename.startswith('uploads/'):
        filename = filename[8:]  # Remove 'uploads/' prefix

    # Split to get directory (form_id) and file
    parts = filename.split('/', 1)
    if len(parts) == 2:
        directory = parts[0]
        file = parts[1]

        # Verify the form belongs to the current user
        try:
            form_id = int(directory)
            form = Form.query.get(form_id)
            if form and can_manage(form):
                # Use os.path.join for platform-independent file system path
                # This handles Windows (\) and Linux (/) automatically
                upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], directory)
                file_path = os.path.join(upload_dir, file)

                # Check if file exists (platform-independent)
                if os.path.exists(file_path) and os.path.isfile(file_path):
                    # send_from_directory handles platform differences automatically
                    # Only images are shown inline; everything else is forced to download
                    inline = file.rsplit('.', 1)[-1].lower() in {'png', 'jpg', 'jpeg', 'gif', 'pdf'}
                    return send_from_directory(upload_dir, file, as_attachment=not inline)
        except (ValueError, AttributeError, TypeError) as e:
            # Log error in production, but don't expose to user
            pass

    # If we get here, file not found or access denied
    abort(404)

