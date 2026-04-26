"""Photo handling — upload, resize, store, delete.

Always resize on upload. Phone shots are 3-5MB each; resized to 1600px
long-edge they're ~250-500KB and just as useful for documentation.
The original is NOT kept — durability beats fidelity here.
"""
from __future__ import annotations

import secrets
from io import BytesIO
from pathlib import Path

from flask import current_app
from PIL import Image, ImageOps
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models.photo import Photo

# Max long-edge in pixels for stored photos
MAX_DIM = 1600
JPEG_QUALITY = 85
ALLOWED_MIMES = {"image/jpeg", "image/png", "image/heic", "image/heif", "image/webp"}


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def save_photo_for_property(property_id: int, file: FileStorage) -> Photo:
    """Resize and store a photo for a Property. Commits the row to the DB.

    Raises ValueError on invalid mimetype or unreadable image.
    """
    if not file or not file.filename:
        raise ValueError("No file provided")
    if file.mimetype not in ALLOWED_MIMES:
        raise ValueError(f"Unsupported file type: {file.mimetype}")

    photo_root: Path = current_app.config["PHOTO_DIR"]
    subdir = Path("properties") / str(property_id)
    _ensure_dir(photo_root / subdir)

    # Open + auto-rotate per EXIF + convert to RGB for JPEG saving
    try:
        img = Image.open(file.stream)
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
    except Exception as e:
        raise ValueError(f"Could not read image: {e}") from e

    img.thumbnail((MAX_DIM, MAX_DIM), Image.Resampling.LANCZOS)
    width, height = img.size

    # Save as JPEG; original filename only used for display
    token = secrets.token_urlsafe(8)
    filename = f"{token}.jpg"
    rel_path = (subdir / filename).as_posix()
    abs_path = photo_root / rel_path

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    abs_path.write_bytes(buf.getvalue())

    photo = Photo(
        rel_path=rel_path,
        original_filename=file.filename,
        mimetype="image/jpeg",
        bytes=abs_path.stat().st_size,
        width=width,
        height=height,
        property_id=property_id,
    )
    db.session.add(photo)
    db.session.commit()
    return photo


def delete_photo(photo: Photo) -> None:
    """Remove the file and the DB row."""
    photo_root: Path = current_app.config["PHOTO_DIR"]
    abs_path = photo_root / photo.rel_path
    try:
        abs_path.unlink(missing_ok=True)
    except OSError as e:
        current_app.logger.warning("Could not unlink %s: %s", abs_path, e)
    db.session.delete(photo)
    db.session.commit()
