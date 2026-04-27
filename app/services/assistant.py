"""Claude assistant service.

- Loads CLAUDE.md from the persistent volume (creates it with sane defaults
  on first read).
- Defines the read-only tool set the assistant can call.
- Sends a chat turn to Claude with prompt-cached system prompt + tool defs.
- Executes any tool_use blocks against the DB and feeds results back.

Tool design philosophy:
- READ-ONLY for v1. The assistant can answer questions but doesn't make
  database changes. Write tools require a propose-confirm UX which we'll
  add when there's appetite.
- Tool results capped to keep token spend low.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import current_app
from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.client import Client
from app.models.job import JOB_STATUS_LABELS, Job
from app.models.property import Property
from app.models.setting import get_setting

ASSISTANT_DEFAULT_MODEL = "claude-opus-4-7"
ASSISTANT_MODELS = [
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
]

DEFAULT_SYSTEM_PROMPT = """\
# Lakewood Original — Assistant prompt

You are the in-app assistant for Jake at Lakewood Original, a solo handyman
business in Cleveland, OH. You help him stay organized, answer questions
about his data, and draft messages.

## How Jake works
- Solo operator. Works mostly Mon–Fri, 8am–5pm. Lunch ~12:00–12:45.
- Service area: Cleveland metro (Cuyahoga, Lake, Lorain, Geauga, Medina, Summit).
- Generic handyman work: repairs, installs, multi-visit jobs are common.
- Jake reads the app on his phone in the truck. Brevity wins.

## Communication
- Be concise. Skip pleasantries.
- For schedules: show date, time, client, address.
- For client lookups: show phone + most recent job.
- For dollar amounts: link to the source row when possible.

## What you can do
You have read-only tools. You can:
- Look up clients, properties, jobs
- Summarize today / this week / overdue work
- Draft email/text bodies (Jake will send from his own email)

## What you cannot do (yet)
- Write to the database. Don't claim to have scheduled, deleted, or marked
  anything. If Jake asks you to do a write, suggest the path: "Tap the +
  button on the bottom bar," etc.
- Send emails or texts on his behalf.

## Customer notes
(Add specifics here as Jake tells you about repeat customers.)

