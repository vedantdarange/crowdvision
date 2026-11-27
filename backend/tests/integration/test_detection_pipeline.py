"""tests/integration/test_detection_pipeline.py — End-to-end B5a detection worker & frame:submit tests."""
from __future__ import annotations

import builtins
import logging
import os
import signal
import struct
import tempfile
import time
from typing import Any

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


def make_test_jpeg(width: int = 640, height: int = 480, *, pad_bytes: int = 0) -> bytes:
    """Build a minimal valid in-memory JPEG byte stream with SOF0 dimensions."""
    buf = bytearray(b"\xff\xd8")
    # APP0 JFIF header (16 bytes total payload+len)
    buf += b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    remaining = pad_bytes
    while remaining > 0:
        chunk = min(remaining, 60_000)
        buf += b"\xff\xfe" + struct.pack(">H", chunk + 2) + (b"\x00" * chunk)
        remaining -= chunk
    # SOF0 frame header
    buf += b"\xff\xc0\x00\x0b\x08" + struct.pack(">HH", height, width) + b"\x01\x01\x11\x00"
    buf += b"\xff\xd9"
    return bytes(buf)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _sio_client(app, token: str | None = None):
    from flask_socketio import SocketIOTestClient
    from app.extensions import socketio

    if token is None:
        return SocketIOTestClient(app, socketio)
    return SocketIOTestClient(app, socketio, auth={"token": token})


def _wait_for_events(
    sio_client,
    name: str,
    *,
    min_count: int = 1,
    timeout: float = 4.0,
) -> list[dict[str, Any]]:
    """Poll SocketIOTestClient received events without busy spinning."""
    collected: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for ev in sio_client.get_received():
            if ev["name"] == name:
                collected.append(ev["args"][0] if ev["args"] else {})
        if len(collected) >= min_count:
            return collected
        time.sleep(0.02)
    return collected


@pytest.fixture()
def seeded_pipeline(app, client, clean_db, make_user, token_for):
    """Create admin, police1, police2, citizen, COUNT zone (W=3, C=5), and active source."""
    admin = make_user(name="Admin", email="admin_b5a@test.local", role="admin")
    police1 = make_user(name="Police 1", email="police1_b5a@test.local", role="police")
    police2 = make_user(name="Police 2", email="police2_b5a@test.local", role="police")
    citizen = make_user(name="Citizen", email="citizen_b5a@test.local", role="citizen")

    admin_tok = token_for(admin.id, role="admin")
    p1_tok = token_for(police1.id, role="police")
    p2_tok = token_for(police2.id, role="police")
    cit_tok = token_for(citizen.id, role="citizen")

    # Speed up debounce/stale for fast integration tests
    rs_set = client.patch(
        "/api/v1/settings",
        json={"debounce_s": 0, "clear_s": 0, "smoothing_window": 3, "stale_after_s": 5},
        headers=_auth(admin_tok),
    )
    assert rs_set.status_code == 200

    rz = client.post(
        "/api/v1/zones",
        json={
            "name": "B5a Main Gate",
            "geometry": _SQUARE,
            "mode": "COUNT",
            "warning_density": 3.0,
            "critical_density": 4.0,
            "warning_count": 3,
            "critical_count": 5,
        },
        headers=_auth(admin_tok),
    )
    assert rz.status_code == 201
    zone = rz.get_json()["data"]

    rs = client.post(
        "/api/v1/sources",
        json={
            "zone_id": zone["id"],
            "name": "B5a Gate Cam",
            "kind": "WEBCAM",
            "coverage_area_m2": 10.0,
        },
        headers=_auth(admin_tok),
    )
    assert rs.status_code == 201
    source = rs.get_json()["data"]

    return {
        "zone": zone,
        "source": source,
        "admin": admin,
        "police1": police1,
        "police2": police2,
        "citizen": citizen,
        "admin_tok": admin_tok,
        "p1_tok": p1_tok,
        "p2_tok": p2_tok,
        "cit_tok": cit_tok,
    }


@pytest.fixture()
def running_worker(app, seeded_pipeline):
    """Start DetectionManager's real spawned worker for a test and stop cleanly after."""
    from app.container import get_container

    with app.app_context():
        manager = get_container().detection_manager

    manager.start(app)
    assert manager.wait_until_ready(timeout=5.0)
    try:
        yield manager
    finally:
        manager.stop(timeout=3.0)


