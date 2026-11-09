"""
Admin dashboard: overview, job-ad management and the applications inbox.
Routes are registered on the admin blueprint (/admin/...).
"""
from collections import Counter
from datetime import date, datetime, timedelta

from flask import Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import case, func

from app import db
from app.admin import admin_bp, admin_required
from app.applications import export_csv, filtered_submissions, summarize
from app.auth import is_safe_redirect
from app.models import Form, FormSubmission, SUBMISSION_STATUSES, User

PER_PAGE = 25
EXPORT_LIMIT = 10000


def _ad_stats():
    """{form_id: (total, new, last_submitted_at)} in one grouped query."""
    rows = (db.session.query(
                FormSubmission.form_id,
                func.count(FormSubmission.id),
                func.sum(case((FormSubmission.status == 'new', 1), else_=0)),
                func.max(FormSubmission.submitted_at))
            .group_by(FormSubmission.form_id).all())
    return {r[0]: (r[1], int(r[2] or 0), r[3]) for r in rows}


@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    """Overview: KPIs, 30-day trend, pipeline, recent applications, top ads"""
    now = datetime.utcnow()
    today = now.date()

    forms = Form.query.all()
    total_apps = FormSubmission.query.count()
    new_apps = FormSubmission.query.filter_by(status='new').count()
    last7 = FormSubmission.query.filter(FormSubmission.submitted_at >= now - timedelta(days=7)).count()
    prev7 = FormSubmission.query.filter(
        FormSubmission.submitted_at >= now - timedelta(days=14),
        FormSubmission.submitted_at < now - timedelta(days=7)).count()

    # 30-day trend (bucketed in Python: portable across PostgreSQL and SQLite)
    start = datetime.combine(today - timedelta(days=29), datetime.min.time())
    stamps = [r[0] for r in db.session.query(FormSubmission.submitted_at)
              .filter(FormSubmission.submitted_at >= start).all()]
    per_day = Counter(ts.date() for ts in stamps if ts)
    trend = [{'date': today - timedelta(days=i), 'count': per_day.get(today - timedelta(days=i), 0)}
             for i in range(29, -1, -1)]
    trend_max = max([d['count'] for d in trend] + [1])

    # Pipeline by status
    status_counts = dict(db.session.query(FormSubmission.status, func.count(FormSubmission.id))
                         .group_by(FormSubmission.status).all())
    pipeline = [(key, label, dot, status_counts.get(key, 0))
                for key, (label, _badge, dot) in SUBMISSION_STATUSES.items()]

    # Recent applications
    recent = FormSubmission.query.order_by(FormSubmission.submitted_at.desc()).limit(8).all()

    # Ads with most applications
    stats = _ad_stats()
    top_ads = sorted(forms, key=lambda f: stats.get(f.id, (0,))[0], reverse=True)[:5]
    closing_soon = sorted([f for f in forms if f.is_open and f.closes_at
                           and f.closes_at <= today + timedelta(days=7)],
                          key=lambda f: f.closes_at)

    kpis = {
        'open_ads': sum(1 for f in forms if f.is_open),
        'total_ads': len(forms),
        'total_apps': total_apps,
        'new_apps': new_apps,
        'last7': last7,
        'delta7': last7 - prev7,
        'pending_users': User.query.filter(User.is_approved.is_(False)).count(),
    }

    return render_template(
        'admin/dashboard.html', kpis=kpis, trend=trend, trend_max=trend_max,
        pipeline=pipeline, pipeline_total=sum(p[3] for p in pipeline),
        recent=recent, summaries=summarize(recent), top_ads=top_ads,
        ad_stats=stats, closing_soon=closing_soon)


# ---------------------------------------------------------------- Ads

@admin_bp.route('/ads')
@login_required
@admin_required
def ads():
    """All job ads with application counts and quick actions"""
    show = request.args.get('show', 'all')
    q = (request.args.get('q') or '').strip()

    query = Form.query
    if q:
        query = query.filter(Form.title.ilike(f'%{q[:100]}%'))
    forms = query.order_by(Form.created_at.desc()).all()

    if show == 'open':
        forms = [f for f in forms if f.is_open]
    elif show == 'closed':
        forms = [f for f in forms if not f.is_open]

    return render_template('admin/ads.html', forms=forms, ad_stats=_ad_stats(), show=show, q=q)


@admin_bp.route('/ads/<int:form_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_ad(form_id):
    """Open/close an ad without opening the editor"""
    form = Form.query.get_or_404(form_id)
    form.is_active = not form.is_active
    db.session.commit()
    flash(f'"{form.title}" is now {"active" if form.is_active else "inactive"}.', 'success')
    return redirect(_back(url_for('admin.ads')))


@admin_bp.route('/ads/<int:form_id>/duplicate', methods=['POST'])
@login_required
@admin_required
def duplicate_ad(form_id):
    """Copy an ad (template + details) as a new inactive draft"""
    src = Form.query.get_or_404(form_id)
    copy = Form(title=(src.title + ' (copy)')[:200], description=src.description,
                form_template=src.form_template, location=src.location,
                employment_type=src.employment_type, closes_at=None,
                is_active=False, user_id=current_user.id)
    db.session.add(copy)
    db.session.commit()
    flash('Ad duplicated as an inactive draft. Review it and activate when ready.', 'success')
    return redirect(url_for('forms.edit', form_id=copy.id))


# ---------------------------------------------------------------- Applications

@admin_bp.route('/applications')
@login_required
@admin_required
def applications():
    """Inbox of all applications with filters, search and pagination"""
    page = request.args.get('page', 1, type=int)
    query = filtered_submissions(request.args).order_by(FormSubmission.submitted_at.desc())
    pagination = query.paginate(page=page, per_page=PER_PAGE, error_out=False)

    status_counts = dict(db.session.query(FormSubmission.status, func.count(FormSubmission.id))
                         .group_by(FormSubmission.status).all())

    args = {k: v for k, v in request.args.items() if k != 'page' and v}
    return render_template(
        'admin/applications.html', pagination=pagination, items=pagination.items,
        summaries=summarize(pagination.items), ads=Form.query.order_by(Form.title).all(),
        status_counts=status_counts, args=args)


@admin_bp.route('/applications/export.csv')
@login_required
@admin_required
def export_applications():
    """CSV export of the currently filtered applications"""
    items = (filtered_submissions(request.args)
             .order_by(FormSubmission.submitted_at.desc()).limit(EXPORT_LIMIT).all())
    filename = f'applications_{datetime.now().strftime("%Y%m%d_%H%M")}.csv'
    return Response(export_csv(items), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename={filename}'})


@admin_bp.route('/applications/bulk', methods=['POST'])
@login_required
@admin_required
def bulk_applications():
    """Set the status of several applications at once"""
    status = request.form.get('status')
    ids = [int(i) for i in request.form.getlist('ids') if i.isdigit()][:500]
    if status not in SUBMISSION_STATUSES or not ids:
        flash('Select at least one application and a status.', 'error')
        return redirect(_back(url_for('admin.applications')))

    now = datetime.utcnow()
    updated = (FormSubmission.query.filter(FormSubmission.id.in_(ids))
               .update({'status': status, 'reviewed_at': now, 'reviewed_by_id': current_user.id},
                       synchronize_session=False))
    db.session.commit()
    flash(f'{updated} application(s) marked as {SUBMISSION_STATUSES[status][0]}.', 'success')
    return redirect(_back(url_for('admin.applications')))


def _back(default):
    target = request.form.get('next') or request.args.get('next')
    return target if is_safe_redirect(target) else default