"""


# ---------- system prompt persistence ----------

def _system_prompt_path() -> Path:
    # Stored on the persistent volume so it survives deploys.
    backup_dir: Path = current_app.config["BACKUP_DIR"]
    return backup_dir.parent / "CLAUDE.md"


def load_system_prompt() -> str:
    p = _system_prompt_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(DEFAULT_SYSTEM_PROMPT, encoding="utf-8")
    return p.read_text(encoding="utf-8")


def save_system_prompt(text: str) -> None:
    p = _system_prompt_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ---------- tools ----------

TOOLS = [
    {
        "name": "get_today_summary",
        "description": "Summary of today's schedule + open work counts. Use this when Jake asks 'what's on today?' or for a daily overview.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_jobs",
        "description": "List jobs in a date range, optionally filtered by status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "ISO date YYYY-MM-DD (inclusive). Omit for today."},
                "end_date":   {"type": "string", "description": "ISO date YYYY-MM-DD (inclusive). Omit for start_date+7."},
                "status":     {"type": "string", "enum": ["scheduled", "in_progress", "complete", "canceled"]},
            },
            "required": [],
        },
    },
    {
        "name": "get_job",
        "description": "Full detail of a single job by ID.",
        "input_schema": {
            "type": "object",
            "properties": {"job_id": {"type": "integer"}},
            "required": ["job_id"],
        },
    },
    {
        "name": "search_clients",
        "description": "Fuzzy match clients by name, phone, or email.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "get_client",
        "description": "Full detail of a single client + their properties + recent jobs.",
        "input_schema": {
            "type": "object",
            "properties": {"client_id": {"type": "integer"}},
            "required": ["client_id"],
        },
    },
]


def _job_brief(j: Job) -> dict:
    return {
        "id": j.id,
        "title": j.title,
        "status": j.status,
        "scheduled_date": j.scheduled_date.isoformat() if j.scheduled_date else None,
        "scheduled_time": j.scheduled_time.strftime("%H:%M") if j.scheduled_time else None,
        "client": j.client.name if j.client else None,
        "client_id": j.client_id,
        "address": j.prop.address_line1 if j.prop else None,
    }


def _job_full(j: Job) -> dict:
    out = _job_brief(j)
    out.update({
        "scope": j.scope,
        "notes": j.notes,
        "est_hours": j.est_hours,
        "address_full": j.prop.address_one_line if j.prop else None,
        "visits": [{
            "date": v.scheduled_date.isoformat() if v.scheduled_date else None,
            "duration": v.duration_display,
            "miles": v.miles,
            "notes": v.notes,
        } for v in j.visits[:20]],
        "total_visit_hours": j.total_visit_hours,
        "total_miles": j.total_miles,
    })
    return out


def _client_brief(c: Client) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "phone": c.display_phone or None,
        "email": c.email,
        "property_count": len(c.properties or []),
    }


def execute_tool(name: str, args: dict) -> dict:
    """Run a tool against the DB. Returns a JSON-serializable dict."""
    try:
        if name == "get_today_summary":
            today = date.today()
            today_jobs = db.session.scalars(
                select(Job).options(joinedload(Job.client), joinedload(Job.prop))
                .where(Job.scheduled_date == today, Job.status != "canceled")
                .order_by(Job.scheduled_time.nulls_last())
            ).all()
            in_progress = db.session.scalars(
                select(Job).where(Job.status == "in_progress")
                .options(joinedload(Job.client))
            ).all()
            overdue = db.session.scalars(
                select(Job).where(Job.scheduled_date < today,
                                  Job.status.in_(["scheduled", "in_progress"]))
                .options(joinedload(Job.client))
            ).all()
            return {
                "today": today.isoformat(),
                "today_jobs": [_job_brief(j) for j in today_jobs],
                "in_progress": [_job_brief(j) for j in in_progress],
                "overdue": [_job_brief(j) for j in overdue],
            }

        if name == "list_jobs":
            today = date.today()
            try:
                start = date.fromisoformat(args.get("start_date") or today.isoformat())
            except ValueError:
                start = today
            try:
                end = date.fromisoformat(args.get("end_date") or (start + timedelta(days=7)).isoformat())
            except ValueError:
                end = start + timedelta(days=7)

            stmt = (select(Job)
                    .options(joinedload(Job.client), joinedload(Job.prop))
                    .where(Job.scheduled_date >= start, Job.scheduled_date <= end)
                    .order_by(Job.scheduled_date, Job.scheduled_time.nulls_last())
                    .limit(50))
            status = args.get("status")
            if status:
                stmt = stmt.where(Job.status == status)
            jobs = db.session.scalars(stmt).all()
            return {
                "range": [start.isoformat(), end.isoformat()],
                "count": len(jobs),
                "jobs": [_job_brief(j) for j in jobs],
            }

        if name == "get_job":
            job_id = int(args.get("job_id"))
            j = db.session.get(Job, job_id)
            if j is None:
                return {"error": f"Job {job_id} not found"}
            return _job_full(j)

        if name == "search_clients":
            q = (args.get("query") or "").strip()
            if not q:
                return {"results": []}
            like = f"%{q}%"
            digits = "".join(ch for ch in q if ch.isdigit())
            conds = [Client.name.ilike(like), Client.email.ilike(like)]
            if digits:
                conds.append(Client.phone.ilike(f"%{digits}%"))
            results = db.session.scalars(
                select(Client).where(or_(*conds)).order_by(Client.name).limit(20)
            ).all()
            return {"results": [_client_brief(c) for c in results]}

        if name == "get_client":
            cid = int(args.get("client_id"))
            c = db.session.get(Client, cid)
            if c is None:
                return {"error": f"Client {cid} not found"}
            recent = db.session.scalars(
                select(Job).where(Job.client_id == c.id)
                .order_by(Job.scheduled_date.desc().nulls_last(), Job.created_at.desc())
                .limit(8)
            ).all()
            return {
                **_client_brief(c),
                "notes": c.notes,
                "properties": [{
                    "id": p.id, "label": p.label,
                    "address": p.address_one_line,
                    "county": p.county, "tax_rate_percent": p.tax_rate_percent,
                } for p in c.properties],
                "recent_jobs": [_job_brief(j) for j in recent],
            }

        return {"error": f"Unknown tool: {name}"}
    except Exception as e:
        current_app.logger.exception("Tool %s failed", name)
        return {"error": str(e)}


# ---------- chat ----------

def assistant_enabled() -> bool:
    if get_setting("assistant_enabled", "1") != "1":
        return False
    return bool(current_app.config.get("ANTHROPIC_API_KEY"))


def get_active_model() -> str:
    return (get_setting("assistant_model")
            or current_app.config.get("ANTHROPIC_MODEL")
            or ASSISTANT_DEFAULT_MODEL)


def _client():
    """Return a configured Anthropic client, or raise if no key."""
    import anthropic
    key = current_app.config.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=key)


def chat_once(history: list[dict], user_message: str, max_tool_iterations: int = 5) -> dict:
    """Send a single user message, loop through any tool calls, return the final answer.

    `history` is a list of {role, content} dicts in Anthropic message format
    (each `content` is either a string or a list of content blocks).
    Returns the full assistant reply text + tool calls used.
    """
    client = _client()
    model = get_active_model()
    system_prompt = load_system_prompt()

    messages = list(history)
    messages.append({"role": "user", "content": user_message})

    final_text = ""
    stop_reason = "unknown"
    tool_log: list[dict] = []  # for in-app display ("called list_jobs(...)")

    for _ in range(max_tool_iterations):
        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            system=[{
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }],
            tools=TOOLS,
            messages=messages,
        )
        stop_reason = resp.stop_reason

        tool_uses = []
        text_parts = []
        for block in resp.content:
            t = getattr(block, "type", None)
            if t == "text":
                text_parts.append(block.text)
            elif t == "tool_use":
                tool_uses.append(block)

        # Append the assistant's full response (text + tool_use blocks) to history
        messages.append({
            "role": "assistant",
            "content": [b.model_dump() for b in resp.content],
        })

        if stop_reason != "tool_use" or not tool_uses:
            final_text = "\n\n".join(text_parts).strip()
            break

        # Execute the tools and feed results back as a single user turn
        tool_results = []
        for tu in tool_uses:
            result = execute_tool(tu.name, tu.input or {})
            tool_log.append({"name": tu.name, "input": tu.input})
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": json.dumps(result, default=str),
            })
        messages.append({"role": "user", "content": tool_results})

    return {
        "reply_text": final_text or "(no text response)",
        "model": model,
        "stop_reason": stop_reason,
        "messages": messages,        # full updated history
        "tool_log": tool_log,        # which tools fired this turn
    }
