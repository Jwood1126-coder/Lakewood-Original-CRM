"""Reports — accounting-friendly summaries.

These are designed for the small-business operator who has to:
  - File Ohio sales tax (semi-annual / quarterly / monthly per ORC 5739)
  - Hand a year-end packet to their CPA
  - Track A/R aging for collections
  - See revenue trends month-over-month

Every report is also CSV-exportable.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import Blueprint, Response, render_template, request
from flask_login import login_required
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.invoice import Invoice
from app.models.payment import Payment

bp = Blueprint("reports", __name__, template_folder="../templates/reports")


# ---------- helpers ----------

def _parse_range() -> tuple[date, date, str]:
    """Parse ?from=YYYY-MM-DD&to=YYYY-MM-DD with sensible defaults.

    Default: this month, first day → today.
    """
    today = date.today()
    default_from = today.replace(day=1)
    raw_from = request.args.get("from")
    raw_to = request.args.get("to")
    try:
        d_from = date.fromisoformat(raw_from) if raw_from else default_from
    except ValueError:
        d_from = default_from
    try:
        d_to = date.fromisoformat(raw_to) if raw_to else today
    except ValueError:
        d_to = today
    if d_to < d_from:
        d_to = d_from
    label = f"{d_from.isoformat()} to {d_to.isoformat()}"
    return d_from, d_to, label


def _range_presets(today: date) -> dict:
    """Compute common date-range presets for the picker UI."""
    this_month_start = today.replace(day=1)
    last_month_end = this_month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    ytd_start = today.replace(month=1, day=1)
    last_year_start = today.replace(year=today.year - 1, month=1, day=1)
    last_year_end = today.replace(year=today.year - 1, month=12, day=31)
    return {
        "today": today,
        "this_month_start": this_month_start,
        "last_month_start": last_month_start,
        "last_month_end": last_month_end,
        "ytd_start": ytd_start,
        "last_year_start": last_year_start,
        "last_year_end": last_year_end,
    }


def _month_buckets(d_from: date, d_to: date) -> list[tuple[date, date, str]]:
    """Yield (month_start, month_end_exclusive, label) for each month overlapping the range."""
    months = []
    cur = d_from.replace(day=1)
    while cur <= d_to:
        if cur.month == 12:
            nxt = cur.replace(year=cur.year + 1, month=1)
        else:
            nxt = cur.replace(month=cur.month + 1)
        months.append((cur, nxt, cur.strftime("%Y-%m")))
        cur = nxt
    return months


# ---------- index ----------

@bp.route("/")
@login_required
def index():
    return render_template("reports/index.html")


# ---------- Sales tax ----------

@bp.route("/sales-tax")
@login_required
def sales_tax():
    """Sales tax collected, by month, for invoices marked sent/partial/paid
    in the date range. Drives Ohio sales tax filing.

    Filters out draft + void invoices (those didn't actually transact).
    Uses invoice.sent_at as the recognition date — when the customer was
    billed. (You could argue paid_at instead; sent_at is the conventional
    accrual-basis choice.)
    """
    d_from, d_to, label = _parse_range()

    invoices = db.session.scalars(
        select(Invoice).options(joinedload(Invoice.client), joinedload(Invoice.prop))
        .where(Invoice.status.in_(["sent", "partial", "paid"]),
               Invoice.sent_at.is_not(None),
               func.date(Invoice.sent_at) >= d_from,
               func.date(Invoice.sent_at) <= d_to)
        .order_by(Invoice.sent_at)
    ).all()

    rows = []
    monthly = {}  # 'YYYY-MM' -> {'taxable_cents': ..., 'tax_cents': ..., 'count': ...}
    for inv in invoices:
        month = inv.sent_at.strftime("%Y-%m")
        bucket = monthly.setdefault(month, {
            "taxable_cents": 0, "tax_cents": 0, "subtotal_cents": 0, "count": 0,
        })
        bucket["taxable_cents"] += inv.taxable_subtotal_cents
        bucket["subtotal_cents"] += inv.subtotal_cents
        bucket["tax_cents"] += inv.tax_cents
        bucket["count"] += 1
        rows.append(inv)

    monthly_sorted = sorted(monthly.items())

    grand = {
        "subtotal_cents": sum(m["subtotal_cents"] for _, m in monthly_sorted),
        "taxable_cents":  sum(m["taxable_cents"]  for _, m in monthly_sorted),
        "tax_cents":      sum(m["tax_cents"]      for _, m in monthly_sorted),
        "count":          sum(m["count"]          for _, m in monthly_sorted),
    }

    if request.args.get("format") == "csv":
        return _sales_tax_csv(rows, label)

    return render_template(
        "reports/sales_tax.html",
        d_from=d_from, d_to=d_to, label=label,
        monthly=monthly_sorted, grand=grand, invoices=rows,
        presets=_range_presets(date.today()),
    )


def _sales_tax_csv(invoices, label: str) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Invoice #", "Sent date", "Client", "Property county",
                "Subtotal", "Taxable subtotal", "Tax rate", "Tax collected", "Total"])
    for inv in invoices:
        w.writerow([
            f"#{inv.number}",
            inv.sent_at.date().isoformat() if inv.sent_at else "",
            inv.client.name if inv.client else "",
            inv.prop.county if inv.prop else "",
            f"{inv.subtotal_cents/100:.2f}",
            f"{inv.taxable_subtotal_cents/100:.2f}",
            f"{inv.effective_tax_rate*100:.4f}%",
            f"{inv.tax_cents/100:.2f}",
            f"{inv.total_cents/100:.2f}",
        ])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="sales_tax_{label.replace(" ", "_")}.csv"'},
    )


# ---------- Revenue ----------

@bp.route("/revenue")
@login_required
def revenue():
    """Revenue (cash basis: based on payments received in the range).

    Why cash basis: matches what hits your bank account. For accrual basis
    you'd group by invoice.sent_at — call it 'billings' rather than revenue.
    Showing both columns side-by-side.
    """
    d_from, d_to, label = _parse_range()

    # Cash basis: payments received in range
    payments = db.session.scalars(
        select(Payment).options(joinedload(Payment.invoice).joinedload(Invoice.client))
        .where(func.date(Payment.received_at) >= d_from,
               func.date(Payment.received_at) <= d_to)
        .order_by(Payment.received_at)
    ).all()

    # Accrual basis: invoices sent in range
    invoices_billed = db.session.scalars(
        select(Invoice).options(joinedload(Invoice.client))
        .where(Invoice.status.in_(["sent", "partial", "paid"]),
               Invoice.sent_at.is_not(None),
               func.date(Invoice.sent_at) >= d_from,
               func.date(Invoice.sent_at) <= d_to)
    ).all()

    monthly = {}
    for m_start, _, label_m in _month_buckets(d_from, d_to):
        monthly[label_m] = {"received_cents": 0, "billed_cents": 0, "payment_count": 0}

    for p in payments:
        m = p.received_at.strftime("%Y-%m")
        if m in monthly:
            monthly[m]["received_cents"] += p.amount_cents
            monthly[m]["payment_count"] += 1

    for inv in invoices_billed:
        m = inv.sent_at.strftime("%Y-%m")
        if m in monthly:
            monthly[m]["billed_cents"] += inv.total_cents

    monthly_sorted = sorted(monthly.items())
    grand = {
        "received_cents": sum(m["received_cents"] for _, m in monthly_sorted),
        "billed_cents":   sum(m["billed_cents"] for _, m in monthly_sorted),
        "payment_count":  sum(m["payment_count"] for _, m in monthly_sorted),
    }

    # Top clients by received in range
    top_clients = {}
    for p in payments:
        if p.invoice and p.invoice.client:
            cid = p.invoice.client.id
            tc = top_clients.setdefault(cid, {
                "name": p.invoice.client.name, "received_cents": 0,
            })
            tc["received_cents"] += p.amount_cents
    top_clients_list = sorted(top_clients.values(),
                               key=lambda x: x["received_cents"], reverse=True)[:10]

    if request.args.get("format") == "csv":
        return _revenue_csv(monthly_sorted, label)

    return render_template(
        "reports/revenue.html",
        d_from=d_from, d_to=d_to, label=label,
        monthly=monthly_sorted, grand=grand,
        top_clients=top_clients_list,
        presets=_range_presets(date.today()),
    )


def _revenue_csv(monthly_sorted, label: str) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Month", "Billed", "Received (cash)", "Payment count"])
    for m, b in monthly_sorted:
        w.writerow([m, f"{b['billed_cents']/100:.2f}",
                    f"{b['received_cents']/100:.2f}", b["payment_count"]])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="revenue_{label.replace(" ", "_")}.csv"'},
    )


# ---------- A/R aging ----------

@bp.route("/ar-aging")
@login_required
def ar_aging():
    """Accounts Receivable aging — open invoice balances in standard buckets.

    Buckets: current (not yet due), 1-30, 31-60, 61-90, 90+.
    Standard small-business format used by every accountant.
    """
    today = date.today()
    open_invoices = db.session.scalars(
        select(Invoice).options(joinedload(Invoice.client))
        .where(Invoice.status.in_(["sent", "partial"]))
        .order_by(Invoice.due_date.nulls_last())
    ).all()

    buckets = {
        "current": {"label": "Current (not yet due)", "cents": 0, "invoices": []},
        "1_30":    {"label": "1–30 days",  "cents": 0, "invoices": []},
        "31_60":   {"label": "31–60 days", "cents": 0, "invoices": []},
        "61_90":   {"label": "61–90 days", "cents": 0, "invoices": []},
        "over_90": {"label": "90+ days",   "cents": 0, "invoices": []},
    }
    by_client = {}

    for inv in open_invoices:
        bal = inv.balance_cents
        if bal <= 0:
            continue

        if not inv.due_date or inv.due_date >= today:
            bucket_key = "current"
            days = 0
        else:
            days = (today - inv.due_date).days
            if days <= 30:
                bucket_key = "1_30"
            elif days <= 60:
                bucket_key = "31_60"
            elif days <= 90:
                bucket_key = "61_90"
            else:
                bucket_key = "over_90"

        buckets[bucket_key]["cents"] += bal
        buckets[bucket_key]["invoices"].append({"inv": inv, "days_past_due": days})

        if inv.client:
            cb = by_client.setdefault(inv.client.id, {
                "client": inv.client, "current": 0, "1_30": 0,
                "31_60": 0, "61_90": 0, "over_90": 0, "total": 0,
            })
            cb[bucket_key] += bal
            cb["total"] += bal

    grand_total = sum(b["cents"] for b in buckets.values())
    by_client_sorted = sorted(by_client.values(), key=lambda x: x["total"], reverse=True)

    return render_template(
        "reports/ar_aging.html",
        today=today, buckets=buckets, grand_total=grand_total,
        by_client=by_client_sorted,
    )


# ---------- Year-end bundle ----------

@bp.route("/year-end")
@login_required
def year_end():
    """Year-end summary: links to all the reports for the current and previous year."""
    today = date.today()
    return render_template("reports/year_end.html",
                           current_year=today.year,
                           previous_year=today.year - 1)