class TestFramePipelineEndToEnd:
    def test_submit_drives_zone_to_warning_and_critical_and_sender_only(
        self, app, client, seeded_pipeline, running_worker
    ):
        source_id = seeded_pipeline["source"]["id"]
        zone_id = seeded_pipeline["zone"]["id"]

        p1 = _sio_client(app, seeded_pipeline["p1_tok"])
        p2 = _sio_client(app, seeded_pipeline["p2_tok"])
        p1.get_received()
        p2.get_received()

        jpeg = make_test_jpeg(640, 480)
        try:
            # 1. Drive count=4 (>= WARNING 3, < CRITICAL 5)
            running_worker.set_fake_count(source_id, 4)
            p1.emit(
                "frame:submit",
                {
                    "source_id": source_id,
                    "seq": 1,
                    "captured_at": "2026-11-27T09:00:00Z",
                    "width": 640,
                    "height": 480,
                    "image": jpeg,
                },
            )
            res1 = _wait_for_events(p1, "frame:result", min_count=1, timeout=4.0)
            assert len(res1) == 1
            r1 = res1[0]
            assert r1["ok"] is True
            assert r1["source_id"] == source_id
            assert r1["seq"] == 1
            assert r1["count"] == 4
            assert len(r1["boxes"]) == 4
            assert r1["infer_ms"] >= 0.0
            assert r1["smoothed_count"] == 4.0
            assert r1["density"] == 0.4
            assert r1["level"] == "WARNING"

            # Verify p2 did NOT receive p1's frame:result
            p2_events = p2.get_received()
            assert not any(e["name"] == "frame:result" for e in p2_events)

            # 2. Drive count=6 (>= CRITICAL 5)
            running_worker.set_fake_count(source_id, 6)
            for seq in (2, 3):
                p1.emit(
                    "frame:submit",
                    {
                        "source_id": source_id,
                        "seq": seq,
                        "captured_at": "2026-11-27T09:00:01Z",
                        "width": 640,
                        "height": 480,
                        "image": jpeg,
                    },
                )
            res2 = _wait_for_events(p1, "frame:result", min_count=2, timeout=4.0)
            assert len(res2) == 2
            # Rolling median over [4, 6, 6] == 6 -> CRITICAL
            assert res2[-1]["ok"] is True
            assert res2[-1]["level"] == "CRITICAL"
            assert res2[-1]["smoothed_count"] == 6.0

            # Confirm zone REST state and alerts match
            z_resp = client.get(
                f"/api/v1/zones/{zone_id}", headers=_auth(seeded_pipeline["p1_tok"])
            )
            assert z_resp.status_code == 200
            assert z_resp.get_json()["data"]["level"] == "CRITICAL"

            a_resp = client.get(
                "/api/v1/alerts?active=true", headers=_auth(seeded_pipeline["p1_tok"])
            )
            assert a_resp.status_code == 200
            alerts = a_resp.get_json()["data"]
            assert len(alerts) == 1
            assert alerts[0]["level"] == "CRITICAL"
        finally:
            p1.disconnect()
            p2.disconnect()

    def test_frame_result_hud_uses_zone_level_max_across_sources(
        self, app, client, seeded_pipeline, running_worker
    ):
        """frame:result reports this source's raw count/boxes, but ZONE-level HUD metrics."""
        zone_id = seeded_pipeline["zone"]["id"]
        src1_id = seeded_pipeline["source"]["id"]
        rs2 = client.post(
            "/api/v1/sources",
            json={"zone_id": zone_id, "name": "B5a Cam 2", "kind": "VIDEO_FILE"},
            headers=_auth(seeded_pipeline["admin_tok"]),
        )
        assert rs2.status_code == 201
        src2_id = rs2.get_json()["data"]["id"]

        p1 = _sio_client(app, seeded_pipeline["p1_tok"])
        p2 = _sio_client(app, seeded_pipeline["p2_tok"])
        p1.get_received()
        p2.get_received()
        jpeg = make_test_jpeg(640, 480)
        try:
            running_worker.set_fake_count(src2_id, 6)  # CRITICAL on source 2
            p2.emit("frame:submit", {"source_id": src2_id, "seq": 1, "width": 640, "height": 480, "image": jpeg})
            r_src2 = _wait_for_events(p2, "frame:result", min_count=1)[0]
            assert r_src2["level"] == "CRITICAL"

            running_worker.set_fake_count(src1_id, 1)  # Low count on source 1
            p1.emit("frame:submit", {"source_id": src1_id, "seq": 1, "width": 640, "height": 480, "image": jpeg})
            r_src1 = _wait_for_events(p1, "frame:result", min_count=1)[0]
            assert r_src1["count"] == 1
            assert len(r_src1["boxes"]) == 1
            # Zone level & smoothed_count come from MAX over fresh sources (src2=6 -> CRITICAL)
            assert r_src1["smoothed_count"] == 6.0
            assert r_src1["level"] == "CRITICAL"
        finally:
            p1.disconnect()
            p2.disconnect()


class TestLeaseAndReset:
    def test_one_streamer_per_source_lease_and_disconnect_release(
        self, app, seeded_pipeline, running_worker
    ):
        source_id = seeded_pipeline["source"]["id"]
        p1 = _sio_client(app, seeded_pipeline["p1_tok"])
        p2 = _sio_client(app, seeded_pipeline["p2_tok"])
        p1.get_received()
        p2.get_received()
        jpeg = make_test_jpeg(640, 480)
        try:
            # p1 acquires lease
            p1.emit("frame:submit", {"source_id": source_id, "seq": 1, "width": 640, "height": 480, "image": jpeg})
            res_p1 = _wait_for_events(p1, "frame:result", min_count=1)
            assert res_p1[0]["ok"] is True

            # p2 attempts to stream same source -> rejected with SOURCE_IN_USE (not queued)
            p2.emit("frame:submit", {"source_id": source_id, "seq": 1, "width": 640, "height": 480, "image": jpeg})
            res_p2 = _wait_for_events(p2, "frame:result", min_count=1)
            assert res_p2[0]["ok"] is False
            assert res_p2[0]["error"] == "SOURCE_IN_USE"

            # Disconnect p1 -> lease is released immediately, so p2 succeeds
            p1.disconnect()
            time.sleep(0.05)

            p2.emit("frame:submit", {"source_id": source_id, "seq": 2, "width": 640, "height": 480, "image": jpeg})
            res_p2_ok = _wait_for_events(p2, "frame:result", min_count=1)
            assert res_p2_ok[0]["ok"] is True
            assert res_p2_ok[0]["seq"] == 2
        finally:
            if p1.is_connected():
                p1.disconnect()
            p2.disconnect()

    def test_reset_true_clears_smoothing_buffer(
        self, app, seeded_pipeline, running_worker
    ):
        source_id = seeded_pipeline["source"]["id"]
        p1 = _sio_client(app, seeded_pipeline["p1_tok"])
        p1.get_received()
        jpeg = make_test_jpeg(640, 480)
        try:
            running_worker.set_fake_count(source_id, 10)
            for seq in (1, 2):
                p1.emit("frame:submit", {"source_id": source_id, "seq": seq, "width": 640, "height": 480, "image": jpeg})
            res_hi = _wait_for_events(p1, "frame:result", min_count=2)
            assert res_hi[-1]["smoothed_count"] == 10.0

            # With reset=False and count=0, median of [10, 10, 0] would stay 10.
            # With reset=True, smoothing buffer clears so smoothed_count drops to 0 immediately.
            running_worker.set_fake_count(source_id, 0)
            p1.emit(
                "frame:submit",
                {"source_id": source_id, "seq": 3, "reset": True, "width": 640, "height": 480, "image": jpeg},
            )
            res_reset = _wait_for_events(p1, "frame:result", min_count=1)
            assert res_reset[0]["ok"] is True
            assert res_reset[0]["smoothed_count"] == 0.0
            assert res_reset[0]["level"] == "SAFE"
        finally:
            p1.disconnect()


