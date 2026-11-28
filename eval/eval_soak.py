"""eval/eval_soak.py — Long-running soak & leak test (contract §13, B9).

Simulates continuous 1 Hz multi-zone telemetry (all 3 seeded zones on fake feed
plus optional 1 real detection source) alongside the 1 Hz background loop (`run_tick_once`),
sampling main + spawned worker RSS memory, queue depths, in-memory cache sizes,
and thread counts every `--sample-interval-s` seconds into `eval/results/soak.csv`.

Fails loudly (exit code 1) if:
  - Total RSS memory grows by more than `--max-mem-growth-pct` (default 20%) after warm-up
  - Request/result queues or `_inflight` map fail to drain cleanly
  - The detection worker dies unexpectedly during the run

Run from backend venv:
  python eval/eval_soak.py --duration-s 1800 --sample-interval-s 10
  python eval/eval_soak.py --duration-s 60 --sample-interval-s 5 --include-real
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import psutil
from flask_socketio import SocketIOTestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _default_model_path() -> str:
    for candidate in (
        ROOT_DIR / "people_model.pt",
        ROOT_DIR / "docs" / "model" / "best.pt",
        BACKEND_DIR / "docs" / "model" / "best.pt",
    ):
        if candidate.is_file():
            return str(candidate)
    return str(ROOT_DIR / "people_model.pt")


def _default_real_input() -> Path | None:
    for candidate in (
        ROOT_DIR / "eval" / "data" / "crowd-photos-and-videos" / "crowd-video.mp4",
        ROOT_DIR / "eval" / "data" / "crowd-photos-and-videos" / "processed_IMG_1.jpg",
        ROOT_DIR / "crowd-photos-and-videos" / "crowd-video.mp4",
    ):
        if candidate.is_file():
            return candidate
    return None


def _load_real_jpeg(path: Path) -> tuple[bytes, int, int]:
    if path.suffix.lower() in {".mp4", ".avi", ".mov", ".mkv"}:
        cap = cv2.VideoCapture(str(path))
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            raise RuntimeError(f"Failed to read frame from {path}")
    else:
        frame = cv2.imread(str(path))
        if frame is None:
            raise RuntimeError(f"Failed to load image {path}")
    h, w = frame.shape[:2]
    ok_enc, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not ok_enc:
        raise RuntimeError(f"Failed to encode JPEG for {path}")
    return buf.tobytes(), int(w), int(h)


def _rss_mb(pid: int | None) -> float:
    if pid is None or pid <= 0:
        return 0.0
    try:
        proc = psutil.Process(pid)
        return float(proc.memory_info().rss) / (1024.0 * 1024.0)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0.0


def run_soak(args: argparse.Namespace) -> int:
    real_input = Path(args.real_input).resolve() if args.real_input else _default_real_input()
    use_real = bool(args.include_real and real_input is not None and real_input.is_file())
    backend = "ultralytics" if use_real else "fake"

    tmp_dir = tempfile.TemporaryDirectory(prefix="crowdvision_soak_")
    db_file = Path(tmp_dir.name) / "soak.db"

    os.environ["FLASK_ENV"] = "testing"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file.as_posix()}"
    os.environ["SECRET_KEY"] = "soak-secret-key-0123456789abcdef"
    os.environ["JWT_SECRET_KEY"] = "soak-jwt-secret-key-0123456789abcdef"
    os.environ["DETECTOR_BACKEND"] = backend
    os.environ["MODEL_PATH"] = str(args.model)
    os.environ["USE_TRACKER"] = "false"

    from argon2 import PasswordHasher
    from flask_jwt_extended import create_access_token

    from app import create_app
    from app.cli import _seed_settings, _seed_zones
    from app.extensions import db, socketio
    from app.models.models import ZoneSample, User
    from app.realtime.tasks import run_tick_once
    from app.services.engine_sync import reload_engine_from_db

    flask_app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_file.as_posix()}",
            "RATELIMIT_ENABLED": False,
        }
    )

    try:
        with flask_app.app_context():
            db.create_all()
            _seed_settings(db.session)
            _seed_zones(db.session, 28.6139, 77.2090)
            admin = User(
                name="Soak Admin",
                email="soak_admin@test.local",
                password_hash=PasswordHasher().hash("SoakPass@123"),
                role="admin",
                is_active=True,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            db.session.add(admin)
            db.session.commit()
            c_seed = flask_app.extensions["container"]
            with c_seed.engine_lock:
                reload_engine_from_db(
                    zone_engine=c_seed.zone_engine,
                    zone_repo=c_seed.zone_repo,
                    source_repo=c_seed.source_repo,
                    settings_service=c_seed.settings_service,
                )
            tok = create_access_token(
                identity=str(admin.id),
                additional_claims={"role": "admin"},
            )

        client = flask_app.test_client()
        headers = {"Authorization": f"Bearer {tok}"}

        zones = client.get("/api/v1/zones", headers=headers).get_json()["data"]
        sources = client.get("/api/v1/sources", headers=headers).get_json()["data"]
        if len(zones) < 3 or len(sources) < 3:
            print("Expected at least 3 seeded zones and 3 seeded sources for soak.", file=sys.stderr)
            return 1

        # Add a dedicated real source when requested (attached to Zone 1)
        real_source_id: int | None = None
        real_frame: tuple[bytes, int, int] | None = None
        if use_real and real_input is not None:
            real_frame = _load_real_jpeg(real_input)
            s_resp = client.post(
                "/api/v1/sources",
                json={"zone_id": zones[0]["id"], "name": "Soak Real Source", "kind": "VIDEO_FILE"},
                headers=headers,
            )
            if s_resp.status_code in (200, 201):
                real_source_id = int(s_resp.get_json()["data"]["id"])

        container = flask_app.extensions["container"]
        manager = container.detection_manager
        manager.start(flask_app)
        if not manager.wait_until_ready(timeout=25.0):
            manager.stop(timeout=3.0)
            print("Detection worker failed to become ready within 25s.", file=sys.stderr)
            return 1

        sio = SocketIOTestClient(flask_app, socketio, auth={"token": tok})
        sio.get_received()

        duration_s = float(args.duration_s)
        sample_interval_s = max(1.0, float(args.sample_interval_s))
        warmup_s = float(args.warmup_s) if args.warmup_s is not None else min(30.0, duration_s * 0.2)

        main_pid = os.getpid()
        samples: list[dict[str, Any]] = []
        seq = 0
        start_mono = time.monotonic()
        next_sample_at = 0.0
        worker_died = False

        print("=== CrowdVision Long-Running Soak Test ===")
        print(
            f"Duration={duration_s:.0f}s | Sample interval={sample_interval_s:.1f}s | "
            f"Warm-up={warmup_s:.1f}s | Backend={backend} | Real source={real_source_id or 'none'}"
        )

        try:
            tick_idx = 0
            while True:
                elapsed_s = time.monotonic() - start_mono
                if elapsed_s >= duration_s:
                    break

                # 1. Drive fake-feed wave on the 3 seeded zones at 1 Hz
                now_utc = datetime.now(timezone.utc)
                with flask_app.app_context():
                    for z_i, src in enumerate(sources[:3]):
                        # Smooth sine oscillation that occasionally crosses thresholds & clears
                        wave = int(round(12 + 12 * math.sin((tick_idx + z_i * 7) / 8.0)))
                        manager.ingest_count(src["id"], max(0, wave), now=now_utc)

                    # 2. Optional real YOLO inference source submission (~1 Hz)
                    if real_source_id is not None and real_frame is not None:
                        seq += 1
                        jpg, w, h = real_frame
                        sio.emit(
                            "frame:submit",
                            {
                                "source_id": real_source_id,
                                "seq": seq,
                                "reset": (seq == 1),
                                "width": w,
                                "height": h,
                                "image": jpg,
                            },
                        )
                    sio.get_received()

                    # 3. Execute 1 Hz scheduler tick (alerts, zone_samples, pruning)
                    run_tick_once(flask_app, now=now_utc)

                    # 4. Periodic telemetry sampling
                    if elapsed_s >= next_sample_at:
                        rt = manager.runtime_stats()
                        em = container.emitter.stats()
                        main_rss = _rss_mb(main_pid)
                        wrk_rss = _rss_mb(manager.worker_pid)
                        row = {
                            "elapsed_s": round(elapsed_s, 1),
                            "main_rss_mb": round(main_rss, 2),
                            "worker_rss_mb": round(wrk_rss, 2),
                            "total_rss_mb": round(main_rss + wrk_rss, 2),
                            "threads": len(psutil.Process(main_pid).threads()),
                            "inflight": rt["inflight"],
                            "leases": rt["leases"],
                            "throttle_entries": em["throttle_entries"],
                            "request_queue_depth": rt["request_queue_depth"],
                            "result_queue_depth": rt["result_queue_depth"],
                            "worker_alive": int(bool(rt["worker_alive"])),
                            "zone_samples_rows": int(db.session.query(ZoneSample).count()),
                        }
                        samples.append(row)
                        if not rt["worker_alive"]:
                            worker_died = True
                        next_sample_at += sample_interval_s

                tick_idx += 1
                if worker_died:
                    print("FAIL: Detection worker died mid-soak!", file=sys.stderr)
                    break
                time.sleep(1.0)

            # Drain grace window after stopping submissions
            drain_deadline = time.monotonic() + 5.0
            final_rt = manager.runtime_stats()
            while time.monotonic() < drain_deadline:
                sio.get_received()
                final_rt = manager.runtime_stats()
                if (
                    final_rt["inflight"] == 0
                    and max(0, final_rt["request_queue_depth"]) == 0
                    and max(0, final_rt["result_queue_depth"]) == 0
                ):
                    break
                time.sleep(0.2)
        finally:
            if sio.is_connected():
                sio.disconnect()
            manager.stop(timeout=3.0)

        out_path = Path(args.out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if samples:
            with out_path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(samples[0].keys()))
                writer.writeheader()
                writer.writerows(samples)

        if len(samples) < 2:
            print("FAIL: Insufficient soak samples collected.", file=sys.stderr)
            return 1

        post_warmup = [s for s in samples if s["elapsed_s"] >= warmup_s]
        if len(post_warmup) < 2:
            post_warmup = samples[1:]

        baseline_rss = statistics.mean(
            s["total_rss_mb"] for s in post_warmup[: min(3, len(post_warmup))]
        )
        final_rss = post_warmup[-1]["total_rss_mb"]
        peak_rss = max(s["total_rss_mb"] for s in post_warmup)
        rss_growth_pct = (
            ((final_rss - baseline_rss) / baseline_rss * 100.0) if baseline_rss > 0 else 0.0
        )
        peak_growth_pct = (
            ((peak_rss - baseline_rss) / baseline_rss * 100.0) if baseline_rss > 0 else 0.0
        )

        queues_drained = (
            final_rt["inflight"] <= 1
            and max(0, final_rt["request_queue_depth"]) == 0
            and max(0, final_rt["result_queue_depth"]) == 0
        )
        mem_ok = rss_growth_pct <= float(args.max_mem_growth_pct)
        passed = mem_ok and queues_drained and not worker_died

        print(
            f"Samples={len(samples)} | Warm-up baseline RSS={baseline_rss:.2f} MB | "
            f"Final RSS={final_rss:.2f} MB ({rss_growth_pct:+.2f}%) | "
            f"Peak RSS={peak_rss:.2f} MB ({peak_growth_pct:+.2f}%)"
        )
        print(
            f"Final state -> threads: {samples[0]['threads']}->{samples[-1]['threads']} | "
            f"inflight={final_rt['inflight']} | req_q={final_rt['request_queue_depth']} | "
            f"res_q={final_rt['result_queue_depth']} | throttle_entries={samples[-1]['throttle_entries']}"
        )
        print(f"Wrote soak telemetry CSV -> {out_path}")
        print(f"SOAK RESULT: {'PASS' if passed else 'FAIL'}")

        if not mem_ok:
            print(
                f"FAIL: Total RSS grew by {rss_growth_pct:.2f}% > {args.max_mem_growth_pct:.1f}% limit.",
                file=sys.stderr,
            )
        if not queues_drained:
            print(f"FAIL: Worker queues did not drain cleanly: {final_rt}", file=sys.stderr)
        return 0 if passed else 1
    finally:
        with flask_app.app_context():
            db.session.remove()
            db.engine.dispose()
        tmp_dir.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CrowdVision stability soak test.")
    parser.add_argument("--duration-s", type=float, default=1800.0, help="Total soak duration in seconds (default 1800 = 30 min).")
    parser.add_argument("--sample-interval-s", type=float, default=10.0, help="Telemetry sampling period in seconds (default 10).")
    parser.add_argument("--warmup-s", type=float, default=None, help="Warm-up window before RSS baseline (default min(30, 0.2*duration)).")
    parser.add_argument("--max-mem-growth-pct", type=float, default=20.0, help="Fail threshold for post-warmup RSS growth %%.")
    parser.add_argument("--include-real", action="store_true", help="Also run real YOLO detector source alongside 3 fake-feed zones.")
    parser.add_argument("--real-input", default="", help="Video or image path for --include-real.")
    parser.add_argument("--model", default=_default_model_path(), help="Path to YOLO .pt model for --include-real.")
    parser.add_argument("--out", default=str(ROOT_DIR / "eval" / "results" / "soak.csv"), help="Output telemetry CSV.")
    args = parser.parse_args()
    return run_soak(args)


if __name__ == "__main__":
    raise SystemExit(main())
