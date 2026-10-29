"""gunicorn entry point: `gunicorn --config deploy/gunicorn.conf.py wsgi:app`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.app import app  # noqa: E402

__all__ = ["app"]