class TestValidationAndAuthGuards:
    def test_forbidden_citizen_and_anonymous_and_stale_session(
        self, app, seeded_pipeline, running_worker
    ):
        from app.extensions import db
        from app.models.models import User

        source_id = seeded_pipeline["source"]["id"]
        jpeg = make_test_jpeg(640, 480)

        anon = _sio_client(app)
        cit = _sio_client(app, seeded_pipeline["cit_tok"])
        pol = _sio_client(app, seeded_pipeline["p1_tok"])
        anon.get_received()
        cit.get_received()
        pol.get_received()
        try:
            anon.emit("frame:submit", {"source_id": source_id, "seq": 1, "width": 640, "height": 480, "image": jpeg})
            r_anon = _wait_for_events(anon, "frame:result", min_count=1)
            assert r_anon[0]["ok"] is False and r_anon[0]["error"] == "FORBIDDEN"

            cit.emit("frame:submit", {"source_id": source_id, "seq": 1, "width": 640, "height": 480, "image": jpeg})
            r_cit = _wait_for_events(cit, "frame:result", min_count=1)
            assert r_cit[0]["ok"] is False and r_cit[0]["error"] == "FORBIDDEN"

            # Disable police user in DB; next frame:submit checks freshness & expels socket
            with app.app_context():
                u = db.session.get(User, seeded_pipeline["police1"].id)
                assert u is not None
                u.is_active = False
                db.session.commit()

            pol.emit("frame:submit", {"source_id": source_id, "seq": 1, "width": 640, "height": 480, "image": jpeg})
            assert not pol.is_connected()
            queued_names = [e["name"] for e in pol.queue]
            assert "auth:expired" in queued_names
        finally:
            for c in (anon, cit, pol):
                if c.is_connected():
                    c.disconnect()

    def test_unknown_source_and_bad_image_paths(
        self, app, client, seeded_pipeline, running_worker
    ):
        source_id = seeded_pipeline["source"]["id"]
        p1 = _sio_client(app, seeded_pipeline["p1_tok"])
        p1.get_received()
        try:
            # Nonexistent source -> UNKNOWN_SOURCE
            p1.emit(
                "frame:submit",
                {"source_id": 999999, "seq": 1, "width": 640, "height": 480, "image": make_test_jpeg()},
            )
            r_unk = _wait_for_events(p1, "frame:result", min_count=1)[0]
            assert r_unk["ok"] is False and r_unk["error"] == "UNKNOWN_SOURCE"

            # Non-JPEG bytes -> BAD_IMAGE
            p1.emit(
                "frame:submit",
                {"source_id": source_id, "seq": 2, "width": 640, "height": 480, "image": b"\x89PNG\r\n\x1a\n"},
            )
            r_png = _wait_for_events(p1, "frame:result", min_count=1)[0]
            assert r_png["ok"] is False and r_png["error"] == "BAD_IMAGE"

            # Oversized JPEG (> 300 KB) -> BAD_IMAGE
            big_jpeg = make_test_jpeg(640, 480, pad_bytes=301 * 1024)
            p1.emit(
                "frame:submit",
                {"source_id": source_id, "seq": 3, "width": 640, "height": 480, "image": big_jpeg},
            )
            r_big = _wait_for_events(p1, "frame:result", min_count=1)[0]
            assert r_big["ok"] is False and r_big["error"] == "BAD_IMAGE"

            # Too wide (> 1280 px) -> BAD_IMAGE
            wide_jpeg = make_test_jpeg(1920, 1080)
            p1.emit(
                "frame:submit",
                {"source_id": source_id, "seq": 4, "width": 1920, "height": 1080, "image": wide_jpeg},
            )
            r_wide = _wait_for_events(p1, "frame:result", min_count=1)[0]
            assert r_wide["ok"] is False and r_wide["error"] == "BAD_IMAGE"

            # Soft-deleted source -> UNKNOWN_SOURCE
            del_resp = client.delete(
                f"/api/v1/sources/{source_id}", headers=_auth(seeded_pipeline["admin_tok"])
            )
            assert del_resp.status_code in (200, 204)
            p1.emit(
                "frame:submit",
                {"source_id": source_id, "seq": 5, "width": 640, "height": 480, "image": make_test_jpeg()},
            )
            r_inact = _wait_for_events(p1, "frame:result", min_count=1)[0]
            assert r_inact["ok"] is False and r_inact["error"] == "UNKNOWN_SOURCE"
        finally:
            p1.disconnect()


