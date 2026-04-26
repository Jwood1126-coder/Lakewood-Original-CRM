"""Run a backup right now (manual / on-demand). Usage: python -m scripts.run_backup"""
from __future__ import annotations

import json
import sys

from app import create_app
from app.services.backup import run_backup


def main():
    app = create_app()
    with app.app_context():
        result = run_backup()
        print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
