"""Client forms."""
from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, TelField, TextAreaField
from wtforms.validators import Email, Length, Optional


class ClientForm(FlaskForm):
    name = StringField(
        "Name",
        validators=[Length(min=1, max=200)],
        render_kw={"autofocus": True, "placeholder": "Mrs. Anderson / Smith Rentals"},
    )
    phone = TelField(
        "Phone",
        validators=[Optional(), Length(max=40)],
        render_kw={"placeholder": "(555) 555-5555", "inputmode": "tel"},
    )
    email = StringField(
        "Email",
        validators=[Optional(), Email(), Length(max=255)],
        render_kw={"placeholder": "optional", "inputmode": "email"},
    )
    notes = TextAreaField(
        "Notes",
        validators=[Optional(), Length(max=10000)],
        render_kw={
            "rows": 4,
            "placeholder": "Anything worth remembering — payment habits, "
                           "access notes, etc.",
        },
    )
    submit = SubmitField("Save")
