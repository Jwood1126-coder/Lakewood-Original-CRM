"""Quote forms.

Line items are submitted as parallel arrays (description[], qty[],
unit_price[], taxable[]) so the UI can dynamically add/remove rows with
zero JS framework. Parsed in the route, not here.
"""
from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    DecimalField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class QuoteForm(FlaskForm):
    subject = StringField(
        "Subject", validators=[DataRequired(), Length(max=200)],
        render_kw={"placeholder": "e.g. Bathroom repair estimate", "autofocus": True},
    )
    client_id = SelectField("Client", coerce=int, validators=[DataRequired()], choices=[])
    property_id = SelectField("Property", coerce=int, validators=[DataRequired()], choices=[])

    valid_until = DateField("Valid until", validators=[Optional()])
    tax_rate_override = DecimalField(
        "Tax rate override",
        places=4,
        validators=[Optional(), NumberRange(min=0, max=1)],
        render_kw={"step": "0.0001",
                   "placeholder": "Leave blank to use property rate"},
    )
    message_to_customer = TextAreaField(
        "Message to customer (shown on the quote)",
        validators=[Optional(), Length(max=10000)],
        render_kw={"rows": 3},
    )
    internal_notes = TextAreaField(
        "Internal notes (only you see)",
        validators=[Optional(), Length(max=10000)],
        render_kw={"rows": 2},
    )
    submit = SubmitField("Save quote")
