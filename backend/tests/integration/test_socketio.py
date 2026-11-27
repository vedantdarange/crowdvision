"""tests/integration/test_socketio.py — Socket.IO connect/rooms/hello/auth:expired tests."""
from __future__ import annotations

import pytest


@pytest.fixture()
def admin(make_user, clean_db):
    return make_user(name="Admin", email="admin_sio@test.local", role="admin")


@pytest.fixture()
def police(make_user, clean_db):
    return make_user(name="Police", email="police_sio@test.local", role="police")


@pytest.fixture()
def citizen(make_user, clean_db):
    return make_user(name="Citizen", email="citizen_sio@test.local", role="citizen")


def _sio_client(app, token: str | None = None):
    from flask_socketio import SocketIOTestClient
    from app.extensions import socketio

    if token is None:
        return SocketIOTestClient(app, socketio)
    return SocketIOTestClient(app, socketio, auth={"token": token})


def _ns_sid(client) -> str:
    from app.extensions import socketio

    return socketio.server.manager.sid_from_eio_sid(client.eio_sid, "/")


def _rooms_for(client) -> set[str]:
    from app.extensions import socketio

    sid = _ns_sid(client)
    return set(socketio.server.rooms(sid, namespace="/")) if sid else set()


class TestSocketIOConnect:
    def test_anonymous_connect_rooms_and_hello(self, app, clean_db):
        client = _sio_client(app)
        assert client.is_connected()
        rooms = _rooms_for(client)
        assert "public" in rooms
        assert "role:police" not in rooms
        assert "role:admin" not in rooms

        received = client.get_received()
        assert all(e["name"] != "auth:expired" for e in received)
        hello_events = [e for e in received if e["name"] == "hello"]
        assert len(hello_events) == 1
        payload = hello_events[0]["args"][0]
        assert payload["role"] is None
        assert "server_time" in payload
        assert payload["contract_version"] == "1.1.0"
        client.disconnect()

    def test_valid_citizen_connect_rooms_and_hello(self, app, clean_db, citizen, token_for):
        client = _sio_client(app, token_for(citizen.id, role="citizen"))
        assert client.is_connected()
        rooms = _rooms_for(client)
        assert "public" in rooms
        assert f"user:{citizen.id}" in rooms
        assert "role:police" not in rooms
        assert "role:admin" not in rooms

        hello_events = [e for e in client.get_received() if e["name"] == "hello"]
        assert hello_events[0]["args"][0]["role"] == "citizen"
        client.disconnect()

    def test_valid_police_connect_rooms_and_hello(self, app, clean_db, police, token_for):
        client = _sio_client(app, token_for(police.id, role="police"))
        assert client.is_connected()
        rooms = _rooms_for(client)
        assert {"public", f"user:{police.id}", "role:police"}.issubset(rooms)
        assert "role:admin" not in rooms

        hello_events = [e for e in client.get_received() if e["name"] == "hello"]
        assert hello_events[0]["args"][0]["role"] == "police"
        client.disconnect()

    def test_valid_admin_connect_rooms_and_hello(self, app, clean_db, admin, token_for):
        client = _sio_client(app, token_for(admin.id, role="admin"))
        assert client.is_connected()
        rooms = _rooms_for(client)
        assert {"public", f"user:{admin.id}", "role:police", "role:admin"}.issubset(rooms)

        hello_events = [e for e in client.get_received() if e["name"] == "hello"]
        assert hello_events[0]["args"][0]["role"] == "admin"
        client.disconnect()

    def test_garbage_token_emits_auth_expired_and_stays_public(self, app, clean_db):
        client = _sio_client(app, "garbage.token.value")
        assert client.is_connected()
        rooms = _rooms_for(client)
        assert "public" in rooms
        assert "role:police" not in rooms

        received = client.get_received()
        assert "auth:expired" in [e["name"] for e in received]
        hello_events = [e for e in received if e["name"] == "hello"]
        assert hello_events[0]["args"][0]["role"] is None
        client.disconnect()

    def test_disabling_police_user_expels_socket(self, app, clean_db, police, token_for):
        """Disabling a connected police user + calling enforce_session_freshness kicks them."""
        from app.core.time import utcnow
        from app.extensions import db, socketio
        from app.models.models import User
        from app.realtime.connect import enforce_session_freshness, sessions

        client = _sio_client(app, token_for(police.id, role="police"))
        assert client.is_connected()
        sid = _ns_sid(client)
        assert "role:police" in set(socketio.server.rooms(sid, namespace="/"))
        client.get_received()  # drain hello

        with app.app_context():
            u = db.session.get(User, police.id)
            assert u is not None
            u.is_active = False
            db.session.commit()
            enforce_session_freshness(utcnow())

        assert "role:police" not in set(socketio.server.rooms(sid, namespace="/"))
        assert sid not in sessions
        assert not client.is_connected()
        assert "auth:expired" in [e["name"] for e in client.queue]
