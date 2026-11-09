"""
Helpers shared by the admin dashboard and form owners' pages:
applicant summaries, filtering, permissions and CSV export.
"""
import csv
import io
import re
from datetime import datetime, timedelta

from flask import url_for
from flask_login import current_user
from sqlalchemy import or_

from app import db
from app.models import Form, FormSubmission, FormSubmissionField, SUBMISSION_STATUSES

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def can_manage(form):
    """Owners manage their own ads; admins manage every ad."""
    return current_user.is_authenticated and (
        current_user.is_admin or form.user_id == current_user.id)


def summarize(submissions):
    """Return {submission_id: {'name', 'email', 'phone', 'files'}} using one query."""
    ids = [s.id for s in submissions]
    result = {i: {'name': None, 'email': None, 'phone': None, 'files': 0} for i in ids}
    if not ids:
        return result
    fields = (FormSubmissionField.query
              .filter(FormSubmissionField.submission_id.in_(ids))
              .order_by(FormSubmissionField.id).all())
    first_text = {}
    for f in fields:
        info = result[f.submission_id]
        if f.file_path:
            info['files'] += 1
            continue
        value = (f.field_value or '').strip()
        if not value or value.startswith('['):  # skip JSON lists (checkbox/radio)
            continue
        name = f.field_name.lower()
        if info['email'] is None and ('mail' in name or _EMAIL_RE.match(value)):
            info['email'] = value
        elif info['phone'] is None and any(k in name for k in ('tel', 'phone', 'mobile')):
            info['phone'] = value
        elif info['name'] is None and 'name' in name:
            info['name'] = value
        first_text.setdefault(f.submission_id, value)
    for sid, info in result.items():
        if not info['name']:
            info['name'] = (first_text.get(sid) or info['email'] or f'Applicant #{sid}')[:80]
    return result


def parse_date(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d') if value else None
    except ValueError:
        return None


def filtered_submissions(args, base_query=None):
    """Apply inbox filters (ad, status, q, from, to) from a request.args-like mapping."""
    query = base_query if base_query is not None else FormSubmission.query
    query = query.join(Form, FormSubmission.form_id == Form.id)

    form_id = args.get('ad', type=int)
    if form_id:
        query = query.filter(FormSubmission.form_id == form_id)

    status = args.get('status', '')
    if status in SUBMISSION_STATUSES:
        query = query.filter(FormSubmission.status == status)

    q = (args.get('q') or '').strip()[:100]
    if q:
        if q.lstrip('#').isdigit():
            query = query.filter(FormSubmission.id == int(q.lstrip('#')))
        else:
            like = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            match = (db.session.query(FormSubmissionField.id)
                     .filter(FormSubmissionField.submission_id == FormSubmission.id,
                             or_(FormSubmissionField.field_value.ilike(like, escape='\\'),
                                 FormSubmissionField.file_name.ilike(like, escape='\\')))
                     .exists())
            query = query.filter(or_(match, FormSubmission.notes.ilike(like, escape='\\')))

    start = parse_date(args.get('from'))
    if start:
        query = query.filter(FormSubmission.submitted_at >= start)
    end = parse_date(args.get('to'))
    if end:
        query = query.filter(FormSubmission.submitted_at < end + timedelta(days=1))

    return query


def _csv_safe(value):
    """Neutralise spreadsheet formula injection (=, +, -, @ at the start of a cell)."""
    value = '' if value is None else str(value)
    if value and value[0] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + value
    return value


def export_csv(submissions):
    """Build a UTF-8 (BOM, Excel-friendly) CSV of submissions with one column per field."""
    ids = [s.id for s in submissions]
    fields = (FormSubmissionField.query
              .filter(FormSubmissionField.submission_id.in_(ids))
              .order_by(FormSubmissionField.id).all()) if ids else []

    columns, values = [], {}
    for f in fields:
        if f.field_name not in columns:
            columns.append(f.field_name)
        if f.file_path:
            cell = url_for('uploaded_file', filename=f.file_path, _external=True)
        else:
            cell = f.field_value
            try:
                import json
                parsed = json.loads(cell) if cell and cell.startswith('[') else None
                if isinstance(parsed, list):
                    cell = ', '.join(map(str, parsed))
            except ValueError:
                pass
        values[(f.submission_id, f.field_name)] = cell

    out = io.StringIO()
    out.write('﻿')
    writer = csv.writer(out)
    writer.writerow(['ID', 'Ad', 'Submitted at', 'Status', 'Notes'] + columns)
    for s in submissions:
        writer.writerow([
            s.id, _csv_safe(s.form.title), s.submitted_at.strftime('%Y-%m-%d %H:%M') if s.submitted_at else '',
            SUBMISSION_STATUSES.get(s.status, (s.status,))[0], _csv_safe(s.notes),
        ] + [_csv_safe(values.get((s.id, c))) for c in columns])
    return out.getvalue()
