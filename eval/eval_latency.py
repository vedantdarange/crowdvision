"""eval/eval_latency.py — End-to-end detection & pipeline latency benchmark (plan §8.2 / B5b).

Sends N frames from a folder of images or a video file through the real spawned
detection worker (`frame:submit` -> worker YOLO inference -> `ZoneEngine` -> `frame:result`),
reporting warm-up time, per-frame counts, `infer_ms`, and end-to-end capture->result
p50 / p95 latencies.

Usage (from repo root or backend/):
    backend/.venv/Scripts/python.exe eval/eval_latency.py --input path/to/frames_or_video --frames 20
"""
from __future__ import annotations

import argparse
import os
import platform
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
MAX_FRAME_BYTES = 300 * 1024


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * (pct / 100.0)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _encode_bgr_to_jpeg(frame: Any, *, max_width: int = 640, quality: int = 70) -> tuple[bytes, int, int]:
    import cv2

    h, w = int(frame.shape[0]), int(frame.shape[1])
    if w > max_width:
        scale = max_width / float(w)
        new_w = max_width
        new_h = max(1, int(round(h * scale)))
        frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
        h, w = new_h, new_w

    q = int(quality)
    while q >= 30:
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), q])
        if ok and len(buf) <= MAX_FRAME_BYTES:
            return buf.tobytes(), w, h
        q -= 10
    raise RuntimeError("Could not encode frame under 300 KB limit.")


def _load_frames(
    input_path: Path, max_frames: int, *, max_width: int = 640
) -> list[tuple[str, bytes, int, int]]:
    import cv2

    if not input_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")

    encoded: list[tuple[str, bytes, int, int]] = []
    if input_path.is_dir():
        files = sorted(
            p for p in input_path.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS
        )
        if not files:
            raise ValueError(f"No image files found in directory: {input_path}")
        raw_frames: list[tuple[str, bytes, int, int]] = []
        for p in files:
            img = cv2.imread(str(p))
            if img is None:
                continue
            jpg, w, h = _encode_bgr_to_jpeg(img, max_width=max_width)
            raw_frames.append((p.name, jpg, w, h))
        if not raw_frames:
            raise ValueError(f"Could not decode any images in directory: {input_path}")
        for idx in range(max_frames):
            name, jpg, w, h = raw_frames[idx % len(raw_frames)]
            encoded.append((f"{name}#{idx + 1}", jpg, w, h))
        return encoded

    if input_path.suffix.lower() in IMAGE_EXTS:
        img = cv2.imread(str(input_path))
        if img is None:
            raise ValueError(f"Could not decode image: {input_path}")
        jpg, w, h = _encode_bgr_to_jpeg(img, max_width=max_width)
        return [(f"{input_path.name}#{i + 1}", jpg, w, h) for i in range(max_frames)]

    if input_path.suffix.lower() in VIDEO_EXTS:
        cap = cv2.VideoCapture(str(input_path))
        if not cap.isOpened():
            raise RuntimeError(f"Failed to open video file: {input_path}")
        try:
            idx = 0
            while len(encoded) < max_frames:
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                idx += 1
                jpg, w, h = _encode_bgr_to_jpeg(frame, max_width=max_width)
                encoded.append((f"frame_{idx}", jpg, w, h))
        finally:
            cap.release()
        if not encoded:
            raise ValueError(f"No frames read from video: {input_path}")
        return encoded

    raise ValueError(f"Unsupported input type: {input_path}")


def _default_input_path() -> Path:
    import ultralytics

    return Path(ultralytics.__file__).resolve().parent / "assets"


def _default_model_path() -> str:
    env_val = os.environ.get("MODEL_PATH", "").strip()
    if env_val:
        return env_val
    for candidate in (REPO_ROOT / "people_model.pt", REPO_ROOT / "docs" / "model" / "best.pt"):
        if candidate.is_file():
            return str(candidate)
    return "docs/model/best.pt"


