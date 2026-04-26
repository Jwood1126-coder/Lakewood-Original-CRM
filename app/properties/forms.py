"""Property forms."""
from __future__ import annotations

from decimal import Decimal

from flask_wtf import FlaskForm
from wtforms import DecimalField, StringField, SubmitField, TextAreaField
from wtforms.validators import InputRequired, Length, NumberRange, Optional, Regexp


class PropertyForm(FlaskForm):
    label = StringField(
        "Label",
        validators=[Length(min=1, max=100)],
        default="Home",
        render_kw={"placeholder": "Home, Rental #1, etc.", "autofocus": True},
    )
    address_line1 = StringField(
        "Address line 1",
        validators=[InputRequired(), Length(max=200)],
        render_kw={"placeholder": "123 Main St", "autocomplete": "address-line1"},
    )
    address_line2 = StringField(
        "Address line 2",
        validators=[Optional(), Length(max=200)],
        render_kw={"placeholder": "Apt 2 (optional)", "autocomplete": "address-line2"},
    )
    city = StringField(
        "City",
        validators=[InputRequired(), Length(max=100)],
        render_kw={"autocomplete": "address-level2"},
    )
    state = StringField(
        "State",
        validators=[InputRequired(), Length(min=2, max=2)],
        default="OH",
        render_kw={"autocomplete": "address-level1", "maxlength": "2"},
    )
    zip_code = StringField(
        "ZIP",
        validators=[InputRequired(), Regexp(r"^\d{5}(-\d{4})?$",
                                            message="5-digit or ZIP+4 only")],
        render_kw={"autocomplete": "postal-code", "inputmode": "numeric"},
    )
    county = StringField(
        "County",
        validators=[Optional(), Length(max=60)],
        render_kw={"placeholder": "Auto-filled from ZIP if blank"},
    )
    tax_rate = DecimalField(
        "Tax rate",
        places=4,
        validators=[Optional(), NumberRange(min=0, max=Decimal("0.20"))],
        render_kw={
            "step": "0.0001",
            "placeholder": "Auto from county; e.g. 0.08 for 8%",
        },
    )
    notes = TextAreaField(
        "Notes",
        validators=[Optional(), Length(max=10000)],
        render_kw={
            "rows": 3,
            "placeholder": "Access codes, gate codes, dog warnings, etc.",
        },
    )
    submit = SubmitField("Save")
