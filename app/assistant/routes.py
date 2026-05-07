"""Assistant chat routes.

UI is full-page chat (better on phone). One conversation per visit by default;
user can start a new conversation anytime.

For v1 we don't stream — we synchronously call Claude (which itself loops
through tool use) and render the full reply when ready. Streaming SSE can
be added later but isn't necessary for the small replies this surfaces.
"""
from __future__ import annotations

import json
from datetime import datetime

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required
from sqlalchemy import select

from app.extensions import db
from app.models.conversation import Conversation, Message
from app.services.assistant import (
    assistant_enabled,
    chat_once,
    get_active_model,
)

bp = Blueprint("assistant", __name__, template_folder="../templates/assistant")


def _conversation_to_history(conv: Conversation) -> list[dict]:
    """Build the Anthropic message history for a saved Conversation.

    For assistant turns that involved tool use, `tool_calls_json` stores
    the *full* sequence of message dicts (asst → user-tool-result → asst).
    Those are individual messages in the Anthropic format, so we extend
    history with them rather than nest them as content blocks of a single
    assistant message (which produced the 400 'content.0.type: Field
    required' error).
    """
    history = []
    for m in conv.messages:
        if m.role == "user":
            history.append({"role": "user", "content": m.content})
        elif m.role == "assistant":
            if m.tool_calls_json:
                try:
                    blocks = json.loads(m.tool_calls_json)
                    if isinstance(blocks, list) and blocks:
                        history.extend(blocks)
                        continue
                except Exception:
                    pass
            history.append({"role": "assistant", "content": m.content})
    return history


@bp.route("/")
@login_required
def index():
    """List recent conversations."""
    convs = db.session.scalars(
        select(Conversation).order_by(Conversation.updated_at.desc()).limit(30)
    ).all()
    return render_template(
        "assistant/index.html",
        conversations=convs,
        enabled=assistant_enabled(),
        model=get_active_model(),
    )


@bp.route("/new", methods=["POST"])
@login_required
def new_conversation():
    conv = Conversation(title=None)
    db.session.add(conv)
    db.session.commit()
    return redirect(url_for("assistant.view", conversation_id=conv.id))


@bp.route("/c/<int:conversation_id>")
@login_required
def view(conversation_id: int):
    conv = db.session.get(Conversation, conversation_id) or abort(404)
    return render_template(
        "assistant/conversation.html",
        conv=conv,
        enabled=assistant_enabled(),
        model=get_active_model(),
    )


@bp.route("/c/<int:conversation_id>/send", methods=["POST"])
@login_required
def send(conversation_id: int):
    conv = db.session.get(Conversation, conversation_id) or abort(404)
    text = (request.form.get("message") or "").strip()
    if not text:
        flash("Empty message.", "error")
        return redirect(url_for("assistant.view", conversation_id=conv.id))

    if not assistant_enabled():
        flash("Assistant is disabled or no Anthropic API key is configured. "
              "Set it in Railway env vars and enable in Settings → Assistant.",
              "error")
        return redirect(url_for("assistant.view", conversation_id=conv.id))

    # Persist user message immediately
    user_msg = Message(conversation_id=conv.id, role="user", content=text)
    db.session.add(user_msg)
    db.session.flush()

    history = _conversation_to_history(conv)

    try:
        result = chat_once(history, text)
    except Exception as e:
        current_app.logger.exception("Assistant call failed")
        # Save an assistant message describing the error so the chat shows it
        err_msg = Message(
            conversation_id=conv.id, role="assistant",
            content=f"⚠ Assistant error: {e}",
        )
        db.session.add(err_msg)
        db.session.commit()
        return redirect(url_for("assistant.view", conversation_id=conv.id))

    # Save full assistant response (text + tool calls). Append all assistant +
    # tool_result blocks from the new history past what we already had stored.
    new_blocks = result["messages"][len(history) + 1:]  # skip stored history + user msg

    # Collapse: the assistant turn(s) and any tool_result turn(s).
    # We persist one "assistant" Message with the final text, and store the
    # full block sequence for replay/audit.
    db.session.add(Message(
        conversation_id=conv.id,
        role="assistant",
        content=result["reply_text"],
        tool_calls_json=json.dumps(new_blocks, default=str),
    ))

    # Auto-title the conversation from the first user message if not set yet
    if not conv.title:
        conv.title = (text[:80] + "…") if len(text) > 80 else text
    conv.updated_at = datetime.utcnow()
    db.session.commit()

    return redirect(url_for("assistant.view", conversation_id=conv.id))


@bp.route("/c/<int:conversation_id>/delete", methods=["POST"])
@login_required
def delete(conversation_id: int):
    conv = db.session.get(Conversation, conversation_id) or abort(404)
    db.session.delete(conv)
    db.session.commit()
    flash("Conversation deleted.", "info")
    return redirect(url_for("assistant.index"))
