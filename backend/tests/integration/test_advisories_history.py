"""tests/integration/test_advisories_history.py — Integration tests for Advisories, Zone History & SAFE alternatives."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

_SQUARE = {
    "type": "Polygon",
    "coordinates": [[
        [77.2090, 28.6139],
        [77.2094, 28.6139],
        [77.2094, 28.6143],
        [77.2090, 28.6143],
        [77.2090, 28.6139],
    ]],
}


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


def _sio_client(app, token: str | None = None):
    from flask_socketio import SocketIOTestClient
    from app.extensions import socketio

    if token is None:
        return SocketIOTestClient(app, socketio)
    return SocketIOTestClient(app, socketio, auth={"token": token})


@pytest.fixture()
def users(make_user, token_for, clean_db):
    admin = make_user(name="Admin", email="admin_adv@test.local", role="admin")
    police = make_user(name="Police", email="police_adv@test.local", role="police")
    return {
        "admin": admin,
        "police": police,
        "admin_tok": token_for(admin.id, role="admin"),
        "police_tok": token_for(police.id, role="police"),
    }


class TestAdvisories:
    def test_create_list_retract_and_realtime(self, app, client, users):
        admin_tok = users["admin_tok"]
        pol_tok = users["police_tok"]

        rz = client.post(
            "/api/v1/zones",
            json={"name": "Adv Zone", "geometry": _SQUARE},
            headers=_auth(admin_tok),
        )
        zone_id = rz.get_json()["data"]["id"]

        pub_sio = _sio_client(app)
        pub_sio.get_received()

        # Global advisory + zone-scoped advisory
        r_g = client.post(
            "/api/v1/advisories",
            json={"title": "Global Notice", "body": "Stay hydrated", "severity": "INFO"},
            headers=_auth(pol_tok),
        )
        assert r_g.status_code == 201
        adv_g = r_g.get_json()["data"]
        assert adv_g["zone_id"] is None

        r_z = client.post(
            "/api/v1/advisories",
            json={
                "title": "Gate Crowd",
                "body": "Use south exit",
                "severity": "URGENT",
                "zone_id": zone_id,
            },
            headers=_auth(pol_tok),
        )
        assert r_z.status_code == 201
        adv_z = r_z.get_json()["data"]
        assert adv_z["zone_name"] == "Adv Zone"

        # Public list with zone_id includes global + that zone's; without zone_id returns all active
        listed_for_zone = client.get(f"/api/v1/advisories?zone_id={zone_id}").get_json()["data"]
        assert {a["id"] for a in listed_for_zone} == {adv_g["id"], adv_z["id"]}
        listed_other = client.get("/api/v1/advisories?zone_id=999").get_json()["data"]
        assert [a["id"] for a in listed_other] == [adv_g["id"]]

        # Retract
        assert client.delete(f"/api/v1/advisories/{adv_z['id']}", headers=_auth(pol_tok)).status_code == 204
        listed_after = client.get(f"/api/v1/advisories?zone_id={zone_id}").get_json()["data"]
        assert [a["id"] for a in listed_after] == [adv_g["id"]]

        # Realtime advisory:new and advisory:retracted emitted to public
        evs = pub_sio.get_received()
        assert sum(1 for e in evs if e["name"] == "advisory:new") == 2
        retracted = [e for e in evs if e["name"] == "advisory:retracted"]
        assert len(retracted) == 1
        assert retracted[0]["args"][0] == {"id": adv_z["id"]}
        pub_sio.disconnect()

    def test_advisory_expiry_emits_retracted_in_tick(self, app, client, users):
        from app.core.clock import FakeClock
        from app.realtime.tasks import run_tick_once

        pol_tok = users["police_tok"]
        pub_sio = _sio_client(app)
        pub_sio.get_received()

        now = datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        r = client.post(
            "/api/v1/advisories",
            json={
                "title": "Short Alert",
                "body": "Temporary block",
                "severity": "WARNING",
                "expires_at": expires,
            },
            headers=_auth(pol_tok),
        )
        assert r.status_code == 201
        adv_id = r.get_json()["data"]["id"]
        pub_sio.get_received()

        # Before expiry -> still active
        run_tick_once(app, now=now + timedelta(seconds=10))
        assert len(client.get("/api/v1/advisories").get_json()["data"]) == 1

        # After expiry -> deactivated and advisory:retracted emitted
        run_tick_once(app, now=now + timedelta(seconds=35))
        assert client.get("/api/v1/advisories").get_json()["data"] == []
        retracted = [e for e in pub_sio.get_received() if e["name"] == "advisory:retracted"]
        assert len(retracted) == 1
        assert retracted[0]["args"][0] == {"id": adv_id}
        pub_sio.disconnect()


class TestHistoryAndAlternatives:
    def test_zone_history_bucketed_and_1hz_sample_persistence(self, app, client, users):
        from app.container import get_container
        from app.core.clock import FakeClock
        from app.realtime.tasks import run_tick_once

        admin_tok = users["admin_tok"]
        pol_tok = users["police_tok"]

        rz = client.post(
            "/api/v1/zones",
            json={"name": "Hist Zone", "geometry": _SQUARE, "mode": "COUNT", "warning_count": 3, "critical_count": 5},
            headers=_auth(admin_tok),
        )
        zone_id = rz.get_json()["data"]["id"]
        rsrc = client.post(
            "/api/v1/sources",
            json={"zone_id": zone_id, "name": "Hist Cam", "kind": "WEBCAM"},
            headers=_auth(admin_tok),
        )
        src_id = rsrc.get_json()["data"]["id"]

        clock = FakeClock(start=1_700_000_000.0)
        with app.app_context():
            c = get_container()
            c.detection_manager.ingest_count(src_id, 2, now=clock.utcnow())
        # Tick at t=0 -> writes sample; t=1 -> skipped (<2s); t=2 -> writes sample; t=12 -> new 10s bucket
        run_tick_once(app, now=clock.utcnow())
        clock.advance(1.0)
        run_tick_once(app, now=clock.utcnow())
        clock.advance(1.0)
        run_tick_once(app, now=clock.utcnow())
        clock.advance(10.0)
        with app.app_context():
            get_container().detection_manager.ingest_count(src_id, 4, now=clock.utcnow())
        run_tick_once(app, now=clock.utcnow())

        t_from = "2023-11-14T22:13:00Z"
        t_to = "2023-11-14T22:15:00Z"
        r10 = client.get(
            f"/api/v1/zones/{zone_id}/history?from={t_from}&to={t_to}&bucket_s=10",
            headers=_auth(pol_tok),
        )
        assert r10.status_code == 200
        pts10 = r10.get_json()["data"]
        assert len(pts10) == 2
        assert set(pts10[0].keys()) == {"ts", "count", "density", "level"}

        r60 = client.get(
            f"/api/v1/zones/{zone_id}/history?from={t_from}&to={t_to}&bucket_s=60",
            headers=_auth(pol_tok),
        )
        assert r60.status_code == 200
        assert len(r60.get_json()["data"]) == 1

        # Invalid bucket_s -> 422
        r_bad = client.get(
            f"/api/v1/zones/{zone_id}/history?bucket_s=15",
            headers=_auth(pol_tok),
        )
        assert r_bad.status_code == 422

    def test_public_alternatives_nearest_safe_zones_live(self, app, client, users):
        from app.container import get_container
        from app.core.clock import FakeClock

        admin_tok = users["admin_tok"]
        zone_ids = []
        src_ids = []
        for idx in range(5):
            off = idx * 0.001
            geom = {
                "type": "Polygon",
                "coordinates": [[
                    [77.2090 + off, 28.6139],
                    [77.2092 + off, 28.6139],
                    [77.2092 + off, 28.6141],
                    [77.2090 + off, 28.6141],
                    [77.2090 + off, 28.6139],
                ]],
            }
            rz = client.post(
                "/api/v1/zones",
                json={"name": f"Alt {idx}", "geometry": geom, "mode": "COUNT", "warning_count": 3, "critical_count": 5},
                headers=_auth(admin_tok),
            )
            zid = rz.get_json()["data"]["id"]
            zone_ids.append(zid)
            rs = client.post(
                "/api/v1/sources",
                json={"zone_id": zid, "name": f"Cam {idx}", "kind": "WEBCAM"},
                headers=_auth(admin_tok),
            )
            src_ids.append(rs.get_json()["data"]["id"])

        clock = FakeClock(start=1_700_000_000.0)
        with app.app_context():
            dm = get_container().detection_manager
            dm.ingest_count(src_ids[0], 6, now=clock.utcnow())  # CRITICAL
            dm.ingest_count(src_ids[1], 4, now=clock.utcnow())  # WARNING (excluded)
            dm.ingest_count(src_ids[2], 1, now=clock.utcnow())  # SAFE
            dm.ingest_count(src_ids[3], 1, now=clock.utcnow())  # SAFE
            dm.ingest_count(src_ids[4], 1, now=clock.utcnow())  # SAFE

        r_pub = client.get(f"/api/v1/zones/{zone_ids[0]}/public")
        assert r_pub.status_code == 200
        data = r_pub.get_json()["data"]
        assert data["state"]["level"] == "CRITICAL"
        assert [a["zone_id"] for a in data["alternatives"]] == [
            zone_ids[2],
            zone_ids[3],
            zone_ids[4],
        ]
