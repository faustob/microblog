from flask import render_template, redirect, url_for, flash, request
from urllib.parse import urlsplit
from flask import current_app
from markupsafe import escape
from app.telemetry import web_vital_inp, web_vital_lcp
from flask_login import login_user, logout_user, current_user
from flask_babel import _
import sqlalchemy as sa
from app import db
from app.auth import bp
from app.auth.forms import LoginForm, RegistrationForm, \
    ResetPasswordRequestForm, ResetPasswordForm
from app.models import User
from app.auth.email import send_password_reset_email


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(
            sa.select(User).where(User.username == form.username.data))
        if user is None or not user.check_password(form.password.data):
            flash(_('Invalid username or password'))
            return redirect(url_for('auth.login'))
        login_user(user, remember=form.remember_me.data)
        next_page = request.args.get('next')
        if not next_page or urlsplit(next_page).netloc != '':
            next_page = url_for('main.index')
        return redirect(next_page)
    return render_template('auth/login.html', title=_('Sign In'), form=form)


@bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('main.index'))


# --- Real User Monitoring (Core Web Vitals) -------------------------------
# Browser-reported LCP / INP are ingested here and recorded on the server
# meter (web.vital.lcp / web.vital.inp), dimensioned by the matched Flask
# route template and the device class.
_WEB_VITAL_INSTRUMENTS = {'LCP': web_vital_lcp, 'INP': web_vital_inp}


def _safe_route(route):
    """Keep http.route low cardinality: only accept known route templates."""
    if not route:
        return 'unknown'
    for rule in current_app.url_map.iter_rules():
        if rule.rule == route:
            return route
    return 'other'


@bp.route('/vitals', methods=['POST'])
def report_web_vitals():
    payload = request.get_json(silent=True) or {}
    samples = payload.get('metrics')
    if not isinstance(samples, list):
        samples = [payload]
    attributes = {
        'http.route': _safe_route(payload.get('route')),
        'device.type': 'mobile' if payload.get('mobile') else 'desktop',
    }
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        instrument = _WEB_VITAL_INSTRUMENTS.get(
            str(sample.get('name', '')).upper())
        value = sample.get('value')
        if instrument is None or isinstance(value, bool) or \
                not isinstance(value, (int, float)):
            continue
        if value < 0 or value > 3600000:
            continue
        instrument.record(float(value), attributes)
    return '', 204


@bp.after_app_request
def inject_web_vitals_reporter(response):
    """Add the client-side web-vitals reporter script to HTML pages."""
    try:
        if response.direct_passthrough or response.mimetype != 'text/html':
            return response
        body = response.get_data()
        if b'</body>' not in body:
            return response
        tag = (
            '<script src="{}" data-endpoint="{}" data-route="{}" defer>'
            '</script>'
        ).format(
            escape(url_for('static', filename='js/web_vitals_reporter.js')),
            escape(url_for('auth.report_web_vitals')),
            escape(request.url_rule.rule if request.url_rule else 'unknown'),
        ).encode('utf-8')
        response.set_data(body.replace(b'</body>', tag + b'</body>', 1))
    except Exception:  # telemetry must never break a page response
        current_app.logger.debug(
            'web vitals reporter injection skipped', exc_info=True)
    return response


@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash(_('Congratulations, you are now a registered user!'))
        return redirect(url_for('auth.login'))
    return render_template('auth/register.html', title=_('Register'),
                           form=form)


@bp.route('/reset_password_request', methods=['GET', 'POST'])
def reset_password_request():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = ResetPasswordRequestForm()
    if form.validate_on_submit():
        user = db.session.scalar(
            sa.select(User).where(User.email == form.email.data))
        if user:
            send_password_reset_email(user)
        flash(
            _('Check your email for the instructions to reset your password'))
        return redirect(url_for('auth.login'))
    return render_template('auth/reset_password_request.html',
                           title=_('Reset Password'), form=form)


@bp.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    user = User.verify_reset_password_token(token)
    if not user:
        return redirect(url_for('main.index'))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash(_('Your password has been reset.'))
        return redirect(url_for('auth.login'))
    return render_template('auth/reset_password.html', form=form)