class TestQueueFloodHealthSupervisionAndPrivacy:
    def test_queue_full_flood_returns_detector_busy_without_blocking(
        self, app, seeded_pipeline
    ):
        from app.container import get_container

        with app.app_context():
            manager = get_container().detection_manager

        # Configure slight per-frame worker delay so a rapid burst of 24 frames fills queue (maxsize 16)
        old_delay = manager._worker_delay_ms
        manager._worker_delay_ms = 120.0
        manager.start(app)
        assert manager.wait_until_ready(timeout=5.0)
        p1 = _sio_client(app, seeded_pipeline["p1_tok"])
        p1.get_received()
        jpeg = make_test_jpeg(640, 480)
        source_id = seeded_pipeline["source"]["id"]
        try:
            t0 = time.monotonic()
            for seq in range(1, 26):
                p1.emit(
                    "frame:submit",
                    {"source_id": source_id, "seq": seq, "width": 640, "height": 480, "image": jpeg},
                )
            emit_elapsed = time.monotonic() - t0
            assert emit_elapsed < 1.5, f"Queue-full blocked caller for {emit_elapsed:.2f}s"

            results = _wait_for_events(p1, "frame:result", min_count=25, timeout=6.0)
            busy = [r for r in results if not r["ok"] and r.get("error") == "DETECTOR_BUSY"]
            succeeded = [r for r in results if r["ok"]]
            assert len(busy) >= 1
            assert len(succeeded) >= 1
        finally:
            p1.disconnect()
            manager.stop(timeout=3.0)
            manager._worker_delay_ms = old_delay

    def test_health_ping_pong_and_worker_kill_restart_and_exhaustion(
        self, app, client, seeded_pipeline
    ):
        from app.container import get_container

        with app.app_context():
            manager = get_container().detection_manager

        old_backoffs = manager._restart_backoffs
        manager._restart_backoffs = (0.05, 0.05, 0.05)
        manager.start(app)
        try:
            assert manager.wait_until_ready(timeout=5.0)
            h1 = client.get("/api/v1/health").get_json()
            assert h1["detector"] == "ready"
            assert h1["worker_alive"] is True

            # Kill worker mid-run and verify supervisor restarts it with a new PID
            old_pid = manager.worker_pid
            assert old_pid is not None
            os.kill(old_pid, signal.SIGTERM)

            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if manager.worker_pid is not None and manager.worker_pid != old_pid and manager.detector_status == "ready":
                    break
                time.sleep(0.05)

            assert manager.worker_pid is not None and manager.worker_pid != old_pid
            assert manager.restart_count >= 1
            h2 = client.get("/api/v1/health").get_json()
            assert h2["detector"] == "ready"
            assert h2["worker_alive"] is True

            # Exhaust remaining restarts (kills 2, 3, and then 4th final death -> unavailable)
            for _ in range(3):
                # Wait for current respawned worker to be alive
                w_dead = time.monotonic() + 4.0
                while time.monotonic() < w_dead and (manager._process is None or not manager._process.is_alive()):
                    time.sleep(0.02)
                pid = manager.worker_pid
                if pid is not None and manager._process is not None and manager._process.is_alive():
                    os.kill(pid, signal.SIGTERM)
                # Wait briefly for supervisor to observe death
                k_dead = time.monotonic() + 2.0
                while time.monotonic() < k_dead and manager._process is not None and manager._process.is_alive() and manager.worker_pid == pid:
                    time.sleep(0.02)
                time.sleep(0.1)

            # Wait until supervisor hits max_restarts=3 and marks unavailable
            u_dead = time.monotonic() + 4.0
            while time.monotonic() < u_dead:
                if manager.restart_count >= 3 and manager.detector_status == "unavailable" and (manager._process is None or not manager._process.is_alive()):
                    break
                time.sleep(0.05)

            h3 = client.get("/api/v1/health").get_json()
            assert h3["detector"] == "unavailable"
            assert h3["worker_alive"] is False
        finally:
            manager.stop(timeout=3.0)
            manager._restart_backoffs = old_backoffs

    def test_clean_shutdown_leaves_no_orphan_process(self, app, seeded_pipeline):
        from app.container import get_container

        with app.app_context():
            manager = get_container().detection_manager

        manager.start(app)
        assert manager.wait_until_ready(timeout=5.0)
        proc = manager._process
        assert proc is not None and proc.is_alive()

        manager.stop(timeout=3.0)
        assert not proc.is_alive()
        assert proc.exitcode is not None
        assert manager.worker_pid is None

    def test_detect_once_and_privacy_zero_file_writes_and_no_jpeg_logged(
        self, app, seeded_pipeline, running_worker, monkeypatch, caplog
    ):
        from app.core.errors import DetectorUnavailable

        source_id = seeded_pipeline["source"]["id"]
        jpeg = make_test_jpeg(640, 480)
        p1 = _sio_client(app, seeded_pipeline["p1_tok"])
        p1.get_received()

        write_opens: list[str] = []
        orig_open = builtins.open

        def _spy_open(file, mode="r", *args, **kwargs):
            if any(ch in str(mode) for ch in ("w", "a", "x", "+")):
                write_opens.append(str(file))
            return orig_open(file, mode, *args, **kwargs)

        def _forbid_temp(*args, **kwargs):
            raise AssertionError("Pipeline must never create temp files")

        # Note: builtins.open/tempfile monkeypatches verify the main Flask process only;
        # the spawned worker runs in a separate process and is verified by inspection of
        # app/detection/worker.py and app/detection/detector.py (zero disk I/O / JPEG logging).
        monkeypatch.setattr(builtins, "open", _spy_open)
        monkeypatch.setattr(tempfile, "TemporaryFile", _forbid_temp)
        monkeypatch.setattr(tempfile, "NamedTemporaryFile", _forbid_temp)
        monkeypatch.setattr(tempfile, "mkstemp", _forbid_temp)

        try:
            with caplog.at_level(logging.DEBUG):
                running_worker.set_fake_count(source_id, 2)
                p1.emit(
                    "frame:submit",
                    {"source_id": source_id, "seq": 1, "width": 640, "height": 480, "image": jpeg},
                )
                res = _wait_for_events(p1, "frame:result", min_count=1)
                assert len(res) == 1 and res[0]["ok"] is True

                # Synchronous detect_once for citizen reports (uses source_id=-1, no tracker)
                running_worker.set_fake_count(-1, 3)
                once_res = running_worker.detect_once(jpeg, timeout=5.0)
                assert once_res.ok is True
                assert once_res.source_id == -1
                assert once_res.count == 3
                assert len(once_res.boxes) == 3

            assert write_opens == [], f"Unexpected file writes: {write_opens}"
            for rec in caplog.records:
                msg = rec.getMessage()
                assert "JFIF" not in msg
                assert "\\xff\\xd8" not in msg
        finally:
            monkeypatch.undo()
            p1.disconnect()

        # After stop, detect_once raises DetectorUnavailable (503)
        running_worker.stop(timeout=3.0)
        with pytest.raises(DetectorUnavailable):
            running_worker.detect_once(jpeg, timeout=1.0)