def _run_frame_latency(args: argparse.Namespace) -> int:
    # Configure environment before importing Flask app
    os.environ["FLASK_ENV"] = "testing"
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    os.environ["SECRET_KEY"] = "eval-secret-key-0123456789abcdef"
    os.environ["JWT_SECRET_KEY"] = "eval-jwt-secret-key-0123456789abcdef"
    os.environ["DETECTOR_BACKEND"] = args.backend
    os.environ["MODEL_PATH"] = args.model
    os.environ["USE_TRACKER"] = "true" if args.use_tracker else "false"

    from argon2 import PasswordHasher
    from flask_jwt_extended import create_access_token
    from flask_socketio import SocketIOTestClient

    from app import create_app
    from app.extensions import db, socketio
    from app.models.models import User

    input_path = Path(args.input) if args.input else _default_input_path()
    frames = _load_frames(input_path, args.frames, max_width=args.imgsz)

    flask_app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "RATELIMIT_ENABLED": False,
        }
    )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with flask_app.app_context():
        db.create_all()
        ph = PasswordHasher()
        admin = User(
            name="Eval Admin",
            email="eval_admin@test.local",
            password_hash=ph.hash("EvalPass@123"),
            role="admin",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db.session.add(admin)
        db.session.commit()
        tok = create_access_token(identity=str(admin.id), additional_claims={"role": "admin"})

    client = flask_app.test_client()
    headers = {"Authorization": f"Bearer {tok}"}

    settings_resp = client.patch(
        "/api/v1/settings",
        json={"detect_conf": args.conf, "frame_width": args.imgsz, "debounce_s": 0, "clear_s": 0},
        headers=headers,
    )
    if settings_resp.status_code != 200:
        body = settings_resp.get_json(silent=True) or settings_resp.get_data(as_text=True)
        print(f"Benchmark setup failed: PATCH /api/v1/settings returned {settings_resp.status_code}: {body}", file=sys.stderr)
        return 1
    eff_settings = settings_resp.get_json()["data"]
    eff_conf = float(eff_settings["detect_conf"])
    eff_imgsz = int(eff_settings["frame_width"])

    zone_resp = client.post(
        "/api/v1/zones",
        json={
            "name": "Eval Zone",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[77.209, 28.6139], [77.2094, 28.6139], [77.2094, 28.6143], [77.209, 28.6143], [77.209, 28.6139]]],
            },
            "mode": "COUNT",
            "warning_count": 3,
            "critical_count": 5,
        },
        headers=headers,
    )
    if zone_resp.status_code not in (200, 201):
        body = zone_resp.get_json(silent=True) or zone_resp.get_data(as_text=True)
        print(f"Benchmark setup failed: POST /api/v1/zones returned {zone_resp.status_code}: {body}", file=sys.stderr)
        return 1
    zone_id = zone_resp.get_json()["data"]["id"]

    src_resp = client.post(
        "/api/v1/sources",
        json={"zone_id": zone_id, "name": "Eval Cam", "kind": "VIDEO_FILE"},
        headers=headers,
    )
    if src_resp.status_code not in (200, 201):
        body = src_resp.get_json(silent=True) or src_resp.get_data(as_text=True)
        print(f"Benchmark setup failed: POST /api/v1/sources returned {src_resp.status_code}: {body}", file=sys.stderr)
        return 1
    source_id = src_resp.get_json()["data"]["id"]

    manager = flask_app.extensions["container"].detection_manager
    t_boot0 = time.perf_counter()
    manager.start(flask_app)
    if not manager.wait_until_ready(timeout=20.0):
        manager.stop(timeout=3.0)
        raise RuntimeError("Detection worker failed to become ready within 20s.")
    worker_ready_ms = (time.perf_counter() - t_boot0) * 1000.0

    health = client.get("/api/v1/health").get_json()
    sio = SocketIOTestClient(flask_app, socketio, auth={"token": tok})
    sio.get_received()

    submitted = 0
    succeeded = 0
    busy_dropped = 0
    other_failed = 0
    timed_out = 0
    error_counts: Counter[str] = Counter()

    infer_ms_list: list[float] = []
    e2e_ms_list: list[float] = []
    counts_by_label: list[tuple[str, int, float, float]] = []
    first_frame_stat: tuple[str, str, int | None, float | None, float | None] | None = None

    try:
        for seq, (label, jpg, w, h) in enumerate(frames, start=1):
            submitted += 1
            t0 = time.perf_counter()
            sio.emit(
                "frame:submit",
                {
                    "source_id": source_id,
                    "seq": seq,
                    "reset": (seq == 1),
                    "width": w,
                    "height": h,
                    "image": jpg,
                },
            )
            matched: dict[str, Any] | None = None
            deadline = time.monotonic() + float(args.timeout)
            while time.monotonic() < deadline and matched is None:
                for ev in sio.get_received():
                    if ev["name"] == "frame:result" and ev["args"]:
                        payload = ev["args"][0]
                        # Match strictly on seq so a late result from a timed-out frame
                        # is never attributed to a later frame.
                        if payload.get("seq") == seq:
                            matched = payload
                            break
                if matched is None:
                    time.sleep(0.005)
            e2e_ms = (time.perf_counter() - t0) * 1000.0

            if matched is None:
                timed_out += 1
                if seq == 1:
                    first_frame_stat = (label, "TIMEOUT", None, None, None)
                continue

            if not matched.get("ok"):
                err_code = str(matched.get("error") or "UNKNOWN")
                error_counts[err_code] += 1
                if err_code == "DETECTOR_BUSY":
                    busy_dropped += 1
                else:
                    other_failed += 1
                if seq == 1:
                    first_frame_stat = (label, f"ERROR({err_code})", None, None, None)
                continue

            succeeded += 1
            inf_ms = float(matched["infer_ms"])
            cnt = int(matched["count"])
            infer_ms_list.append(inf_ms)
            e2e_ms_list.append(e2e_ms)
            counts_by_label.append((label, cnt, inf_ms, e2e_ms))
            if seq == 1:
                first_frame_stat = (label, "OK", cnt, inf_ms, e2e_ms)
    finally:
        if sio.is_connected():
            sio.disconnect()
        manager.stop(timeout=3.0)

    assert submitted == succeeded + busy_dropped + other_failed + timed_out

    print("=== CrowdVision Pipeline Latency Evaluation (in-process submit-to-result) ===")
    print(f"Platform:        {platform.platform()} | CPU: {platform.processor()}")
    print(
        f"Backend:         {args.backend} | Model: {args.model} | "
        f"effective_imgsz={eff_imgsz} | effective_conf={eff_conf} | use_tracker={args.use_tracker}"
    )
    print(f"Transport:       SocketIOTestClient (in-process; browser capture & WebSocket not included)")
    print(f"Input:           {input_path} ({len(frames)} frames)")
    print(f"Health on boot:  {health}")
    print(f"Worker startup:  {worker_ready_ms:.1f} ms (spawn + YOLO load + blank warm-up)")
    partial_tag = " [PARTIAL RUN]" if succeeded < submitted else ""
    print(
        f"Frames{partial_tag}: submitted={submitted} | succeeded={succeeded} | "
        f"busy_dropped={busy_dropped} | other_failed={other_failed} | timed_out={timed_out}"
    )
    if error_counts:
        print(f"Error breakdown: {dict(error_counts)}")
    if first_frame_stat is not None:
        flbl, fstatus, fcnt, fims, fems = first_frame_stat
        if fstatus == "OK":
            print(f"First frame:     {flbl} -> count={fcnt}, infer_ms={fims:.2f}, in_process_e2e_ms={fems:.2f}")
        else:
            print(f"First frame:     {flbl} -> {fstatus}")

    if succeeded == 0:
        print("No successful frames (sample_size=0) — latency percentiles omitted.")
        return 1

    print("Sample detections:")
    for lbl, cnt, ims, ems in counts_by_label[: min(5, len(counts_by_label))]:
        print(f"  - {lbl}: count={cnt}, infer_ms={ims:.2f}, in_process_e2e_ms={ems:.2f}")

    s_inf = sorted(infer_ms_list)
    s_e2e = sorted(e2e_ms_list)
    p50_inf = _percentile(s_inf, 50)
    p95_inf = _percentile(s_inf, 95)
    p50_e2e = _percentile(s_e2e, 50)
    p95_e2e = _percentile(s_e2e, 95)
    print(
        f"infer_ms (sample_size={succeeded}): min={s_inf[0]:.2f} | p50={p50_inf:.2f} | "
        f"p95={p95_inf:.2f} | max={s_inf[-1]:.2f}"
    )
    print(
        f"in_process_e2e_ms (sample_size={succeeded}): min={s_e2e[0]:.2f} | p50={p50_e2e:.2f} | "
        f"p95={p95_e2e:.2f} | max={s_e2e[-1]:.2f}"
    )
    print(f"Target (<1500ms p95 in-process submit-to-result): {'PASS' if p95_e2e < 1500.0 else 'MISS'}")
    return 0


