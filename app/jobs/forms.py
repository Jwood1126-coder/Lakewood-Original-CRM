"""Job + Visit forms."""
from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    DecimalField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
    TimeField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class JobForm(FlaskForm):
    """Used for both create and edit. Property dropdown is populated dynamically
    from the chosen client's properties."""

    title = StringField(
        "Job title",
        validators=[DataRequired(), Length(max=200)],
        render_kw={"placeholder": "e.g. Replace kitchen faucet", "autofocus": True},
    )
    client_id = SelectField(
        "Client", coerce=int, validators=[DataRequired()], choices=[]
    )
    property_id = SelectField(
        "Property", coerce=int, validators=[DataRequired()], choices=[]
    )
    scope = TextAreaField(
        "Scope of work",
        validators=[Optional(), Length(max=10000)],
        render_kw={"rows": 4, "placeholder": "What needs doing"},
    )
    scheduled_date = DateField(
        "Date", validators=[Optional()], render_kw={"inputmode": "numeric"}
    )
    scheduled_time = TimeField(
        "Start time", validators=[Optional()], render_kw={"step": "300"}
    )
    est_hours = DecimalField(
        "Estimated hours",
        places=1,
        validators=[Optional(), NumberRange(min=0, max=100)],
        render_kw={"step": "0.5", "inputmode": "decimal"},
    )
    notes = TextAreaField(
        "Internal notes",
        validators=[Optional(), Length(max=10000)],
        render_kw={"rows": 3, "placeholder": "Access codes, parts to bring, etc."},
    )
    submit = SubmitField("Save")


class VisitForm(FlaskForm):
    """Manual entry of a past visit (after-the-fact logging)."""

    scheduled_date = DateField("Date", validators=[DataRequired()])
    arrived_at_time = TimeField(
        "Arrived",
        validators=[Optional()],
        render_kw={"step": "300"},
    )
    departed_at_time = TimeField(
        "Departed",
        validators=[Optional()],
        render_kw={"step": "300"},
    )
    miles = IntegerField(
        "Miles driven",
        validators=[Optional(), NumberRange(min=0, max=1000)],
        render_kw={"inputmode": "numeric"},
    )
    notes = TextAreaField(
        "Notes",
        validators=[Optional(), Length(max=10000)],
        render_kw={"rows": 3},
    )
    submit = SubmitField("Save visit")