# ---------------------------------------------------------------------------
# B5a Bug Regression Tests
# ---------------------------------------------------------------------------

class TestBug1DelayedResultRouting:
    """Regression for Bug 1: stale DetectResult after disconnect routes to new sender.

    Fix: _inflight is now keyed on a unique request_id rather than (sid, source_id, seq).
    A delayed result whose request_id is no longer in _inflight is silently discarded.
    """

    def test_delayed_result_after_disconnect_does_not_reach_new_sender(
        self, app, client, seeded_pipeline
    ):
        """Disconnect the original sender while its result is in-flight.
        A new sender then submits a request with the same seq.
        The new sender must receive only its own result, never the stale one.
        """
        from app.container import get_container

        with app.app_context():
            manager = get_container().detection_manager

        # Use a 350 ms worker delay so we can disconnect before the result arrives
        manager._worker_delay_ms = 350.0
        manager.start(app)
        assert manager.wait_until_ready(timeout=5.0)

        source_id = seeded_pipeline["source"]["id"]
        jpeg = make_test_jpeg(640, 480)

        p1 = _sio_client(app, seeded_pipeline["p1_tok"])
        p2 = _sio_client(app, seeded_pipeline["p2_tok"])
        p1.get_received()
        p2.get_received()

        try:
            # p1 acquires lease and submits seq=1 — result is delayed 350 ms
            manager.set_fake_count(source_id, 9)
            p1.emit(
                "frame:submit",
                {"source_id": source_id, "seq": 1, "width": 640, "height": 480, "image": jpeg},
            )
            # Disconnect p1 immediately (before the 350 ms result arrives)
            p1.disconnect()
            time.sleep(0.05)  # Let disconnect handler run

            # p2 now takes the same source with seq=1 (same seq as p1 used)
            manager.set_fake_count(source_id, 2)
            p2.emit(
                "frame:submit",
                {"source_id": source_id, "seq": 1, "width": 640, "height": 480, "image": jpeg},
            )

            # Wait long enough for both results to be processed
            p2_results = _wait_for_events(p2, "frame:result", min_count=1, timeout=4.0)

            # p2 should receive exactly one result — its own (count=2), not p1's (count=9)
            assert len(p2_results) >= 1
            for r in p2_results:
                assert r["ok"] is True
                assert r["count"] == 2, (
                    f"p2 received stale count={r['count']} from p1's delayed result (Bug 1 not fixed)"
                )

            # p1's zone must not have gone CRITICAL (count=9) due to its stale result
            # (p1 was disconnected before ingest_count ran for its request_id)
            zone_resp = client.get(
                f"/api/v1/zones/{seeded_pipeline['zone']['id']}",
                headers=_auth(seeded_pipeline["p2_tok"]),
            )
            assert zone_resp.status_code == 200
            level = zone_resp.get_json()["data"]["level"]
            assert level != "CRITICAL", (
                f"Zone went CRITICAL — p1's stale count=9 was ingested despite disconnect (Bug 1 not fixed)"
            )
        finally:
            if p1.is_connected():
                p1.disconnect()
            if p2.is_connected():
                p2.disconnect()
            manager.stop(timeout=3.0)
            manager._worker_delay_ms = 0.0

    def test_same_socket_stream_restart_with_reset_discards_pending_old_result(
        self, app, client, seeded_pipeline
    ):
        """Submit a delayed high-count frame, then restart the same source on the same socket
        with reset=True, seq=1, and a low-count frame while the older request is still pending.
        The pending previous-stream result must be superseded so it neither reaches the client,
        contaminates the restarted smoothing buffer, nor creates an alert from old data.
        """
        from app.container import get_container

        with app.app_context():
            manager = get_container().detection_manager

        old_delay = manager._worker_delay_ms
        manager._worker_delay_ms = 350.0
        manager.start(app)
        assert manager.wait_until_ready(timeout=5.0)

        source_id = seeded_pipeline["source"]["id"]
        zone_id = seeded_pipeline["zone"]["id"]
        jpeg = make_test_jpeg(640, 480)
        p1 = _sio_client(app, seeded_pipeline["p1_tok"])
        p1.get_received()

        try:
            # 1. Old stream submits high-count frame (9 >= CRITICAL 5) that stalls 350ms in worker
            manager.set_fake_count(source_id, 9)
            p1.emit(
                "frame:submit",
                {"source_id": source_id, "seq": 1, "width": 640, "height": 480, "image": jpeg},
            )
            # Let worker dequeue request #1 and begin sleeping before changing FakeDetector count
            time.sleep(0.08)

            # 2. Same socket restarts source with reset=True, seq=1, low count=1 while #1 is pending
            manager.set_fake_count(source_id, 1)
            p1.emit(
                "frame:submit",
                {
                    "source_id": source_id,
                    "seq": 1,
                    "reset": True,
                    "width": 640,
                    "height": 480,
                    "image": jpeg,
                },
            )

            # Wait long enough for BOTH worker executions (~700ms) to complete
            first_res = _wait_for_events(p1, "frame:result", min_count=1, timeout=4.0)
            time.sleep(0.4)
            extra_res = [e["args"][0] for e in p1.get_received() if e["name"] == "frame:result"]
            all_results = first_res + extra_res

            # Client must receive ONLY the restarted stream's low-count result (never stale count=9)
            assert len(all_results) == 1, (
                f"Expected only restarted frame:result, got {all_results}"
            )
            r = all_results[0]
            assert r["ok"] is True
            assert r["seq"] == 1
            assert r["count"] == 1
            assert r["smoothed_count"] == 1.0
            assert r["level"] == "SAFE"

            # Verify no alert (open or auto-cleared) was ever created by old count=9
            alerts_resp = client.get(
                "/api/v1/alerts", headers=_auth(seeded_pipeline["p1_tok"])
            )
            assert alerts_resp.status_code == 200
            assert alerts_resp.get_json()["data"] == [], (
                f"Stale pre-restart result created unexpected alert(s): {alerts_resp.get_json()['data']}"
            )

            # Inspect ZoneEngine internal state directly: smoother holds only [1.0], level is SAFE
            with manager._engine_lock:
                src_state = manager.engine._sources.get(source_id)
                assert src_state is not None
                assert list(src_state.smoother._buf) == [1.0], (
                    f"Smoother contaminated by previous stream: {list(src_state.smoother._buf)}"
                )
                assert manager.engine._open_alerts.get(zone_id) is None
                eng_zone = manager.engine.get_zone_state(zone_id, manager._clock.utcnow())
                assert eng_zone is not None
                assert eng_zone["level"] == "SAFE"
                assert eng_zone["count"] == 1.0
        finally:
            if p1.is_connected():
                p1.disconnect()
            manager.stop(timeout=3.0)
            manager._worker_delay_ms = old_delay


