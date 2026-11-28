"""tests/integration/test_reports.py — End-to-end B7 Citizen Reports tests."""
from __future__ import annotations

import io
import os
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

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

_INSIDE_LAT, _INSIDE_LNG = 28.6141, 77.2092
_OUTSIDE_LAT, _OUTSIDE_LNG = 28.6200, 77.2200

_REPORT_KEYS = {
    "id",
    "kind",
    "status",
    "zone_id",
    "zone_name",
    "lat",
    "lng",
    "count",
    "density_hint",
    "sos_type",
    "note",
    "created_by",
    "created_at",
    "reviewed_by",
    "reviewed_at",
    "review_note",
}

# Minimal valid JPEG and PNG headers/payloads for fast unit/integration checks
_VALID_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00" + b"\x01" * 64 + b"\xff\xd9"
)
_VALID_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


def _sio_client(app, token: str | None = None):
    from flask_socketio import SocketIOTestClient

    from app.extensions import socketio

    if token is None:
        return SocketIOTestClient(app, socketio)
    return SocketIOTestClient(app, socketio, auth={"token": token})


@pytest.fixture()
def env(app, client, clean_db, make_user, token_for):
    cit_a = make_user(name="Citizen A", email="cit_a@test.local", role="citizen")
    cit_b = make_user(name="Citizen B", email="cit_b@test.local", role="citizen")
    pol = make_user(name="Officer", email="pol_rep@test.local", role="police")
    adm = make_user(name="Admin", email="adm_rep@test.local", role="admin")

    cit_a_tok = token_for(cit_a.id, role="citizen")
    cit_b_tok = token_for(cit_b.id, role="citizen")
    pol_tok = token_for(pol.id, role="police")
    adm_tok = token_for(adm.id, role="admin")

    rz = client.post(
        "/api/v1/zones",
        json={
            "name": "Main Gate B7",
            "geometry": _SQUARE,
            "mode": "DENSITY",
            "warning_density": 3.0,
            "critical_density": 4.0,
        },
        headers=_auth(adm_tok),
    )
    assert rz.status_code == 201
    zone = rz.get_json()["data"]

    return {
        "cit_a": cit_a,
        "cit_b": cit_b,
        "pol": pol,
        "adm": adm,
        "cit_a_tok": cit_a_tok,
        "cit_b_tok": cit_b_tok,
        "pol_tok": pol_tok,
        "adm_tok": adm_tok,
        "zone": zone,
    }


@pytest.fixture()
def started_fake_worker(app, env):
    from app.container import get_container

    with app.app_context():
        dm = get_container().detection_manager
        dm.start(app)
        assert dm.wait_until_ready(timeout=10.0)
        dm.set_fake_count(-1, 14)
    try:
        yield dm
    finally:
        with app.app_context():
            dm.stop(timeout=3.0)


