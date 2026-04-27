"""Settings — landing page + sub-pages for profile, theme, business info,
backup tools, Jobber import."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func, select

from app.auth.forms import ChangePasswordForm
from app.extensions import db
from app.models.audit_log import AuditLog
from app.models.client import Client
from app.models.job import Job
from app.models.property import Property
from app.models.setting import all_business_settings, get_setting, set_setting
from app.services.backup import run_backup
from app.settings.forms import (
    THEMES,
    AssistantForm,
    BusinessForm,
    JobberClientsImportForm,
    NotificationForm,
    ProfileForm,
    ThemeForm,
)

bp = Blueprint("settings", __name__, template_folder="../templates/settings")


def _last_backup_info() -> dict | None:
    backup_dir: Path = current_app.config["BACKUP_DIR"]
    files = sorted(backup_dir.glob("snapshot-*.tar.gz"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    p = files[0]
    return {
        "name": p.name,
        "size_kb": round(p.stat().st_size / 1024, 1),
        "when": datetime.utcfromtimestamp(p.stat().st_mtime),
        "count_total": len(files),
    }


# ---------- index ----------

@bp.route("/")
@login_required
def index():
    biz = all_business_settings()
    last = _last_backup_info()
    counts = {
        "clients":   db.session.scalar(select(func.count(Client.id))) or 0,
        "properties": db.session.scalar(select(func.count(Property.id))) or 0,
        "jobs":      db.session.scalar(select(func.count(Job.id))) or 0,
    }
    return render_template(
        "settings/index.html",
        business=biz,
        last_backup=last,
        counts=counts,
    )


# ---------- profile ----------

@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        new_email = form.email.data.strip().lower()
        current_user.display_name = (form.display_name.data or "").strip() or None
        current_user.email = new_email
        db.session.commit()
        flash("Profile saved.", "success")
        return redirect(url_for("settings.index"))
    return render_template("settings/profile.html", form=form)


# ---------- theme ----------

@bp.route("/theme", methods=["GET", "POST"])
@login_required
def theme():
    form = ThemeForm(theme=current_user.theme or "dark")
    if form.validate_on_submit():
        current_user.theme = form.theme.data
        db.session.commit()
        flash("Theme updated.", "success")
        return redirect(url_for("settings.theme"))
    return render_template("settings/theme.html", form=form, themes=THEMES)


# ---------- business info ----------

@bp.route("/business", methods=["GET", "POST"])
@login_required
def business():
    biz = all_business_settings()
    form = BusinessForm(data={
        "name":    biz["name"],
        "address": biz["address"],
        "phone":   biz["phone"],
        "email":   biz["email"],
    })
    if form.validate_on_submit():
        set_setting("business_name", form.name.data.strip())
        set_setting("business_address", (form.address.data or "").strip())
        set_setting("business_phone", (form.phone.data or "").strip())
        set_setting("business_email", (form.email.data or "").strip().lower())
        flash("Business info saved.", "success")
        return redirect(url_for("settings.business"))
    return render_template("settings/business.html", form=form)


# ---------- password ----------

@bp.route("/password", methods=["GET", "POST"])
@login_required
def password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.verify_password(form.current_password.data):
            flash("Current password is incorrect.", "error")
        elif form.new_password.data != form.confirm_password.data:
            flash("New passwords don't match.", "error")
        else:
            current_user.set_password(form.new_password.data)
            db.session.commit()
            flash("Password updated.", "success")
            return redirect(url_for("settings.index"))
    return render_template("settings/password.html", form=form)


# ---------- backup ----------

@bp.route("/backup")
@login_required
def backup():
    backup_dir: Path = current_app.config["BACKUP_DIR"]
    files = sorted(backup_dir.glob("snapshot-*.tar.gz"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    backups = [{
        "name": p.name,
        "size_kb": round(p.stat().st_size / 1024, 1),
        "when": datetime.utcfromtimestamp(p.stat().st_mtime),
    } for p in files[:30]]
    return render_template("settings/backup.html", backups=backups)


@bp.route("/backup/run", methods=["POST"])
@login_required
def backup_run():
    try:
        result = run_backup()
        if result.get("status") == "ok":
            uploaded = " (uploaded to cloud)" if result.get("uploaded_to_b2") else " (local only — set B2 env vars for off-site)"
            kb = round(result.get("size_bytes", 0) / 1024, 1)
            flash(f"Backup created: {kb} KB{uploaded}.", "success")
        else:
            flash(f"Backup skipped: {result.get('reason', 'unknown')}", "warning")
    except Exception as e:
        current_app.logger.exception("Manual backup failed: %s", e)
        flash(f"Backup failed: {e}", "error")
    return redirect(url_for("settings.backup"))


@bp.route("/backup/download/<path:name>")
@login_required
def backup_download(name: str):
    """Download a backup tarball. send_from_directory blocks path traversal."""
    backup_dir: Path = current_app.config["BACKUP_DIR"]
    return send_from_directory(backup_dir, name, as_attachment=True)


# ---------- Assistant settings ----------

@bp.route("/assistant", methods=["GET", "POST"])
@login_required
def assistant():
    from app.services.assistant import (
        ASSISTANT_DEFAULT_MODEL,
        ASSISTANT_MODELS,
        load_system_prompt,
        save_system_prompt,
    )

    form = AssistantForm(data={
        "enabled": get_setting("assistant_enabled", "1") == "1",
        "model": get_setting("assistant_model", ASSISTANT_DEFAULT_MODEL),
        "system_prompt": load_system_prompt(),
    })

    if form.validate_on_submit():
        set_setting("assistant_enabled", "1" if form.enabled.data else "0")
        set_setting("assistant_model", form.model.data)
        save_system_prompt(form.system_prompt.data or "")
        flash("Assistant settings saved.", "success")
        return redirect(url_for("settings.assistant"))

    has_key = bool(current_app.config.get("ANTHROPIC_API_KEY"))
    return render_template(
        "settings/assistant.html",
        form=form,
        has_api_key=has_key,
        models=ASSISTANT_MODELS,
    )


# ---------- Notifications settings ----------

@bp.route("/notifications", methods=["GET", "POST"])
@login_required
def notifications():
    EVENT_KEYS = ("event_quote_sent", "event_quote_accepted",
                  "event_quote_converted", "event_job_complete",
                  "event_invoice_sent", "event_invoice_paid",
                  "event_payment_received")
    form = NotificationForm(data={
        "daily_briefing":  get_setting("notify_daily", "1") == "1",
        "daily_time":      get_setting("notify_daily_time", "06:30"),
        "weekly_briefing": get_setting("notify_weekly", "1") == "1",
        "monthly_report":  get_setting("notify_monthly", "1") == "1",
        "job_day_reminder": get_setting("notify_job_day", "1") == "1",
        **{k: get_setting(f"notify_{k}", "1") == "1" for k in EVENT_KEYS},
        "email_channel":   get_setting("notify_email", "1") == "1",
        "notify_email_to": get_setting("notify_email_to",
                                       current_app.config.get("NOTIFY_EMAIL") or ""),
    })

    if form.validate_on_submit():
        set_setting("notify_daily", "1" if form.daily_briefing.data else "0")
        set_setting("notify_daily_time", form.daily_time.data or "06:30")
        set_setting("notify_weekly", "1" if form.weekly_briefing.data else "0")
        set_setting("notify_monthly", "1" if form.monthly_report.data else "0")
        set_setting("notify_job_day", "1" if form.job_day_reminder.data else "0")
        for k in EVENT_KEYS:
            set_setting(f"notify_{k}", "1" if getattr(form, k).data else "0")
        set_setting("notify_email", "1" if form.email_channel.data else "0")
        set_setting("notify_email_to", (form.notify_email_to.data or "").strip())
        # Re-schedule the cron jobs with the new times
        from app.services.scheduler import reschedule_recurring_jobs
        reschedule_recurring_jobs()
        flash("Notification preferences saved.", "success")
        return redirect(url_for("settings.notifications"))

    has_email = bool(current_app.config.get("SMTP_USER")
                     and current_app.config.get("SMTP_PASSWORD"))
    return render_template(
        "settings/notifications.html",
        form=form,
        has_email=has_email,
    )


@bp.route("/notifications/test-email", methods=["POST"])
@login_required
def notifications_test_email():
    from app.services.email import send_email
    to = (get_setting("notify_email_to") or current_app.config.get("NOTIFY_EMAIL") or "").strip()
    if not to:
        flash("No notification email address set.", "error")
        return redirect(url_for("settings.notifications"))
    try:
        send_email(
            to=to,
            subject="Lakewood Original — test notification",
            html="<p>This is a test message from your Lakewood Original CRM.</p>"
                 "<p>If you received it, your Gmail SMTP is correctly configured.</p>",
        )
        flash(f"Sent. Check {to}.", "success")
    except Exception as e:
        current_app.logger.exception("Test email failed")
        flash(f"Email failed: {e}", "error")
    return redirect(url_for("settings.notifications"))


# ---------- Audit log ----------

@bp.route("/audit")
@login_required
def audit_log():
    entity_type = request.args.get("entity_type")
    entity_id = request.args.get("entity_id", type=int)
    operation = request.args.get("operation")

    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if operation in ("insert", "update", "delete"):
        stmt = stmt.where(AuditLog.operation == operation)
    stmt = stmt.limit(200)

    rows = db.session.scalars(stmt).all()

    types = db.session.scalars(
        select(AuditLog.entity_type).distinct().order_by(AuditLog.entity_type)
    ).all()

    return render_template(
        "settings/audit.html",
        rows=rows, types=types,
        f_entity_type=entity_type, f_entity_id=entity_id, f_operation=operation,
    )


# ---------- Notifications: send briefing now ----------

@bp.route("/notifications/send-briefing-now", methods=["POST"])
@login_required
def notifications_send_briefing():
    from app.services.briefing import build_and_send_daily_briefing
    try:
        result = build_and_send_daily_briefing(force=True)
        flash(f"Briefing built and {'sent via email' if result.get('emailed') else 'saved to your inbox in-app'}.", "success")
    except Exception as e:
        current_app.logger.exception("Manual briefing failed")
        flash(f"Briefing failed: {e}", "error")
    return redirect(url_for("settings.notifications"))


# ---------- Jobber CSV import (browser upload) ----------

@bp.route("/import-jobber-clients", methods=["GET", "POST"])
@login_required
def import_jobber_clients():
    """Upload Jobber's 'Export Clients' CSV. Dry-run by default;
    check the box to actually commit. Re-runs are idempotent (skip
    clients whose Jobber ID is already in our notes)."""
    from io import StringIO
    from pathlib import Path
    import tempfile
    from scripts.import_jobber_clients import parse_csv, write_clients

    form = JobberClientsImportForm()
    result = None
    parsed_preview = None

    if form.validate_on_submit():
        # Stream upload to a temp file so parse_csv can read by path
        f = form.csv_file.data
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".csv", delete=False
        ) as tmp:
            tmp.write(f.read())
            tmp_path = Path(tmp.name)
        try:
            parsed = parse_csv(tmp_path)
            parsed_preview = parsed[:10]  # show first 10 in the UI
            result = write_clients(parsed, commit=form.commit.data)
            result["total_parsed"] = len(parsed)
            result["total_properties_parsed"] = sum(
                len(c.properties) for c in parsed
            )
            if form.commit.data:
                flash(
                    f"Imported {result['stats']['clients_created']} clients "
                    f"and {result['stats']['properties_created']} properties.",
                    "success",
                )
            else:
                flash(
                    f"Dry run — parsed {len(parsed)} clients. "
                    f"Tick 'Yes, write to the database' and re-upload to commit.",
                    "info",
                )
        except Exception as e:
            current_app.logger.exception("Jobber import failed")
            flash(f"Import failed: {e}", "error")
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    return render_template(
        "settings/import_jobber_clients.html",
        form=form,
        result=result,
        parsed_preview=parsed_preview,
    )