class TestBug2PingPongCorrelation:
    """Regression for Bug 2: shared _pong_event lets a late Pong satisfy a later probe.

    Fix: each check_health() call gets a unique ping_id; Pong is routed to the
    matching waiter only. A late Pong (ping_id=N) cannot set the event for probe N+1.
    """

    def test_concurrent_health_probes_do_not_steal_pong(
        self, app, seeded_pipeline
    ):
        """A late Pong from a timed-out Ping #1 must NOT satisfy Ping #2.

        Queue layout with worker_delay_ms=250:
          1. Start slow detect_once ts1 (250 ms)
          2. Call h1 = check_health(timeout=0.02) -> Ping #1 queues behind ts1 and times out (False)
          3. Start slow detect_once ts2 (250 ms) behind Ping #1
          4. At t~220ms (just before ts1 finishes and Ping #1 emits Pong #1), call h2 = check_health(timeout=0.14).
             Pong #1 arrives at ~250ms while Ping #2 is STILL stuck behind ts2 (~500ms).
             With shared _pong_event, h2 returned ("ready", True) at ~250ms!
             With per-probe ping_id, h2 ignores Pong #1 and times out ("ready", False).
        """
        import threading
        from app.container import get_container

        with app.app_context():
            manager = get_container().detection_manager

        manager._worker_delay_ms = 250.0
        manager.start(app)
        assert manager.wait_until_ready(timeout=5.0)
        jpeg = make_test_jpeg(640, 480)

        def slow_detect() -> None:
            with app.app_context():
                manager.detect_once(jpeg, timeout=4.0)

        try:
            ts1 = threading.Thread(target=slow_detect, daemon=True)
            ts1.start()
            time.sleep(0.03)  # Ensure ts1 is picked up by worker

            # Probe 1 queues behind ts1 and times out cleanly
            status1, alive1 = manager.check_health(timeout=0.02)
            assert status1 == "ready"
            assert alive1 is False

            # Queue ts2 behind Ping #1
            ts2 = threading.Thread(target=slow_detect, daemon=True)
            ts2.start()
            time.sleep(0.18)  # ~210ms elapsed; ts1 finishes at ~250ms -> Pong #1 emits during h2 wait!

            # Probe 2 queues behind ts2; timeout 0.14s expires before ts2 finishes (~500ms),
            # so Pong #1 (~250ms) arrives right inside h2's wait window!
            status2, alive2 = manager.check_health(timeout=0.14)
            assert status2 == "ready"
            assert alive2 is False, (
                "Probe #2 returned alive=True early — Ping #1's late Pong satisfied Probe #2 (Bug 2 not fixed)"
            )

            ts1.join(timeout=4.0)
            ts2.join(timeout=4.0)

            # Once queue clears, a fresh health probe succeeds
            status3, alive3 = manager.check_health(timeout=1.0)
            assert status3 == "ready"
            assert alive3 is True
        finally:
            manager.stop(timeout=3.0)
            manager._worker_delay_ms = 0.0