class TestCrowdReports:
    def test_crowd_inside_and_outside_zone_plus_realtime_isolation(
        self, app, client, env, started_fake_worker
    ):
        sio_pub = _sio_client(app)
        sio_cit_b = _sio_client(app, env["cit_b_tok"])
        sio_pol = _sio_client(app, env["pol_tok"])
        sio_pub.get_received()
        sio_cit_b.get_received()
        sio_pol.get_received()

        try:
            # 1) Inside zone (JPEG) -> matches zone, computes density_hint = 14 / area_m2
            r_in = client.post(
                "/api/v1/reports/crowd",
                headers=_auth(env["cit_a_tok"]),
                data={
                    "lat": str(_INSIDE_LAT),
                    "lng": str(_INSIDE_LNG),
                    "note": "Queue near entrance",
                    "image": (io.BytesIO(_VALID_JPEG), "crowd.jpg"),
                },
                content_type="multipart/form-data",
            )
            assert r_in.status_code == 201
            d_in = r_in.get_json()["data"]
            assert set(d_in.keys()) == _REPORT_KEYS
            assert d_in["kind"] == "CROWD"
            assert d_in["status"] == "PENDING"
            assert d_in["zone_id"] == env["zone"]["id"]
            assert d_in["zone_name"] == "Main Gate B7"
            assert d_in["count"] == 14
            expected_density = round(14.0 / float(env["zone"]["area_m2"]), 4)
            assert d_in["density_hint"] == pytest.approx(expected_density)
            assert d_in["sos_type"] is None
            assert d_in["note"] == "Queue near entrance"
            assert d_in["created_by"] == {"id": env["cit_a"].id, "name": "Citizen A"}

            # Realtime: report:new reaches police ONLY (not public, not other citizens)
            pol_evs = [e for e in sio_pol.get_received() if e["name"] == "report:new"]
            pub_evs = [e for e in sio_pub.get_received() if e["name"] == "report:new"]
            cit_evs = [e for e in sio_cit_b.get_received() if e["name"] == "report:new"]
            assert len(pol_evs) == 1
            assert pol_evs[0]["args"][0]["id"] == d_in["id"]
            assert pub_evs == []
            assert cit_evs == []

            # 2) Outside all zones (PNG) -> zone_id=None, zone_name=None, density_hint=None
            r_out = client.post(
                "/api/v1/reports/crowd",
                headers=_auth(env["cit_a_tok"]),
                data={
                    "lat": str(_OUTSIDE_LAT),
                    "lng": str(_OUTSIDE_LNG),
                    "image": (io.BytesIO(_VALID_PNG), "outside.png"),
                },
                content_type="multipart/form-data",
            )
            assert r_out.status_code == 201
            d_out = r_out.get_json()["data"]
            assert d_out["kind"] == "CROWD"
            assert d_out["zone_id"] is None
            assert d_out["zone_name"] is None
            assert d_out["density_hint"] is None
            assert d_out["count"] == 14
        finally:
            sio_pub.disconnect()
            sio_cit_b.disconnect()
            sio_pol.disconnect()

    def test_upload_larger_than_500kb_never_writes_temp_file_to_disk(
        self, client, env, started_fake_worker, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("TMP", str(tmp_path))
        monkeypatch.setenv("TEMP", str(tmp_path))
        monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
        before_entries = set(os.listdir(tmp_path))

        # Use > 600 KB valid JPEG (Werkzeug default spools > 500 KB unless overridden).
        # Build multipart payload in RAM directly so Werkzeug's test EnvironBuilder does
        # not itself create a request-encoding temp file before the server runs.
        large_jpeg = _VALID_JPEG[:-2] + (b"\x00" * (650 * 1024)) + b"\xff\xd9"
        assert len(large_jpeg) > 500 * 1024
        boundary = "----crowdvision-ram-boundary"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="lat"\r\n\r\n{_INSIDE_LAT}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="lng"\r\n\r\n{_INSIDE_LNG}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="large_crowd.jpg"\r\n'
            f"Content-Type: image/jpeg\r\n\r\n"
        ).encode("utf-8") + large_jpeg + f"\r\n--{boundary}--\r\n".encode("utf-8")

        with (
            patch("werkzeug.formparser.SpooledTemporaryFile", side_effect=AssertionError("spooled to disk")),
            patch("tempfile.SpooledTemporaryFile", side_effect=AssertionError("spooled to disk")),
            patch("tempfile.TemporaryFile", side_effect=AssertionError("tmp file created")),
            patch("tempfile.NamedTemporaryFile", side_effect=AssertionError("named tmp created")),
        ):
            r = client.post(
                "/api/v1/reports/crowd",
                headers=_auth(env["cit_a_tok"]),
                data=body,
                content_type=f"multipart/form-data; boundary={boundary}",
            )
        assert r.status_code == 201
        after_entries = set(os.listdir(tmp_path))
        assert after_entries == before_entries == set()

    def test_oversize_413_wrong_content_type_and_bad_coords_422(
        self, client, env, started_fake_worker
    ):
        # Exact 5 MiB (5,242,880 B) total multipart request cap via MAX_CONTENT_LENGTH
        boundary = "----crowdvision-size-boundary"
        prefix = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="lat"\r\n\r\n{_INSIDE_LAT}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="lng"\r\n\r\n{_INSIDE_LNG}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="limit.jpg"\r\n'
            f"Content-Type: image/jpeg\r\n\r\n"
        ).encode("utf-8")
        suffix = f"\r\n--{boundary}--\r\n".encode("utf-8")
        overhead = len(prefix) + len(suffix)
        cap = 5 * 1024 * 1024

        def _make_jpeg_of_len(n: int) -> bytes:
            pad = n - len(_VALID_JPEG)
            assert pad >= 0
            return _VALID_JPEG[:-2] + (b"\x00" * pad) + b"\xff\xd9"

        # Total multipart body == 5,242,880 B -> succeeds (201)
        exact_cap_body = prefix + _make_jpeg_of_len(cap - overhead) + suffix
        assert len(exact_cap_body) == cap
        r_ok_cap = client.post(
            "/api/v1/reports/crowd",
            headers=_auth(env["cit_a_tok"]),
            data=exact_cap_body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        assert r_ok_cap.status_code == 201

        # Total multipart body == 5,242,881 B -> 413 PAYLOAD_TOO_LARGE
        over_one_body = prefix + _make_jpeg_of_len(cap - overhead + 1) + suffix
        assert len(over_one_body) == cap + 1
        r_over_one = client.post(
            "/api/v1/reports/crowd",
            headers=_auth(env["cit_a_tok"]),
            data=over_one_body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        assert r_over_one.status_code == 413
        assert r_over_one.get_json()["error"]["code"] == "PAYLOAD_TOO_LARGE"

        # Exact 5 MiB raw image + multipart framing (> 5 MiB total) -> 413 PAYLOAD_TOO_LARGE
        exact_5mib_img = _make_jpeg_of_len(cap)
        r_big = client.post(
            "/api/v1/reports/crowd",
            headers=_auth(env["cit_a_tok"]),
            data={
                "lat": str(_INSIDE_LAT),
                "lng": str(_INSIDE_LNG),
                "image": (io.BytesIO(exact_5mib_img), "huge.jpg"),
            },
            content_type="multipart/form-data",
        )
        assert r_big.status_code == 413
        assert r_big.get_json()["error"]["code"] == "PAYLOAD_TOO_LARGE"

        # Wrong content type -> 422 VALIDATION_ERROR
        r_txt = client.post(
            "/api/v1/reports/crowd",
            headers=_auth(env["cit_a_tok"]),
            data={
                "lat": str(_INSIDE_LAT),
                "lng": str(_INSIDE_LNG),
                "image": (io.BytesIO(b"hello world"), "notes.txt", "text/plain"),
            },
            content_type="multipart/form-data",
        )
        assert r_txt.status_code == 422
        assert r_txt.get_json()["error"]["code"] == "VALIDATION_ERROR"

        r_gif = client.post(
            "/api/v1/reports/crowd",
            headers=_auth(env["cit_a_tok"]),
            data={
                "lat": str(_INSIDE_LAT),
                "lng": str(_INSIDE_LNG),
                "image": (io.BytesIO(b"GIF89a..."), "anim.gif", "image/gif"),
            },
            content_type="multipart/form-data",
        )
        assert r_gif.status_code == 422

        # Spoofed JPEG MIME with invalid payload bytes -> 422
        r_spoof = client.post(
            "/api/v1/reports/crowd",
            headers=_auth(env["cit_a_tok"]),
            data={
                "lat": str(_INSIDE_LAT),
                "lng": str(_INSIDE_LNG),
                "image": (io.BytesIO(b"not-a-jpeg"), "fake.jpg", "image/jpeg"),
            },
            content_type="multipart/form-data",
        )
        assert r_spoof.status_code == 422

        # Out-of-range coordinates -> 422
        r_lat = client.post(
            "/api/v1/reports/crowd",
            headers=_auth(env["cit_a_tok"]),
            data={
                "lat": "91.5",
                "lng": str(_INSIDE_LNG),
                "image": (io.BytesIO(_VALID_JPEG), "ok.jpg"),
            },
            content_type="multipart/form-data",
        )
        assert r_lat.status_code == 422

    def test_detector_down_or_queue_full_returns_503(self, app, client, env):
        from app.container import get_container
        from app.detection.manager import DetectorUnavailable

        # 1) Detector worker not started -> 503 DETECTOR_UNAVAILABLE
        r_down = client.post(
            "/api/v1/reports/crowd",
            headers=_auth(env["cit_a_tok"]),
            data={
                "lat": str(_INSIDE_LAT),
                "lng": str(_INSIDE_LNG),
                "image": (io.BytesIO(_VALID_JPEG), "crowd.jpg"),
            },
            content_type="multipart/form-data",
        )
        assert r_down.status_code == 503
        assert r_down.get_json()["error"]["code"] == "DETECTOR_UNAVAILABLE"

        # 2) Worker running, queue full -> 503 DETECTOR_UNAVAILABLE
        with app.app_context():
            dm = get_container().detection_manager
            dm.start(app)
            assert dm.wait_until_ready(timeout=10.0)
        try:
            with patch.object(
                app.extensions["container"].detection_manager,
                "detect_once",
                side_effect=DetectorUnavailable("Detection queue is busy."),
            ):
                r_full = client.post(
                    "/api/v1/reports/crowd",
                    headers=_auth(env["cit_a_tok"]),
                    data={
                        "lat": str(_INSIDE_LAT),
                        "lng": str(_INSIDE_LNG),
                        "image": (io.BytesIO(_VALID_JPEG), "crowd.jpg"),
                    },
                    content_type="multipart/form-data",
                )
            assert r_full.status_code == 503
            assert r_full.get_json()["error"]["code"] == "DETECTOR_UNAVAILABLE"
        finally:
            with app.app_context():
                get_container().detection_manager.stop(timeout=3.0)

    def test_late_timeout_result_discarded_before_next_crowd_report(self, app, client, env):
        import time

        from app.container import get_container
        from app.extensions import db
        from app.models.models import Report

        with app.app_context():
            dm = get_container().detection_manager
            prev_delay = dm._worker_delay_ms
            dm._worker_delay_ms = 800.0
            dm.start(app)
            assert dm.wait_until_ready(timeout=10.0)
            dm.set_fake_count(-1, 99)

        sio_pol = _sio_client(app, env["pol_tok"])
        sio_pol.get_received()
        orig_detect_once = dm.detect_once
        call_num = 0

        def _timeout_first_call(jpeg: bytes, timeout: float = 5.0):
            nonlocal call_num
            call_num += 1
            eff_timeout = 0.2 if call_num == 1 else timeout
            return orig_detect_once(jpeg, timeout=eff_timeout)

        try:
            with patch.object(dm, "detect_once", side_effect=_timeout_first_call):
                # 1) First submission times out at 0.2s while spawned worker takes 0.8s -> 503
                r_timeout = client.post(
                    "/api/v1/reports/crowd",
                    headers=_auth(env["cit_a_tok"]),
                    data={
                        "lat": str(_INSIDE_LAT),
                        "lng": str(_INSIDE_LNG),
                        "image": (io.BytesIO(_VALID_JPEG), "slow.jpg"),
                    },
                    content_type="multipart/form-data",
                )
                assert r_timeout.status_code == 503
                assert r_timeout.get_json()["error"]["code"] == "DETECTOR_UNAVAILABLE"

                # Wait for the late worker result (count=99) to finish and pass through _pump_loop
                time.sleep(1.1)
                with app.app_context():
                    assert db.session.query(Report).count() == 0
                assert [e for e in sio_pol.get_received() if e["name"] == "report:new"] == []

                # 2) Submit second image with distinguishable count=7; only its result survives
                dm.set_fake_count(-1, 7)
                r_ok = client.post(
                    "/api/v1/reports/crowd",
                    headers=_auth(env["cit_a_tok"]),
                    data={
                        "lat": str(_INSIDE_LAT),
                        "lng": str(_INSIDE_LNG),
                        "image": (io.BytesIO(_VALID_PNG), "second.png"),
                    },
                    content_type="multipart/form-data",
                )
                assert r_ok.status_code == 201
                data_ok = r_ok.get_json()["data"]
                assert data_ok["count"] == 7

                with app.app_context():
                    rows = db.session.query(Report).all()
                    assert len(rows) == 1
                    assert rows[0].count == 7.0
                events = [e for e in sio_pol.get_received() if e["name"] == "report:new"]
                assert len(events) == 1
                assert events[0]["args"][0]["id"] == data_ok["id"]
                assert events[0]["args"][0]["count"] == 7
        finally:
            sio_pol.disconnect()
            with app.app_context():
                dm.stop(timeout=3.0)
                dm._worker_delay_ms = prev_delay

    def test_real_crowd_photo_with_ultralytics_if_available(self, clean_db, make_user, token_for):
        import importlib.util

        photos_dir = Path(__file__).resolve().parents[3] / "crowd-photos-testing"
        model_path = Path(__file__).resolve().parents[3] / "people_model.pt"
        if not photos_dir.is_dir() or not model_path.is_file():
            pytest.skip("crowd-photos-testing or people_model.pt not present")
        if importlib.util.find_spec("torch") is None:
            pytest.skip("torch not installed")

        jpg_files = sorted(p for p in photos_dir.iterdir() if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg"))
        if not jpg_files:
            pytest.skip("No JPEG files in crowd-photos-testing")

        from app import create_app
        from app.extensions import db

        prev_backend = os.environ.get("DETECTOR_BACKEND")
        prev_model = os.environ.get("MODEL_PATH")
        os.environ["DETECTOR_BACKEND"] = "ultralytics"
        os.environ["MODEL_PATH"] = str(model_path)
        try:
            ultra_app = create_app(
                config_override={
                    "TESTING": True,
                    "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                    "RATELIMIT_ENABLED": False,
                }
            )
        finally:
            if prev_backend is None:
                os.environ.pop("DETECTOR_BACKEND", None)
            else:
                os.environ["DETECTOR_BACKEND"] = prev_backend
            if prev_model is None:
                os.environ.pop("MODEL_PATH", None)
            else:
                os.environ["MODEL_PATH"] = prev_model

        with ultra_app.app_context():
            db.create_all()
            from argon2 import PasswordHasher
            from flask_jwt_extended import create_access_token
            from app.core.time import utcnow
            from app.models.models import User

            cit = User(
                name="RealCit",
                email="realcit@test.local",
                password_hash=PasswordHasher().hash("Pass@1234"),
                role="citizen",
                is_active=True,
                created_at=utcnow().replace(tzinfo=None),
                updated_at=utcnow().replace(tzinfo=None),
            )
            db.session.add(cit)
            db.session.commit()
            tok = create_access_token(identity=str(cit.id), additional_claims={"role": "citizen"})
            dm = ultra_app.extensions["container"].detection_manager
            dm.start(ultra_app)
            assert dm.wait_until_ready(timeout=20.0)

        sample_path = jpg_files[0]
        raw = sample_path.read_bytes()
        try:
            with ultra_app.test_client() as tc:
                resp = tc.post(
                    "/api/v1/reports/crowd",
                    headers=_auth(tok),
                    data={
                        "lat": str(_INSIDE_LAT),
                        "lng": str(_INSIDE_LNG),
                        "image": (io.BytesIO(raw), sample_path.name),
                    },
                    content_type="multipart/form-data",
                )
            assert resp.status_code == 201
            assert isinstance(resp.get_json()["data"]["count"], int)
        finally:
            with ultra_app.app_context():
                ultra_app.extensions["container"].detection_manager.stop(timeout=3.0)
                db.drop_all()


class TestSosListingReviewAndIsolation:
    def test_sos_fire_triggers_fake_notifier_other_does_not_and_both_emit_realtime(
        self, app, client, env
    ):
        from app.container import get_container
        from app.push.notifier import FakeNotifier

        fake_notifier = FakeNotifier()
        with app.app_context():
            c = get_container()
            orig_notifier = c.report_service._notifier
            c.report_service._notifier = fake_notifier

        sio_pub = _sio_client(app)
        sio_pol = _sio_client(app, env["pol_tok"])
        sio_pub.get_received()
        sio_pol.get_received()

        try:
            # FIRE inside zone -> report:new + FakeNotifier.notify_sos called
            r_fire = client.post(
                "/api/v1/reports/sos",
                headers=_auth(env["cit_a_tok"]),
                json={
                    "sos_type": "FIRE",
                    "lat": _INSIDE_LAT,
                    "lng": _INSIDE_LNG,
                    "note": "Smoke near gate",
                },
            )
            assert r_fire.status_code == 201
            fire_data = r_fire.get_json()["data"]
            assert fire_data["kind"] == "SOS"
            assert fire_data["sos_type"] == "FIRE"
            assert fire_data["zone_id"] == env["zone"]["id"]
            assert len(fake_notifier.sos_calls) == 1
            assert fake_notifier.sos_calls[0]["id"] == fire_data["id"]

            # OTHER outside zone -> report:new emitted, FakeNotifier.notify_sos NOT called
            r_other = client.post(
                "/api/v1/reports/sos",
                headers=_auth(env["cit_b_tok"]),
                json={
                    "sos_type": "OTHER",
                    "lat": _OUTSIDE_LAT,
                    "lng": _OUTSIDE_LNG,
                    "note": "Lost bag",
                },
            )
            assert r_other.status_code == 201
            other_data = r_other.get_json()["data"]
            assert other_data["zone_id"] is None
            assert len(fake_notifier.sos_calls) == 1

            # Verify CRUSH_RISK and MEDICAL trigger notify_sos, LOST_CHILD does not
            assert (
                client.post(
                    "/api/v1/reports/sos",
                    headers=_auth(env["cit_a_tok"]),
                    json={"sos_type": "CRUSH_RISK", "lat": _INSIDE_LAT, "lng": _INSIDE_LNG},
                ).status_code
                == 201
            )
            assert (
                client.post(
                    "/api/v1/reports/sos",
                    headers=_auth(env["cit_a_tok"]),
                    json={"sos_type": "MEDICAL", "lat": _INSIDE_LAT, "lng": _INSIDE_LNG},
                ).status_code
                == 201
            )
            assert (
                client.post(
                    "/api/v1/reports/sos",
                    headers=_auth(env["cit_a_tok"]),
                    json={"sos_type": "LOST_CHILD", "lat": _INSIDE_LAT, "lng": _INSIDE_LNG},
                ).status_code
                == 201
            )
            assert [c["sos_type"] for c in fake_notifier.sos_calls] == [
                "FIRE",
                "CRUSH_RISK",
                "MEDICAL",
            ]

            pol_news = [e for e in sio_pol.get_received() if e["name"] == "report:new"]
            pub_news = [e for e in sio_pub.get_received() if e["name"] == "report:new"]
            assert len(pol_news) == 5
            assert pub_news == []
        finally:
            sio_pub.disconnect()
            sio_pol.disconnect()
            with app.app_context():
                get_container().report_service._notifier = orig_notifier

    def test_mine_police_filters_review_audit_realtime_and_double_review_409(
        self, app, client, env, started_fake_worker
    ):
        from app.extensions import db
        from app.models.models import AuditLog

        # Citizen A creates CROWD (inside zone) + SOS (outside zone); Citizen B creates SOS
        r1 = client.post(
            "/api/v1/reports/crowd",
            headers=_auth(env["cit_a_tok"]),
            data={
                "lat": str(_INSIDE_LAT),
                "lng": str(_INSIDE_LNG),
                "image": (io.BytesIO(_VALID_JPEG), "a.jpg"),
            },
            content_type="multipart/form-data",
        )
        assert r1.status_code == 201
        r2 = client.post(
            "/api/v1/reports/sos",
            headers=_auth(env["cit_a_tok"]),
            json={"sos_type": "MEDICAL", "lat": _OUTSIDE_LAT, "lng": _OUTSIDE_LNG},
        )
        assert r2.status_code == 201
        r3 = client.post(
            "/api/v1/reports/sos",
            headers=_auth(env["cit_b_tok"]),
            json={"sos_type": "FIRE", "lat": _INSIDE_LAT, "lng": _INSIDE_LNG},
        )
        assert r3.status_code == 201
        rep1_id = r1.get_json()["data"]["id"]

        # GET /reports/mine -> Citizen A sees only their 2 reports
        mine_a = client.get("/api/v1/reports/mine", headers=_auth(env["cit_a_tok"]))
        assert mine_a.status_code == 200
        mine_body = mine_a.get_json()
        assert mine_body["pagination"]["total"] == 2
        assert all(row["created_by"]["id"] == env["cit_a"].id for row in mine_body["data"])

        # Citizen cannot list all reports -> 403
        assert client.get("/api/v1/reports", headers=_auth(env["cit_a_tok"])).status_code == 403

        # Police filters: kind=SOS, zone_id, status=PENDING
        r_sos = client.get("/api/v1/reports?kind=SOS", headers=_auth(env["pol_tok"]))
        assert r_sos.status_code == 200
        assert r_sos.get_json()["pagination"]["total"] == 2

        r_zone = client.get(
            f"/api/v1/reports?zone_id={env['zone']['id']}", headers=_auth(env["pol_tok"])
        )
        assert r_zone.status_code == 200
        assert r_zone.get_json()["pagination"]["total"] == 2

        # Connect owner citizen A, unrelated citizen B, and police to verify report:updated routing
        sio_cit_a = _sio_client(app, env["cit_a_tok"])
        sio_cit_b = _sio_client(app, env["cit_b_tok"])
        sio_pol = _sio_client(app, env["pol_tok"])
        sio_cit_a.get_received()
        sio_cit_b.get_received()
        sio_pol.get_received()

        try:
            # Police verifies Citizen A's crowd report -> 200, audit REPORT_REVIEWED, realtime report:updated
            r_rev = client.patch(
                f"/api/v1/reports/{rep1_id}",
                headers=_auth(env["pol_tok"]),
                json={"status": "VERIFIED", "review_note": "Confirmed on CCTV"},
            )
            assert r_rev.status_code == 200
            rev_data = r_rev.get_json()["data"]
            assert rev_data["status"] == "VERIFIED"
            assert rev_data["reviewed_by"] == {"id": env["pol"].id, "name": "Officer"}
            assert rev_data["reviewed_at"] is not None
            assert rev_data["review_note"] == "Confirmed on CCTV"

            upd_a = [e for e in sio_cit_a.get_received() if e["name"] == "report:updated"]
            upd_b = [e for e in sio_cit_b.get_received() if e["name"] == "report:updated"]
            upd_p = [e for e in sio_pol.get_received() if e["name"] == "report:updated"]
            assert len(upd_a) == 1 and upd_a[0]["args"][0]["id"] == rep1_id
            assert len(upd_p) == 1 and upd_p[0]["args"][0]["status"] == "VERIFIED"
            assert upd_b == []

            # Audit log created
            with app.app_context():
                audits = db.session.query(AuditLog).filter_by(action="REPORT_REVIEWED", entity_id=rep1_id).all()
                assert len(audits) == 1

            # Double review -> 409 INVALID_TRANSITION
            r_dup = client.patch(
                f"/api/v1/reports/{rep1_id}",
                headers=_auth(env["pol_tok"]),
                json={"status": "DISMISSED"},
            )
            assert r_dup.status_code == 409
            assert r_dup.get_json()["error"]["code"] == "INVALID_TRANSITION"
        finally:
            sio_cit_a.disconnect()
            sio_cit_b.disconnect()
            sio_pol.disconnect()

    def test_concurrent_review_atomic_on_file_sqlite(self, tmp_path):
        import threading

        from argon2 import PasswordHasher
        from flask_jwt_extended import create_access_token

        from app import create_app
        from app.core.time import utcnow
        from app.extensions import db
        from app.models.models import AuditLog, Report, User

        db_file = tmp_path / "concurrent_review.db"
        conc_app = create_app(
            config_override={
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_file.as_posix()}",
                "RATELIMIT_ENABLED": False,
                "JWT_SECRET_KEY": "concurrent-review-jwt-secret-32-bytes!",
                "SECRET_KEY": "concurrent-review-secret",
            }
        )

        with conc_app.app_context():
            db.create_all()
            ph = PasswordHasher()
            now_naive = utcnow().replace(tzinfo=None)
            cit = User(
                name="ConcCit",
                email="conccit@test.local",
                password_hash=ph.hash("Pass@1234"),
                role="citizen",
                is_active=True,
                created_at=now_naive,
                updated_at=now_naive,
            )
            pol1 = User(
                name="Officer One",
                email="pol1_conc@test.local",
                password_hash=ph.hash("Pass@1234"),
                role="police",
                is_active=True,
                created_at=now_naive,
                updated_at=now_naive,
            )
            pol2 = User(
                name="Officer Two",
                email="pol2_conc@test.local",
                password_hash=ph.hash("Pass@1234"),
                role="police",
                is_active=True,
                created_at=now_naive,
                updated_at=now_naive,
            )
            db.session.add_all([cit, pol1, pol2])
            db.session.flush()
            rep = Report(  # pyrefly: ignore[unexpected-keyword]
                kind="SOS",
                status="PENDING",
                zone_id=None,
                lat=_INSIDE_LAT,
                lng=_INSIDE_LNG,
                sos_type="MEDICAL",
                note="Concurrent review target",
                created_by=cit.id,
                created_at=now_naive,
            )
            db.session.add(rep)
            db.session.commit()
            rep_id = rep.id
            cit_id = cit.id
            pol1_id = pol1.id
            pol2_id = pol2.id
            cit_tok = create_access_token(identity=str(cit_id), additional_claims={"role": "citizen"})
            pol1_tok = create_access_token(identity=str(pol1_id), additional_claims={"role": "police"})
            pol2_tok = create_access_token(identity=str(pol2_id), additional_claims={"role": "police"})

        sio_cit = _sio_client(conc_app, cit_tok)
        sio_pol = _sio_client(conc_app, pol1_tok)
        sio_cit.get_received()
        sio_pol.get_received()

        container = conc_app.extensions["container"]
        orig_claim = container.report_repo.claim_review
        claim_barrier = threading.Barrier(2, timeout=5.0)
        results: dict[str, tuple[int, dict]] = {}

        def _synchronized_claim(*args, **kwargs):
            claim_barrier.wait()
            return orig_claim(*args, **kwargs)

        container.report_repo.claim_review = _synchronized_claim

        def _officer_worker(label: str, tok: str, status: str, note: str) -> None:
            with conc_app.test_client() as tc:
                resp = tc.patch(
                    f"/api/v1/reports/{rep_id}",
                    headers=_auth(tok),
                    json={"status": status, "review_note": note},
                )
                results[label] = (resp.status_code, resp.get_json())

        try:
            t1 = threading.Thread(
                target=_officer_worker,
                args=("pol1", pol1_tok, "VERIFIED", "Verified by Officer One"),
            )
            t2 = threading.Thread(
                target=_officer_worker,
                args=("pol2", pol2_tok, "DISMISSED", "Dismissed by Officer Two"),
            )
            t1.start()
            t2.start()
            t1.join(timeout=10.0)
            t2.join(timeout=10.0)

            assert not t1.is_alive() and not t2.is_alive()
            statuses = sorted(code for code, _ in results.values())
            assert statuses == [200, 409]

            winner_label = next(k for k, (code, _) in results.items() if code == 200)
            loser_label = next(k for k, (code, _) in results.items() if code == 409)
            winner_body = results[winner_label][1]["data"]
            loser_body = results[loser_label][1]
            assert loser_body["error"]["code"] == "INVALID_TRANSITION"

            # One logical report:updated event (delivered once to police room, once to owner room)
            pol_updates = [e for e in sio_pol.get_received() if e["name"] == "report:updated"]
            cit_updates = [e for e in sio_cit.get_received() if e["name"] == "report:updated"]
            assert len(pol_updates) == 1
            assert len(cit_updates) == 1
            assert pol_updates[0]["args"][0]["status"] == winner_body["status"]
            assert cit_updates[0]["args"][0]["reviewed_by"] == winner_body["reviewed_by"]

            # One REPORT_REVIEWED audit row and saved fields belong strictly to winner
            with conc_app.app_context():
                db.session.remove()
                saved = db.session.get(Report, rep_id)
                assert saved is not None
                expected_status = "VERIFIED" if winner_label == "pol1" else "DISMISSED"
                expected_actor_id = pol1_id if winner_label == "pol1" else pol2_id
                expected_note = (
                    "Verified by Officer One"
                    if winner_label == "pol1"
                    else "Dismissed by Officer Two"
                )
                assert saved.status == expected_status
                assert saved.reviewed_by == expected_actor_id
                assert saved.reviewed_at is not None
                assert saved.review_note == expected_note
                assert winner_body["status"] == expected_status
                assert winner_body["reviewed_by"]["id"] == expected_actor_id
                assert winner_body["review_note"] == expected_note

                audits = (
                    db.session.query(AuditLog)
                    .filter_by(action="REPORT_REVIEWED", entity_id=rep_id)
                    .all()
                )
                assert len(audits) == 1
                assert audits[0].actor_id == expected_actor_id
        finally:
            container.report_repo.claim_review = orig_claim
            sio_cit.disconnect()
            sio_pol.disconnect()
            with conc_app.app_context():
                db.session.remove()
                db.engine.dispose()

    def test_review_rollback_preserves_pending_and_retry_succeeds(self, app, client, env):
        from app.extensions import db
        from app.models.models import AuditLog, Report

        r_sos = client.post(
            "/api/v1/reports/sos",
            headers=_auth(env["cit_a_tok"]),
            json={"sos_type": "OTHER", "lat": _INSIDE_LAT, "lng": _INSIDE_LNG},
        )
        assert r_sos.status_code == 201
        rep_id = r_sos.get_json()["data"]["id"]

        sio_cit = _sio_client(app, env["cit_a_tok"])
        sio_pol = _sio_client(app, env["pol_tok"])
        sio_cit.get_received()
        sio_pol.get_received()

        container = app.extensions["container"]
        orig_claim = container.report_repo.claim_review
        claim_calls = 0

        def _spied_claim(*args, **kwargs):
            nonlocal claim_calls
            claim_calls += 1
            return orig_claim(*args, **kwargs)

        container.report_repo.claim_review = _spied_claim
        prev_prop = app.config.get("PROPAGATE_EXCEPTIONS")
        app.config["PROPAGATE_EXCEPTIONS"] = False
        try:
            with patch.object(
                db.session,
                "commit",
                side_effect=RuntimeError("simulated post-claim commit failure"),
            ):
                r_fail = client.patch(
                    f"/api/v1/reports/{rep_id}",
                    headers=_auth(env["pol_tok"]),
                    json={"status": "VERIFIED", "review_note": "Should roll back"},
                )
            assert r_fail.status_code == 500
            assert claim_calls == 1

            with app.app_context():
                db.session.rollback()
                db.session.expire_all()
                row = db.session.get(Report, rep_id)
                assert row is not None
                assert row.status == "PENDING"
                assert row.reviewed_by is None
                assert row.reviewed_at is None
                assert row.review_note is None
                assert (
                    db.session.query(AuditLog)
                    .filter_by(action="REPORT_REVIEWED", entity_id=rep_id)
                    .count()
                    == 0
                )
            assert [e for e in sio_pol.get_received() if e["name"] == "report:updated"] == []
            assert [e for e in sio_cit.get_received() if e["name"] == "report:updated"] == []

            # Retry cleanly after rollback
            r_retry = client.patch(
                f"/api/v1/reports/{rep_id}",
                headers=_auth(env["pol_tok"]),
                json={"status": "VERIFIED", "review_note": "Confirmed on retry"},
            )
            assert r_retry.status_code == 200
            retry_data = r_retry.get_json()["data"]
            assert retry_data["status"] == "VERIFIED"
            assert retry_data["reviewed_by"] == {"id": env["pol"].id, "name": "Officer"}
            assert retry_data["review_note"] == "Confirmed on retry"

            with app.app_context():
                db.session.expire_all()
                row = db.session.get(Report, rep_id)
                assert row is not None
                assert row.status == "VERIFIED"
                assert row.reviewed_by == env["pol"].id
                assert row.reviewed_at is not None
                assert row.review_note == "Confirmed on retry"
                assert (
                    db.session.query(AuditLog)
                    .filter_by(action="REPORT_REVIEWED", entity_id=rep_id)
                    .count()
                    == 1
                )
            pol_upd = [e for e in sio_pol.get_received() if e["name"] == "report:updated"]
            cit_upd = [e for e in sio_cit.get_received() if e["name"] == "report:updated"]
            assert len(pol_upd) == 1
            assert len(cit_upd) == 1
            assert pol_upd[0]["args"][0]["review_note"] == "Confirmed on retry"
        finally:
            container.report_repo.claim_review = orig_claim
            if prev_prop is None:
                app.config.pop("PROPAGATE_EXCEPTIONS", None)
            else:
                app.config["PROPAGATE_EXCEPTIONS"] = prev_prop
            sio_cit.disconnect()
            sio_pol.disconnect()

    def test_self_review_by_police_emits_single_report_updated_to_overlapping_socket(
        self, app, client, env, make_user, token_for
    ):
        other_pol = make_user(name="Observer Officer", email="obs_pol@test.local", role="police")
        other_pol_tok = token_for(other_pol.id, role="police")

        # Police officer submits their own SOS report (so pol is in BOTH role:police and user:{pol.id})
        r_sos = client.post(
            "/api/v1/reports/sos",
            headers=_auth(env["pol_tok"]),
            json={"sos_type": "OTHER", "lat": _INSIDE_LAT, "lng": _INSIDE_LNG, "note": "Self report"},
        )
        assert r_sos.status_code == 201
        rep_id = r_sos.get_json()["data"]["id"]

        sio_pol_self = _sio_client(app, env["pol_tok"])
        sio_pol_obs = _sio_client(app, other_pol_tok)
        sio_cit_unrel = _sio_client(app, env["cit_a_tok"])
        sio_pol_self.get_received()
        sio_pol_obs.get_received()
        sio_cit_unrel.get_received()

        try:
            r_rev = client.patch(
                f"/api/v1/reports/{rep_id}",
                headers=_auth(env["pol_tok"]),
                json={"status": "VERIFIED", "review_note": "Verified own report"},
            )
            assert r_rev.status_code == 200

            self_ev = [e for e in sio_pol_self.get_received() if e["name"] == "report:updated"]
            obs_ev = [e for e in sio_pol_obs.get_received() if e["name"] == "report:updated"]
            unrel_ev = [e for e in sio_cit_unrel.get_received() if e["name"] == "report:updated"]
            assert len(self_ev) == 1
            assert len(obs_ev) == 1
            assert unrel_ev == []
            assert self_ev[0]["args"][0]["id"] == rep_id
            assert self_ev[0]["args"][0]["status"] == "VERIFIED"
        finally:
            sio_pol_self.disconnect()
            sio_pol_obs.disconnect()
            sio_cit_unrel.disconnect()

    def test_reports_never_create_or_modify_alerts_or_engine_state(
        self, app, client, env, started_fake_worker
    ):
        from app.container import get_container
        from app.core.clock import FakeClock
        from app.models.models import AlertModel

        clock = FakeClock(start=1_700_000_000.0)
        # Seed a source & put zone in SAFE (count=1 < warning)
        r_src = client.post(
            "/api/v1/sources",
            json={"zone_id": env["zone"]["id"], "name": "Cam Isolation", "kind": "WEBCAM"},
            headers=_auth(env["adm_tok"]),
        )
        assert r_src.status_code == 201
        src_id = r_src.get_json()["data"]["id"]

        with app.app_context():
            c = get_container()
            c.detection_manager.ingest_count(src_id, 1, now=clock.utcnow())
            state_before = c.zone_engine.get_zone_state(env["zone"]["id"], clock.utcnow())
            alerts_before = c.extensions if hasattr(c, "extensions") else None
            _ = alerts_before
            alert_count_before = len(AlertModel.query.all()) if hasattr(AlertModel, "query") else len(
                __import__("app.extensions", fromlist=["db"]).db.session.query(AlertModel).all()
            )
            # High count on crowd report + critical SOS must never alter engine or alerts
            c.detection_manager.set_fake_count(-1, 250)

        assert (
            client.post(
                "/api/v1/reports/crowd",
                headers=_auth(env["cit_a_tok"]),
                data={
                    "lat": str(_INSIDE_LAT),
                    "lng": str(_INSIDE_LNG),
                    "image": (io.BytesIO(_VALID_JPEG), "huge_crowd.jpg"),
                },
                content_type="multipart/form-data",
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/api/v1/reports/sos",
                headers=_auth(env["cit_a_tok"]),
                json={"sos_type": "CRUSH_RISK", "lat": _INSIDE_LAT, "lng": _INSIDE_LNG},
            ).status_code
            == 201
        )

        with app.app_context():
            from app.extensions import db

            c = get_container()
            state_after = c.zone_engine.get_zone_state(env["zone"]["id"], clock.utcnow())
            alert_count_after = len(db.session.query(AlertModel).all())
            assert state_after == state_before
            assert state_after["level"] == "SAFE"
            assert alert_count_after == alert_count_before

    def test_hourly_retention_deletes_old_reports_with_fake_clock(self, app, env):
        from app.core.clock import FakeClock
        from app.extensions import db
        from app.models.models import Report
        from app.realtime.tasks import run_tick_once

        clock = FakeClock(start=1_700_000_000.0)
        now_naive = clock.utcnow().replace(tzinfo=None)

        with app.app_context():
            old_rep = Report(  # pyrefly: ignore[unexpected-keyword]
                kind="SOS",
                status="PENDING",
                zone_id=env["zone"]["id"],
                lat=_INSIDE_LAT,
                lng=_INSIDE_LNG,
                sos_type="OTHER",
                created_by=env["cit_a"].id,
                created_at=now_naive - timedelta(days=31),
            )
            recent_rep = Report(  # pyrefly: ignore[unexpected-keyword]
                kind="CROWD",
                status="PENDING",
                zone_id=env["zone"]["id"],
                lat=_INSIDE_LAT,
                lng=_INSIDE_LNG,
                count=5.0,
                density_hint=0.1,
                created_by=env["cit_a"].id,
                created_at=now_naive - timedelta(days=29),
            )
            db.session.add_all([old_rep, recent_rep])
            db.session.commit()
            old_id = old_rep.id
            recent_id = recent_rep.id

        summary = run_tick_once(app, now=clock.utcnow())
        assert summary["reports_pruned"] == 1

        with app.app_context():
            assert db.session.get(Report, old_id) is None
            assert db.session.get(Report, recent_id) is not None


class TestReportRateLimitingPerUser:
    @pytest.fixture()
    def rl_app(self, monkeypatch):
        monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")
        monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

        from app import create_app
        from app.detection.protocol import DetectResult
        from app.extensions import db, limiter

        prev_enabled = limiter.enabled
        app_rl = create_app(
            config_override={
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "RATELIMIT_ENABLED": True,
                "RATELIMIT_REPORT_CROWD": "1/minute",
                "RATELIMIT_REPORT_SOS": "3 per 10 minutes",
                "JWT_SECRET_KEY": "rl-jwt-secret-key-at-least-32-bytes!",
                "SECRET_KEY": "rl-secret",
            }
        )
        with app_rl.app_context():
            db.create_all()
            limiter.reset()
            try:
                with patch.object(
                    app_rl.extensions["container"].detection_manager,
                    "detect_once",
                    return_value=DetectResult(
                        source_id=-1, seq=1, ok=True, error=None, count=5, boxes=[], infer_ms=1.0, request_id=1
                    ),
                ):
                    yield app_rl
            finally:
                limiter.reset()
                limiter.enabled = prev_enabled
                db.session.remove()
                db.drop_all()

    def test_crowd_and_sos_limits_keyed_by_user_id_not_ip(self, rl_app):
        from argon2 import PasswordHasher
        from flask_jwt_extended import create_access_token

        from app.core.time import utcnow
        from app.extensions import db
        from app.models.models import User

        now_naive = utcnow().replace(tzinfo=None)
        ph = PasswordHasher()
        with rl_app.app_context():
            u1 = User(
                name="RL1",
                email="rl1@test.local",
                password_hash=ph.hash("Pass@1234"),
                role="citizen",
                is_active=True,
                created_at=now_naive,
                updated_at=now_naive,
            )
            u2 = User(
                name="RL2",
                email="rl2@test.local",
                password_hash=ph.hash("Pass@1234"),
                role="citizen",
                is_active=True,
                created_at=now_naive,
                updated_at=now_naive,
            )
            db.session.add_all([u1, u2])
            db.session.commit()
            t1 = create_access_token(identity=str(u1.id), additional_claims={"role": "citizen"})
            t2 = create_access_token(identity=str(u2.id), additional_claims={"role": "citizen"})

        with rl_app.test_client() as client:
            # Crowd report limit (1/minute per user): u1 at IP1 -> 201; u1 at DIFFERENT IP2 -> 429; u2 at SAME IP1 -> 201
            assert (
                client.post(
                    "/api/v1/reports/crowd",
                    headers={**_auth(t1), "X-Forwarded-For": "203.0.113.10"},
                    data={
                        "lat": str(_INSIDE_LAT),
                        "lng": str(_INSIDE_LNG),
                        "image": (io.BytesIO(_VALID_JPEG), "c1.jpg"),
                    },
                    content_type="multipart/form-data",
                ).status_code
                == 201
            )
            r_crowd_429 = client.post(
                "/api/v1/reports/crowd",
                headers={**_auth(t1), "X-Forwarded-For": "198.51.100.77"},
                data={
                    "lat": str(_INSIDE_LAT),
                    "lng": str(_INSIDE_LNG),
                    "image": (io.BytesIO(_VALID_JPEG), "c2.jpg"),
                },
                content_type="multipart/form-data",
            )
            assert r_crowd_429.status_code == 429
            assert r_crowd_429.get_json()["error"]["code"] == "RATE_LIMITED"

            assert (
                client.post(
                    "/api/v1/reports/crowd",
                    headers={**_auth(t2), "X-Forwarded-For": "203.0.113.10"},
                    data={
                        "lat": str(_INSIDE_LAT),
                        "lng": str(_INSIDE_LNG),
                        "image": (io.BytesIO(_VALID_JPEG), "c3.jpg"),
                    },
                    content_type="multipart/form-data",
                ).status_code
                == 201
            )

            # SOS limit (3 per 10 minutes per user): 3 succeed for u1, 4th from different IP -> 429; u2 still succeeds
            for i in range(3):
                assert (
                    client.post(
                        "/api/v1/reports/sos",
                        headers={**_auth(t1), "X-Forwarded-For": f"203.0.113.{20 + i}"},
                        json={"sos_type": "MEDICAL", "lat": _INSIDE_LAT, "lng": _INSIDE_LNG},
                    ).status_code
                    == 201
                )
            r_sos_429 = client.post(
                "/api/v1/reports/sos",
                headers={**_auth(t1), "X-Forwarded-For": "198.51.100.88"},
                json={"sos_type": "MEDICAL", "lat": _INSIDE_LAT, "lng": _INSIDE_LNG},
            )
            assert r_sos_429.status_code == 429
            assert r_sos_429.get_json()["error"]["code"] == "RATE_LIMITED"

            assert (
                client.post(
                    "/api/v1/reports/sos",
                    headers={**_auth(t2), "X-Forwarded-For": "203.0.113.20"},
                    json={"sos_type": "MEDICAL", "lat": _INSIDE_LAT, "lng": _INSIDE_LNG},
                ).status_code
                == 201
            )
