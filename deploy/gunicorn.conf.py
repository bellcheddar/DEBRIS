"""gunicorn config for DEBRIS. Adapted from AlphaFraud/deploy/gunicorn.conf.py.

The app is read-only: it reads a static JSON bundle and a read-only SQLite, so sync
workers are right and no worker holds state. Three workers is plenty for a page the
workshop reads from one shared screen, and leaves the droplet to its other apps.
"""
import os

bind = os.environ.get("BIND_ADDR", "127.0.0.1:8014")
workers = int(os.environ.get("WEB_WORKERS", "3"))
threads = 2
worker_class = "gthread"
timeout = 60
graceful_timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = "info"
# A weekly data swap replaces the SQLite file and the JSON bundles underneath a
# running worker; both are opened per request, so nothing needs a restart.
preload_app = False
