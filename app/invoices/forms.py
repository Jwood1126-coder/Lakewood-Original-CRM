"""Invoice + Payment forms."""
from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    DateTimeLocalField,
    DecimalField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class InvoiceForm(FlaskForm):
    subject = StringField(
        "Subject", validators=[DataRequired(), Length(max=200)],
        render_kw={"placeholder": "e.g. Bathroom repair", "autofocus": True},
    )
    client_id = SelectField("Client", coerce=int, validators=[DataRequired()], choices=[])
    property_id = SelectField("Property", coerce=int, validators=[DataRequired()], choices=[])
    job_id = SelectField("Linked job", coerce=int, validators=[Optional()], choices=[])

    due_date = DateField("Due date", validators=[Optional()])
    tax_rate_override = DecimalField(
        "Tax rate override",
        places=4,
        validators=[Optional(), NumberRange(min=0, max=1)],
        render_kw={"step": "0.0001",
                   "placeholder": "Blank = property rate"},
    )
    notes = TextAreaField(
        "Notes (shown on invoice)",
        validators=[Optional(), Length(max=10000)],
        render_kw={"rows": 3},
    )
    submit = SubmitField("Save invoice")


class PaymentForm(FlaskForm):
    amount = StringField(
        "Amount", validators=[DataRequired(), Length(max=20)],
        render_kw={"placeholder": "e.g. 250.00", "inputmode": "decimal"},
    )
    method = SelectField(
        "Method",
        choices=[
            ("check", "Check"), ("cash", "Cash"),
            ("zelle", "Zelle"), ("venmo", "Venmo"),
            ("card",  "Card / Stripe"), ("other", "Other"),
        ],
        default="check",
    )
    received_at = DateTimeLocalField(
        "Received", format="%Y-%m-%dT%H:%M", validators=[Optional()],
    )
    reference = StringField("Reference (check #, etc.)",
                             validators=[Optional(), Length(max=100)])
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=2000)],
                           render_kw={"rows": 2})
    submit = SubmitField("Record payment")
