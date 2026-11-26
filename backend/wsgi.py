"""wsgi.py — WSGI entry point for Gunicorn and the Flask dev server.

Usage:
  Development:  flask run  (or python wsgi.py)
  Demo:         gunicorn -w 1 --threads 100 wsgi:app
  SocketIO dev: python wsgi.py  (runs with socketio.run for WebSocket support)
"""
from __future__ import annotations

from app import create_app
from app.extensions import socketio

app = create_app()

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