class TestFix3MandatoryWidthHeight:
    """Regression for Fix 3: missing or invalid width/height silently accepted.

    Fix: events.py explicitly validates width and height before validate_jpeg_frame().
    """

    def test_missing_width_returns_bad_image(
        self, app, seeded_pipeline, running_worker
    ):
        source_id = seeded_pipeline["source"]["id"]
        jpeg = make_test_jpeg(640, 480)
        p1 = _sio_client(app, seeded_pipeline["p1_tok"])
        p1.get_received()
        try:
            # No width field
            p1.emit(
                "frame:submit",
                {"source_id": source_id, "seq": 14, "height": 480, "image": jpeg},
            )
            r = _wait_for_events(p1, "frame:result", min_count=1, timeout=3.0)
            assert len(r) == 1
            assert r[0]["ok"] is False
            assert r[0]["error"] == "BAD_IMAGE", (
                f"Expected BAD_IMAGE for missing width, got {r[0]['error']!r} (Fix 3 not applied)"
            )
        finally:
            p1.disconnect()

    def test_missing_height_returns_bad_image(
        self, app, seeded_pipeline, running_worker
    ):
        source_id = seeded_pipeline["source"]["id"]
        jpeg = make_test_jpeg(640, 480)
        p1 = _sio_client(app, seeded_pipeline["p1_tok"])
        p1.get_received()
        try:
            # No height field
            p1.emit(
                "frame:submit",
                {"source_id": source_id, "seq": 15, "width": 640, "image": jpeg},
            )
            r = _wait_for_events(p1, "frame:result", min_count=1, timeout=3.0)
            assert len(r) == 1
            assert r[0]["ok"] is False
            assert r[0]["error"] == "BAD_IMAGE"
        finally:
            p1.disconnect()

    def test_bool_width_returns_bad_image(
        self, app, seeded_pipeline, running_worker
    ):
        """bool is a subclass of int in Python; True must not be accepted as width=1."""
        source_id = seeded_pipeline["source"]["id"]
        jpeg = make_test_jpeg(640, 480)
        p1 = _sio_client(app, seeded_pipeline["p1_tok"])
        p1.get_received()
        try:
            p1.emit(
                "frame:submit",
                {"source_id": source_id, "seq": 16, "width": True, "height": 480, "image": jpeg},
            )
            r = _wait_for_events(p1, "frame:result", min_count=1, timeout=3.0)
            assert len(r) == 1
            assert r[0]["ok"] is False
            assert r[0]["error"] == "BAD_IMAGE"
        finally:
            p1.disconnect()

    def test_zero_width_returns_bad_image(
        self, app, seeded_pipeline, running_worker
    ):
        source_id = seeded_pipeline["source"]["id"]
        jpeg = make_test_jpeg(640, 480)
        p1 = _sio_client(app, seeded_pipeline["p1_tok"])
        p1.get_received()
        try:
            p1.emit(
                "frame:submit",
                {"source_id": source_id, "seq": 17, "width": 0, "height": 480, "image": jpeg},
            )
            r = _wait_for_events(p1, "frame:result", min_count=1, timeout=3.0)
            assert len(r) == 1
            assert r[0]["ok"] is False
            assert r[0]["error"] == "BAD_IMAGE"
        finally:
            p1.disconnect()


class TestOverlappingDetectOnce:
    """Verify two concurrent detect_once() calls each receive their own result."""

    def test_overlapping_detect_once_each_gets_own_result(
        self, app, seeded_pipeline, running_worker
    ):
        import threading
        from app.core.errors import DetectorUnavailable

        jpeg = make_test_jpeg(640, 480)
        results: list[tuple[int, bool]] = []

        def run_once(count: int) -> None:
            running_worker.set_fake_count(-1, count)
            with app.app_context():
                try:
                    res = running_worker.detect_once(jpeg, timeout=5.0)
                    results.append((res.count, True))
                except DetectorUnavailable:
                    results.append((-1, False))

        t1 = threading.Thread(target=run_once, args=(3,), daemon=True)
        t2 = threading.Thread(target=run_once, args=(3,), daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=8.0)
        t2.join(timeout=8.0)

        assert len(results) == 2
        for count, ok in results:
            assert ok is True, f"detect_once failed: count={count}"
            assert count == 3

    def test_overlapping_detect_once_one_times_out_other_succeeds(
        self, app, seeded_pipeline
    ):
        """If one overlapping detect_once times out, the other still receives its own result."""
        import threading
        from app.container import get_container
        from app.core.errors import DetectorUnavailable

        with app.app_context():
            manager = get_container().detection_manager

        manager._worker_delay_ms = 250.0
        manager.start(app)
        assert manager.wait_until_ready(timeout=5.0)
        jpeg = make_test_jpeg(640, 480)
        manager.set_fake_count(-1, 5)

        out_fast: list[str] = []
        out_slow: list[tuple[int, int]] = []

        def call_timeout() -> None:
            with app.app_context():
                try:
                    manager.detect_once(jpeg, timeout=0.05)
                    out_fast.append("unexpected_ok")
                except DetectorUnavailable:
                    out_fast.append("timed_out")

        def call_wait() -> None:
            with app.app_context():
                res = manager.detect_once(jpeg, timeout=4.0)
                out_slow.append((res.seq, res.count))

        try:
            t1 = threading.Thread(target=call_timeout, daemon=True)
            t2 = threading.Thread(target=call_wait, daemon=True)
            t1.start()
            t2.start()
            t1.join(timeout=5.0)
            t2.join(timeout=5.0)

            assert out_fast == ["timed_out"]
            assert len(out_slow) == 1
            assert out_slow[0][1] == 5
        finally:
            manager.stop(timeout=3.0)
            manager._worker_delay_ms = 0.0


