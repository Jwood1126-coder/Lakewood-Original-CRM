"""Auth forms (Flask-WTF)."""
from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, Length


class LoginForm(FlaskForm):
    email = StringField(
        "Email",
        validators=[DataRequired(), Email(), Length(max=255)],
        render_kw={"autocomplete": "username", "autofocus": True},
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(), Length(max=200)],
        render_kw={"autocomplete": "current-password"},
    )
    remember = BooleanField("Remember me", default=True)
    submit = SubmitField("Sign in")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField(
        "Current password", validators=[DataRequired(), Length(max=200)]
    )
    new_password = PasswordField(
        "New password", validators=[DataRequired(), Length(min=10, max=200)]
    )
    confirm_password = PasswordField(
        "Confirm new password", validators=[DataRequired(), Length(max=200)]
    )
    submit = SubmitField("Change password")
