"""tests/unit/test_realtime.py — Unit tests for enforce_session_freshness."""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture()
def clean_sessions():
    """Clear and restore the global sessions dict around each test."""
    from app.realtime import connect as rt

    original = dict(rt.sessions)
    rt.sessions.clear()
    yield rt.sessions
    rt.sessions.clear()
    rt.sessions.update(original)


class TestEnforceSessionFreshness:
    def test_expired_token_disconnects(self, app, clean_sessions, fake_clock):
        from app.realtime import connect as rt

        fake_clock.set(1000.0)
        clean_sessions["sid-expired"] = {
            "user_id": 1,
            "role": "police",
            "token_exp": 500.0,
        }

        emitted: list = []
        disconnected: list = []
        left_rooms: list = []

        with app.app_context():
            with (
                patch.object(rt.socketio, "emit", side_effect=lambda *a, **kw: emitted.append(a)),
                patch("app.realtime.connect._disconnect_safe", side_effect=lambda sid: disconnected.append(sid)),
                patch("app.realtime.connect._leave_room_safe", side_effect=lambda sid, rm: left_rooms.append((sid, rm))),
            ):
                rt.enforce_session_freshness(fake_clock.utcnow())

        assert "sid-expired" not in clean_sessions
        assert any(e[0] == "auth:expired" for e in emitted)
        assert "sid-expired" in disconnected
        assert ("sid-expired", "role:police") in left_rooms

    def test_valid_session_untouched(self, app, clean_sessions, fake_clock, make_user):
        from app.realtime import connect as rt

        fake_clock.set(1000.0)
        police_user = make_user(email="fresh_police@test.local", role="police")
        clean_sessions["sid-valid"] = {
            "user_id": police_user.id,
            "role": "police",
            "token_exp": 9999.0,
        }

        with app.app_context():
            with (
                patch.object(rt.socketio, "emit") as mock_emit,
                patch("app.realtime.connect._disconnect_safe") as mock_disc,
                patch("app.realtime.connect._leave_room_safe"),
            ):
                rt.enforce_session_freshness(fake_clock.utcnow())
                mock_disc.assert_not_called()
                mock_emit.assert_not_called()

        assert "sid-valid" in clean_sessions

    def test_disabled_user_disconnects(self, app, clean_sessions, fake_clock, make_user):
        from app.extensions import db
        from app.models.models import User
        from app.realtime import connect as rt

        fake_clock.set(1000.0)
        user = make_user(email="disable_sock@test.local", role="police")
        with app.app_context():
            u = db.session.get(User, user.id)
            assert u is not None
            u.is_active = False
            db.session.commit()

        clean_sessions["sid-disabled"] = {
            "user_id": user.id,
            "role": "police",
            "token_exp": 9999.0,
        }

        disconnected: list = []
        with app.app_context():
            with (
                patch.object(rt.socketio, "emit"),
                patch("app.realtime.connect._disconnect_safe", side_effect=lambda sid: disconnected.append(sid)),
                patch("app.realtime.connect._leave_room_safe"),
            ):
                rt.enforce_session_freshness(fake_clock.utcnow())

        assert "sid-disabled" not in clean_sessions
        assert "sid-disabled" in disconnected

    def test_demoted_police_disconnects(self, app, clean_sessions, fake_clock, make_user):
        from app.extensions import db
        from app.models.models import User
        from app.realtime import connect as rt

        fake_clock.set(1000.0)
        user = make_user(email="demote_sock@test.local", role="police")
        with app.app_context():
            u = db.session.get(User, user.id)
            assert u is not None
            u.role = "citizen"
            db.session.commit()

        clean_sessions["sid-demoted"] = {
            "user_id": user.id,
            "role": "police",
            "token_exp": 9999.0,
        }

        disconnected: list = []
        with app.app_context():
            with (
                patch.object(rt.socketio, "emit"),
                patch("app.realtime.connect._disconnect_safe", side_effect=lambda sid: disconnected.append(sid)),
                patch("app.realtime.connect._leave_room_safe"),
            ):
                rt.enforce_session_freshness(fake_clock.utcnow())

        assert "sid-demoted" not in clean_sessions
        assert "sid-demoted" in disconnected

    def test_anonymous_session_untouched(self, app, clean_sessions, fake_clock):
        from app.realtime import connect as rt

        fake_clock.set(1000.0)
        clean_sessions["sid-anon"] = {
            "user_id": None,
            "role": None,
            "token_exp": None,
        }

        with app.app_context():
            with (
                patch.object(rt.socketio, "emit"),
                patch("app.realtime.connect._disconnect_safe") as mock_disc,
                patch("app.realtime.connect._leave_room_safe"),
            ):
                rt.enforce_session_freshness(fake_clock.utcnow())
                mock_disc.assert_not_called()

        assert "sid-anon" in clean_sessions