def run_alert_latency_benchmark(args: argparse.Namespace) -> int:
    """Measure alert latency from metric crossing threshold to `alert:new` at police Socket.IO client."""
    os.environ["FLASK_ENV"] = "testing"
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    os.environ["DETECTOR_BACKEND"] = str(args.backend)
    os.environ["MODEL_PATH"] = str(args.model)
    os.environ["USE_TRACKER"] = "true" if args.use_tracker else "false"

    from argon2 import PasswordHasher
    from flask_jwt_extended import create_access_token
    from flask_socketio import SocketIOTestClient

    from app import create_app
    from app.extensions import db, socketio
    from app.models.models import User

    flask_app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "RATELIMIT_ENABLED": False,
        }
    )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with flask_app.app_context():
        db.create_all()
        ph = PasswordHasher()
        admin = User(
            name="Alert Admin",
            email="alert_admin@test.local",
            password_hash=ph.hash("EvalPass@123"),
            role="admin",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        police = User(
            name="Alert Police",
            email="alert_police@test.local",
            password_hash=ph.hash("EvalPass@123"),
            role="police",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db.session.add_all([admin, police])
        db.session.commit()
        admin_tok = create_access_token(identity=str(admin.id), additional_claims={"role": "admin"})
        police_tok = create_access_token(identity=str(police.id), additional_claims={"role": "police"})

    client = flask_app.test_client()
    headers = {"Authorization": f"Bearer {admin_tok}"}
    client.patch(
        "/api/v1/settings",
        json={
            "detect_conf": args.conf,
            "frame_width": args.imgsz,
            "smoothing_window": 1,
            "debounce_s": 0,
            "clear_s": 0,
        },
        headers=headers,
    )

    container = flask_app.extensions["container"]
    manager = container.detection_manager
    manager.start(flask_app)
    if not manager.wait_until_ready(timeout=20.0):
        manager.stop(timeout=3.0)
        raise RuntimeError("Detection worker failed to become ready within 20s.")

    police_sio = SocketIOTestClient(flask_app, socketio, auth={"token": police_tok})
    admin_sio = SocketIOTestClient(flask_app, socketio, auth={"token": admin_tok})
    police_sio.get_received()
    admin_sio.get_received()

    trials = max(1, int(args.alert_trials))
    dispatch_latencies_ms: list[float] = []
    frame_to_alert_ms: list[float] = []

    try:
        # 1. Scripted threshold-crossing alert dispatch latency across distinct zones
        with flask_app.app_context():
            t_clock = datetime.now(timezone.utc)
        for i in range(1, trials + 1):
            z_resp = client.post(
                "/api/v1/zones",
                json={
                    "name": f"Alert Latency Zone {i}",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[77.209, 28.6139], [77.2094, 28.6139], [77.2094, 28.6143], [77.209, 28.6143], [77.209, 28.6139]]],
                    },
                    "mode": "COUNT",
                    "warning_count": 5,
                    "critical_count": 10,
                },
                headers=headers,
            )
            zid = z_resp.get_json()["data"]["id"]
            s_resp = client.post(
                "/api/v1/sources",
                json={"zone_id": zid, "name": f"Alert Cam {i}", "kind": "VIDEO_FILE"},
                headers=headers,
            )
            sid_src = s_resp.get_json()["data"]["id"]

            with flask_app.app_context():
                # Establish baseline NORMAL state
                manager.ingest_count(sid_src, count=1, now=t_clock + timedelta(seconds=i * 10))
                police_sio.get_received()

                t0 = time.perf_counter()
                manager.ingest_count(sid_src, count=8, now=t_clock + timedelta(seconds=i * 10 + 1))

            received_alert = False
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and not received_alert:
                for ev in police_sio.get_received():
                    if ev["name"] == "alert:new" and ev["args"]:
                        if ev["args"][0].get("zone_id") == zid:
                            received_alert = True
                            break
                if not received_alert:
                    time.sleep(0.001)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            if received_alert:
                dispatch_latencies_ms.append(elapsed_ms)

        # 2. Optional full frame:submit -> worker infer -> alert:new latency if an image exists
        input_path = Path(args.input) if args.input else _default_input_path()
        frames = _load_frames(input_path, 1) if input_path.exists() else []
        if frames:
            lbl, jpg, w, h = frames[0]
            z_resp = client.post(
                "/api/v1/zones",
                json={
                    "name": "Frame-to-Alert Zone",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[77.209, 28.6139], [77.2094, 28.6139], [77.2094, 28.6143], [77.209, 28.6143], [77.209, 28.6139]]],
                    },
                    "mode": "COUNT",
                    "warning_count": 1,
                    "critical_count": 2,
                },
                headers=headers,
            )
            fzid = z_resp.get_json()["data"]["id"]
            s_resp = client.post(
                "/api/v1/sources",
                json={"zone_id": fzid, "name": "Frame Alert Cam", "kind": "VIDEO_FILE"},
                headers=headers,
            )
            fsid = s_resp.get_json()["data"]["id"]
            if args.backend == "fake":
                manager.set_fake_count(fsid, 5)
            police_sio.get_received()
            t0 = time.perf_counter()
            admin_sio.emit(
                "frame:submit",
                {
                    "source_id": fsid,
                    "seq": 1,
                    "reset": True,
                    "width": w,
                    "height": h,
                    "image": jpg,
                },
            )
            got_frame_alert = False
            deadline = time.monotonic() + float(args.timeout)
            while time.monotonic() < deadline and not got_frame_alert:
                for ev in police_sio.get_received():
                    if ev["name"] == "alert:new" and ev["args"]:
                        if ev["args"][0].get("zone_id") == fzid:
                            got_frame_alert = True
                            break
                if not got_frame_alert:
                    time.sleep(0.002)
            if got_frame_alert:
                frame_to_alert_ms.append((time.perf_counter() - t0) * 1000.0)
    finally:
        if police_sio.is_connected():
            police_sio.disconnect()
        if admin_sio.is_connected():
            admin_sio.disconnect()
        manager.stop(timeout=3.0)

    print("\n=== CrowdVision Alert Delivery Latency (threshold cross -> police alert:new) ===")
    if not dispatch_latencies_ms:
        print("FAILED: No alert:new events received on police Socket.IO client.", file=sys.stderr)
        return 1

    s_disp = sorted(dispatch_latencies_ms)
    print(
        f"alert_dispatch_ms (ingest_count cross -> police alert:new, n={len(s_disp)}/{trials}): "
        f"min={s_disp[0]:.2f} | p50={_percentile(s_disp, 50):.2f} | "
        f"p95={_percentile(s_disp, 95):.2f} | max={s_disp[-1]:.2f}"
    )
    if frame_to_alert_ms:
        print(
            f"frame_to_alert_ms (frame:submit -> YOLO infer -> ZoneEngine -> police alert:new, n=1): "
            f"{frame_to_alert_ms[0]:.2f} ms"
        )
    print("Note: Measured with debounce_s=0, smoothing_window=1 so crossing fires immediately without artificial hold delay.")
    return 0


def run_benchmark(args: argparse.Namespace) -> int:
    rc = 0
    if args.mode in ("frame", "all"):
        rc = _run_frame_latency(args)
        if rc != 0:
            return rc
    if args.mode in ("alert", "all"):
        rc = run_alert_latency_benchmark(args)
    return rc


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate real detection, pipeline & alert latency.")
    parser.add_argument("--mode", default="all", choices=["frame", "alert", "all"], help="Which latency suite to run.")
    parser.add_argument("--input", default="", help="Folder of images, single image, or video file.")
    parser.add_argument("--frames", type=int, default=20, help="Number of frames to submit.")
    parser.add_argument("--alert-trials", type=int, default=10, help="Number of threshold-cross alert trials.")
    parser.add_argument("--model", default=_default_model_path(), help="Path to YOLO .pt model.")
    parser.add_argument("--backend", default="ultralytics", choices=["ultralytics", "fake"])
    parser.add_argument("--conf", type=float, default=0.35)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-frame result timeout in seconds.")
    parser.add_argument("--use-tracker", action="store_true")
    args = parser.parse_args()
    return run_benchmark(args)


if __name__ == "__main__":
    raise SystemExit(main())
