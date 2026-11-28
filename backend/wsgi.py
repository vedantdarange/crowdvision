"""wsgi.py — WSGI entry point for Gunicorn and the Flask dev server.

Usage:
  Development:  flask run  (or python wsgi.py)
  Demo:         gunicorn -w 1 --threads 100 wsgi:app
  SocketIO dev: python wsgi.py  (runs with socketio.run for WebSocket support)
"""
from __future__ import annotations

import os

from app import create_app
from app.extensions import socketio

# When `python wsgi.py` runs directly (especially on Windows where
# multiprocessing uses `spawn`), worker child processes execute this module
# with `__name__ == "__mp_main__"`. Skip creating another Flask app inside
# workers while keeping `app` exposed for `__main__`, `flask --app wsgi:app`,
# and `gunicorn wsgi:app`.
app = create_app() if __name__ != "__mp_main__" else None

if __name__ == "__main__":
    assert app is not None
    is_debug = bool(app.config.get("DEBUG", False))
    port = int(os.environ.get("PORT", "5000"))
    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=is_debug,
        use_reloader=is_debug,
        allow_unsafe_werkzeug=not is_debug,
    )
