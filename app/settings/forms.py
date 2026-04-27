"""Settings forms."""
from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    RadioField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
    TimeField,
)
from wtforms.validators import DataRequired, Email, Length, Optional, Regexp

THEMES = [
    ("dark",   "Dark (default)"),
    ("amoled", "AMOLED — true black"),
    ("light",  "Light"),
]


class ProfileForm(FlaskForm):
    display_name = StringField(
        "Display name",
        validators=[Optional(), Length(max=120)],
        render_kw={"placeholder": "How you appear to yourself in the app"},
    )
    email = StringField(
        "Email",
        validators=[DataRequired(), Email(), Length(max=255)],
    )
    submit = SubmitField("Save profile")


class ThemeForm(FlaskForm):
    theme = RadioField("Theme", choices=THEMES, default="dark")
    submit = SubmitField("Apply")


class BusinessForm(FlaskForm):
    name = StringField("Business name", validators=[DataRequired(), Length(max=200)])
    address = StringField("Address", validators=[Optional(), Length(max=300)])
    phone = StringField("Phone", validators=[Optional(), Length(max=40)])
    email = StringField("Email (for invoices)",
                        validators=[Optional(), Email(), Length(max=255)])
    submit = SubmitField("Save business info")


class AssistantForm(FlaskForm):
    enabled = BooleanField("Enable Claude assistant", default=True)
    model = SelectField(
        "Model",
        choices=[
            ("claude-opus-4-7",   "Opus 4.7 — smartest, most expensive"),
            ("claude-sonnet-4-6", "Sonnet 4.6 — fast, cheaper, very capable"),
            ("claude-haiku-4-5-20251001", "Haiku 4.5 — fastest, cheapest"),
        ],
        default="claude-opus-4-7",
    )
    system_prompt = TextAreaField(
        "System prompt (CLAUDE.md)",
        validators=[Optional(), Length(max=20000)],
        render_kw={"rows": 18,
                   "placeholder": "Tell Claude how to talk to you, your work hours, "
                                  "preferences, customer notes, etc."},
    )
    submit = SubmitField("Save assistant settings")


class NotificationForm(FlaskForm):
    daily_briefing  = BooleanField("Daily morning briefing", default=True)
    daily_time      = StringField(
        "Time (24-hour, your local time)",
        default="06:30",
        validators=[Regexp(r"^\d{1,2}:\d{2}$",
                           message="Format: HH:MM (e.g. 06:30)")],
    )
    weekly_briefing = BooleanField("Weekly look-ahead (Sunday evening)", default=True)
    monthly_report  = BooleanField("Monthly report (1st of month)", default=True)
    job_day_reminder = BooleanField("Reminder the morning of each scheduled job",
                                     default=True)
    email_channel   = BooleanField("Email channel (in addition to in-app)",
                                    default=True)
    notify_email_to = StringField("Send email to",
                                   validators=[Optional(), Email(), Length(max=255)])
    submit = SubmitField("Save notification preferences")
