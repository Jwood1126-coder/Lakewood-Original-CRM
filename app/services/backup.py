"""Nightly backup: SQLite snapshot + photos tarball, optional upload to B2.

Strategy:
1. `sqlite3 backup` to a temp file (consistent snapshot, no app downtime)
2. tar.gz the snapshot + photos folder + CLAUDE.md (when it exists)
3. Upload to Backblaze B2 if credentials present
4. Prune local backups older than 7 days (cloud retention is handled by B2 lifecycle)

Stays robust if B2 isn't configured — local backups still happen.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tarfile
from datetime import datetime, timedelta
from pathlib import Path

from flask import current_app


def _is_sqlite_url(uri: str) -> bool:
    return uri.startswith("sqlite:")


def _sqlite_path(uri: str) -> Path:
    """Convert sqlalchemy URI 'sqlite:///path' to a Path."""
    # 'sqlite:///./data/app.db' -> './data/app.db'
    # 'sqlite:////abs/path.db'  -> '/abs/path.db'
    after = uri.split("sqlite:///", 1)[1]
    return Path(after).resolve()


def run_backup() -> dict:
    """Take a backup. Returns a small dict with what happened (for logging)."""
    app = current_app._get_current_object()
    log = app.logger

    db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if not _is_sqlite_url(db_uri):
        log.warning("Backup skipped: not a SQLite database (%s)", db_uri)
        return {"status": "skipped", "reason": "not-sqlite"}

    db_path = _sqlite_path(db_uri)
    if not db_path.exists():
        log.warning("Backup skipped: DB not yet created (%s)", db_path)
        return {"status": "skipped", "reason": "no-db"}

    backup_dir: Path = app.config["BACKUP_DIR"]
    backup_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")
    snap_path = backup_dir / f"app-{stamp}.db"
    archive_path = backup_dir / f"snapshot-{stamp}.tar.gz"

    # Step 1: consistent SQLite snapshot via .backup()
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(snap_path))
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()
    log.info("DB snapshot taken: %s (%d bytes)", snap_path, snap_path.stat().st_size)

    # Step 2: tarball snapshot + photos + CLAUDE.md
    photo_dir: Path = app.config["PHOTO_DIR"]
    project_root = Path(__file__).resolve().parent.parent.parent
    claude_md = project_root / "CLAUDE.md"

    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(snap_path, arcname=f"app-{stamp}.db")
        if photo_dir.exists():
            tar.add(photo_dir, arcname="photos")
        if claude_md.exists():
            tar.add(claude_md, arcname="CLAUDE.md")

    snap_path.unlink(missing_ok=True)  # snapshot is in the tarball now
    log.info("Backup tarball: %s (%d bytes)",
             archive_path, archive_path.stat().st_size)

    # Step 3: optional B2 upload
    uploaded = _upload_to_b2(archive_path, app)

    # Step 4: prune local backups older than 7 days
    pruned = _prune_local(backup_dir, days=7)

    return {
        "status": "ok",
        "archive": str(archive_path),
        "size_bytes": archive_path.stat().st_size,
        "uploaded_to_b2": uploaded,
        "pruned": pruned,
    }


def _upload_to_b2(path: Path, app) -> bool:
    """Upload via S3-compatible API. Returns True on success, False if not configured."""
    if not all([
        app.config.get("B2_ENDPOINT_URL"),
        app.config.get("B2_KEY_ID"),
        app.config.get("B2_APPLICATION_KEY"),
        app.config.get("B2_BUCKET"),
    ]):
        app.logger.info("B2 not configured; backup stays local only")
        return False

    try:
        import boto3
    except ImportError:
        app.logger.warning("boto3 not installed; cannot upload backup")
        return False

    s3 = boto3.client(
        "s3",
        endpoint_url=app.config["B2_ENDPOINT_URL"],
        aws_access_key_id=app.config["B2_KEY_ID"],
        aws_secret_access_key=app.config["B2_APPLICATION_KEY"],
    )
    key = f"backups/{path.name}"
    try:
        s3.upload_file(str(path), app.config["B2_BUCKET"], key)
        app.logger.info("Uploaded backup to B2: s3://%s/%s",
                        app.config["B2_BUCKET"], key)
        return True
    except Exception as e:
        app.logger.exception("B2 upload failed: %s", e)
        return False


def _prune_local(backup_dir: Path, days: int) -> int:
    cutoff = datetime.utcnow() - timedelta(days=days)
    pruned = 0
    for p in backup_dir.glob("snapshot-*.tar.gz"):
        try:
            mtime = datetime.utcfromtimestamp(p.stat().st_mtime)
            if mtime < cutoff:
                p.unlink()
                pruned += 1
        except OSError:
            pass
    return pruned