class TestAdditionalEdgeAndLifecycleCases:
    """Cover pending-request cleanup on worker kill, /health during recovery, 30s reset, and TESTING=False startup."""

    def test_worker_kill_with_pending_requests_cleanup_and_recovery_health(
        self, app, client, seeded_pipeline
    ):
        """Killing the worker mid-flight cleans up inflight frame:submit and detect_once waiters,
        reports unavailable/loading on /health during backoff, and recovers cleanly.
        """
        import threading
        from app.container import get_container
        from app.core.errors import DetectorUnavailable

        with app.app_context():
            manager = get_container().detection_manager

        old_delay = manager._worker_delay_ms
        old_backoffs = manager._restart_backoffs
        manager._worker_delay_ms = 500.0
        manager._restart_backoffs = (0.4, 0.4, 0.4)
        manager.start(app)
        assert manager.wait_until_ready(timeout=5.0)

        source_id = seeded_pipeline["source"]["id"]
        jpeg = make_test_jpeg(640, 480)
        p1 = _sio_client(app, seeded_pipeline["p1_tok"])
        p1.get_received()
        once_outcome: list[str] = []

        def run_once() -> None:
            with app.app_context():
                try:
                    manager.detect_once(jpeg, timeout=4.0)
                    once_outcome.append("ok")
                except DetectorUnavailable:
                    once_outcome.append("unavailable")

        try:
            # Submit both a streaming frame and a synchronous detect_once
            p1.emit(
                "frame:submit",
                {"source_id": source_id, "seq": 1, "width": 640, "height": 480, "image": jpeg},
            )
            t_once = threading.Thread(target=run_once, daemon=True)
            t_once.start()
            time.sleep(0.08)

            old_pid = manager.worker_pid
            assert old_pid is not None
            os.kill(old_pid, signal.SIGTERM)

            # During the 0.4s restart backoff window, supervisor marks detector unavailable
            deadline = time.monotonic() + 2.0
            saw_unavailable_health = False
            while time.monotonic() < deadline:
                h = client.get("/api/v1/health").get_json()
                if h["detector"] in ("unavailable", "loading") and h["worker_alive"] is False:
                    saw_unavailable_health = True
                    break
                time.sleep(0.02)
            assert saw_unavailable_health is True

            # Pending waiters must fail fast with DETECTOR_UNAVAILABLE rather than hanging
            t_once.join(timeout=3.0)
            assert once_outcome == ["unavailable"]

            res_stream = _wait_for_events(p1, "frame:result", min_count=1, timeout=3.0)
            assert len(res_stream) == 1
            assert res_stream[0]["ok"] is False
            assert res_stream[0]["error"] == "DETECTOR_UNAVAILABLE"

            # Wait for automatic recovery
            rec_deadline = time.monotonic() + 5.0
            while time.monotonic() < rec_deadline:
                if manager.worker_pid is not None and manager.worker_pid != old_pid and manager.detector_status == "ready":
                    break
                time.sleep(0.05)

            assert manager.worker_pid is not None and manager.worker_pid != old_pid
            h_after = client.get("/api/v1/health").get_json()
            assert h_after["detector"] == "ready"
            assert h_after["worker_alive"] is True
        finally:
            if p1.is_connected():
                p1.disconnect()
            manager.stop(timeout=3.0)
            manager._worker_delay_ms = old_delay
            manager._restart_backoffs = old_backoffs

    def test_30s_inactivity_reset_clears_engine_smoother(
        self, app, seeded_pipeline, running_worker
    ):
        """After 30s without frames, submit_frame sets reset=True so ZoneEngine clears smoothing buffer."""
        from app.detection.tracker import INACTIVITY_RESET_S

        source_id = seeded_pipeline["source"]["id"]
        jpeg = make_test_jpeg(640, 480)
        p1 = _sio_client(app, seeded_pipeline["p1_tok"])
        p1.get_received()

        try:
            running_worker.set_fake_count(source_id, 10)
            for seq in (1, 2):
                p1.emit(
                    "frame:submit",
                    {"source_id": source_id, "seq": seq, "width": 640, "height": 480, "image": jpeg},
                )
            res_hi = _wait_for_events(p1, "frame:result", min_count=2, timeout=4.0)
            assert res_hi[-1]["smoothed_count"] == 10.0

            # Jump last-submitted timestamp past INACTIVITY_RESET_S (30s) and switch count to 0.
            # Without the 30s inactivity reset, median([10, 10, 0]) would stay 10.0.
            running_worker.set_fake_count(source_id, 0)
            with running_worker._pipeline_lock:
                running_worker._source_last_submitted_mono[source_id] -= (INACTIVITY_RESET_S + 2.0)

            p1.emit(
                "frame:submit",
                {"source_id": source_id, "seq": 3, "width": 640, "height": 480, "image": jpeg},
            )
            res_after = _wait_for_events(p1, "frame:result", min_count=1, timeout=4.0)
            assert len(res_after) == 1
            assert res_after[0]["ok"] is True
            assert res_after[0]["smoothed_count"] == 0.0
            assert res_after[0]["level"] == "SAFE"
        finally:
            p1.disconnect()

    def test_normal_startup_outside_testing_mode_clean_shutdown(self):
        """Boot app with TESTING=False against a temp SQLite DB and verify worker starts & stops cleanly."""
        from app import create_app
        from app.extensions import db
        from app.realtime.tasks import stop_background_loop

        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "prod_boot.db").replace("\\", "/")
            db_uri = f"sqlite:///{db_path}"

            boot_app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": db_uri})
            with boot_app.app_context():
                db.create_all()
                db.session.remove()
                db.engine.dispose()

            prod_app = create_app(
                {
                    "TESTING": False,
                    "SQLALCHEMY_DATABASE_URI": db_uri,
                    "RATELIMIT_ENABLED": False,
                }
            )
            pmgr = prod_app.extensions["container"].detection_manager
            proc = pmgr._process
            try:
                assert proc is not None
                assert pmgr.wait_until_ready(timeout=6.0) is True
                hc = prod_app.test_client().get("/api/v1/health").get_json()
                assert hc["detector"] == "ready"
                assert hc["worker_alive"] is True
            finally:
                stop_background_loop(prod_app)
                pmgr.stop(timeout=3.0)
                with prod_app.app_context():
                    db.session.remove()
                    db.engine.dispose()
            assert not proc.is_alive()
            assert proc.exitcode is not None
