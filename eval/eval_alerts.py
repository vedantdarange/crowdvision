"""eval/eval_alerts.py — False alarm, missed alarm & flicker evaluation (contract §13, B9).

Replays labelled 1 Hz count series (and optionally raw detector counts extracted
from a real video) through the full `ZoneEngine` (5-frame RollingMedian, 0.85x
hysteresis, 3 s trigger debounce, 8 s clear hold) and compares against a naive
single-sample unsmoothed threshold without hysteresis or debounce.

Reports:
  - False alarms & missed alarms on scripted ground-truth crowd episodes
  - Flicker comparison: number of level changes with smoothing/hysteresis/debounce ON
    vs naive threshold OFF
  - Writes `eval/results/alerts.csv`

Run from backend venv:
  python eval/eval_alerts.py
  python eval/eval_alerts.py --video eval/data/crowd-photos-and-videos/crowd-video.mp4
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import cv2

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.detection.detector import UltralyticsDetector  # noqa: E402
from app.engine.alert_rules import CreateAlert, EscalateAlert, ReopenAlert  # noqa: E402
from app.engine.zone_engine import (  # noqa: E402
    EngineSettings,
    SourceConfig,
    ZoneConfig,
    ZoneEngine,
)


@dataclass
class AlertScenario:
    name: str
    warning_count: int
    critical_count: int
    # Each tuple: (raw_count_or_None_for_gap, ground_truth_alert_active)
    steps: list[tuple[int | None, bool]]


def _build_default_scenarios() -> list[AlertScenario]:
    # 1. Transient false-positive spikes (1-2 frames above threshold, must NOT raise alert)
    spike_steps: list[tuple[int | None, bool]] = (
        [(10, False)] * 5
        + [(28, False), (32, False)]  # 2-second spike < 3s debounce + filtered by median
        + [(11, False)] * 6
        + [(45, False)]  # single-frame extreme outlier
        + [(10, False)] * 10
    )

    # 2. Sustained ramp into WARNING -> CRITICAL -> clean drop to NORMAL
    ramp_steps: list[tuple[int | None, bool]] = (
        [(10, False)] * 5
        + [(22, True)] * 6
        + [(35, True)] * 7
        + [(12, False)] * 14
    )

    # 3. Boundary oscillation around warning threshold (20) & critical threshold (30)
    osc_steps: list[tuple[int | None, bool]] = (
        [(18, False), (21, False), (19, False), (21, False), (18, False), (20, False)] * 2
        + [(24, True)] * 6
        + [(29, True), (31, True), (28, True), (31, True), (27, True), (32, True)] * 2
        + [(19, False), (18, False), (20, False), (17, False)] * 2
        + [(10, False)] * 10
    )

    # 4. Sustained alarm + brief 12s camera dropout (> stale_after_s=10) + recovery
    outage_steps: list[tuple[int | None, bool]] = (
        [(10, False)] * 4
        + [(25, True)] * 7
        + [(None, True)] * 12
        + [(26, True)] * 6
        + [(8, False)] * 12
    )

    return [
        AlertScenario("transient_spike", warning_count=20, critical_count=30, steps=spike_steps),
        AlertScenario("sustained_crowd_ramp", warning_count=20, critical_count=30, steps=ramp_steps),
        AlertScenario("boundary_oscillation", warning_count=20, critical_count=30, steps=osc_steps),
        AlertScenario("camera_dropout_recovery", warning_count=20, critical_count=30, steps=outage_steps),
    ]


def _count_truth_episodes(truth_flags: list[bool]) -> list[tuple[int, int]]:
    episodes: list[tuple[int, int]] = []
    start: int | None = None
    for idx, flag in enumerate(truth_flags):
        if flag and start is None:
            start = idx
        elif not flag and start is not None:
            episodes.append((start, idx - 1))
            start = None
    if start is not None:
        episodes.append((start, len(truth_flags) - 1))
    return episodes


def _run_series_through_engine(
    steps: list[tuple[int | None, bool]],
    *,
    warning_count: int,
    critical_count: int,
    smoothing_window: int,
    hysteresis_ratio: float,
    debounce_s: float,
    clear_s: float,
) -> dict[str, Any]:
    settings = EngineSettings(
        smoothing_window=smoothing_window,
        hysteresis_ratio=hysteresis_ratio,
        debounce_s=debounce_s,
        clear_s=clear_s,
        stale_after_s=10.0,
        cooldown_s=60.0,
        escalation_s=120.0,
    )
    engine = ZoneEngine(auto_commit_alerts=True)
    zone = ZoneConfig(
        id=1,
        mode="COUNT",
        warning_density=1.0,
        critical_density=2.0,
        warning_count=warning_count,
        critical_count=critical_count,
    )
    src = SourceConfig(id=1, zone_id=1, coverage_area_m2=100.0)
    t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    engine.boot([zone], [src], settings=settings)

    prev_level: str | None = None
    transitions = 0
    alert_triggers: list[int] = []
    active_steps: list[bool] = []

    for idx, (val, _) in enumerate(steps):
        now = t0 + timedelta(seconds=idx)
        if val is not None:
            actions = engine.ingest(1, float(val), now)
        else:
            actions = []
        tick_actions = engine.tick(now)
        all_actions = actions + tick_actions

        level = engine.get_zone_state(1, now)["level"]
        if prev_level is not None and level != prev_level:
            transitions += 1
        prev_level = level

        if any(isinstance(a, (CreateAlert, ReopenAlert, EscalateAlert)) for a in all_actions):
            alert_triggers.append(idx)

        is_alarming = level in ("WARNING", "CRITICAL")
        active_steps.append(is_alarming)

    truth_flags = [truth for _, truth in steps]
    episodes = _count_truth_episodes(truth_flags)

    # Missed alarm = ground-truth episode during which engine never entered WARNING/CRITICAL
    missed_alarms = 0
    for ep_start, ep_end in episodes:
        # Allow debounce warm-up tolerance inside sustained episode
        if not any(active_steps[t] for t in range(ep_start, ep_end + 1)):
            missed_alarms += 1

    # False alarm = alert activation step that occurs while ground truth is False (with 1s edge margin)
    false_alarms = 0
    for idx in alert_triggers:
        if not truth_flags[idx]:
            false_alarms += 1

    # For transient spike scenario: also count unexpected active alarm intervals outside truth
    if not episodes and false_alarms == 0 and any(active_steps):
        false_alarms = 1

    return {
        "transitions": transitions,
        "false_alarms": false_alarms,
        "missed_alarms": missed_alarms,
        "alert_triggers": len(alert_triggers),
    }


def _extract_video_counts(
    video_path: Path, model_path: str, *, imgsz: int, conf: float, max_frames: int
) -> list[int]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    native_fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    step = max(1, int(round(native_fps / 1.0)))  # 1 Hz replay
    detector = UltralyticsDetector(
        model_path=model_path,
        warmup_imgsz=imgsz,
        default_conf=conf,
    )
    counts: list[int] = []
    idx = 0
    try:
        while len(counts) < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % step == 0:
                ok_enc, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                if ok_enc:
                    boxes = detector.detect(buf.tobytes(), source_id=1, conf=conf, imgsz=imgsz)
                    counts.append(len(boxes))
            idx += 1
    finally:
        cap.release()
    return counts


def _default_model_path() -> str:
    for candidate in (
        ROOT_DIR / "people_model.pt",
        ROOT_DIR / "docs" / "model" / "best.pt",
        BACKEND_DIR / "docs" / "model" / "best.pt",
    ):
        if candidate.is_file():
            return str(candidate)
    return str(ROOT_DIR / "people_model.pt")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate false/missed alarms & flicker suppression.")
    parser.add_argument("--out", default=str(ROOT_DIR / "eval" / "results" / "alerts.csv"))
    parser.add_argument("--video", default="", help="Optional video to replay 1 Hz raw detector counts through ZoneEngine.")
    parser.add_argument("--model", default=_default_model_path(), help="Path to YOLO weights for --video mode.")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.35)
    parser.add_argument("--max-seconds", type=int, default=60, help="Max 1 Hz samples for --video mode.")
    args = parser.parse_args()

    scenarios = _build_default_scenarios()
    results: list[dict[str, Any]] = []

    print("=== CrowdVision Alert Accuracy & Flicker Evaluation ===")
    print("Engine: smoothing_window=5, hysteresis=0.85x, debounce=3s, clear_hold=8s")
    print("Naive:  smoothing_window=1, hysteresis=1.00x, debounce=0s, clear_hold=0s\n")
    print(
        f"{'Scenario':<26} {'Eng FA':>7} {'Eng Miss':>9} {'Naive FA':>9} "
        f"{'Eng Trans':>10} {'Naive Trans':>12} {'Flicker Drop':>13}"
    )
    print("-" * 92)

    for sc in scenarios:
        eng = _run_series_through_engine(
            sc.steps,
            warning_count=sc.warning_count,
            critical_count=sc.critical_count,
            smoothing_window=5,
            hysteresis_ratio=0.85,
            debounce_s=3.0,
            clear_s=8.0,
        )
        naive = _run_series_through_engine(
            sc.steps,
            warning_count=sc.warning_count,
            critical_count=sc.critical_count,
            smoothing_window=1,
            hysteresis_ratio=1.0,
            debounce_s=0.0,
            clear_s=0.0,
        )
        n_trans = naive["transitions"]
        e_trans = eng["transitions"]
        reduction = ((n_trans - e_trans) / n_trans * 100.0) if n_trans > 0 else 0.0
        row = {
            "scenario": sc.name,
            "steps": len(sc.steps),
            "engine_false_alarms": eng["false_alarms"],
            "engine_missed_alarms": eng["missed_alarms"],
            "naive_false_alarms": naive["false_alarms"],
            "naive_missed_alarms": naive["missed_alarms"],
            "engine_transitions": e_trans,
            "naive_transitions": n_trans,
            "flicker_reduction_pct": round(reduction, 1),
        }
        results.append(row)
        print(
            f"{row['scenario']:<26} {row['engine_false_alarms']:>7d} {row['engine_missed_alarms']:>9d} "
            f"{row['naive_false_alarms']:>9d} {row['engine_transitions']:>10d} "
            f"{row['naive_transitions']:>12d} {row['flicker_reduction_pct']:>12.1f}%"
        )

    if args.video:
        video_path = Path(args.video).resolve()
        counts = _extract_video_counts(
            video_path,
            args.model,
            imgsz=int(args.imgsz),
            conf=float(args.conf),
            max_frames=int(args.max_seconds),
        )
        if counts:
            # Place threshold near median count to stress boundary transitions on the real video
            sorted_c = sorted(counts)
            warn_t = max(2, sorted_c[len(sorted_c) // 2])
            crit_t = max(warn_t + 2, int(round(warn_t * 1.25)))
            v_steps = [(c, c >= warn_t) for c in counts]
            eng_v = _run_series_through_engine(
                v_steps,
                warning_count=warn_t,
                critical_count=crit_t,
                smoothing_window=5,
                hysteresis_ratio=0.85,
                debounce_s=3.0,
                clear_s=8.0,
            )
            naive_v = _run_series_through_engine(
                v_steps,
                warning_count=warn_t,
                critical_count=crit_t,
                smoothing_window=1,
                hysteresis_ratio=1.0,
                debounce_s=0.0,
                clear_s=0.0,
            )
            n_t = naive_v["transitions"]
            e_t = eng_v["transitions"]
            red = ((n_t - e_t) / n_t * 100.0) if n_t > 0 else 0.0
            print(
                f"\nReal video 1 Hz flicker replay ({video_path.name}, n={len(counts)}s, warn={warn_t}, crit={crit_t}):"
            )
            print(
                f"  Raw counts range: min={min(counts)}, median={warn_t}, max={max(counts)} | "
                f"Engine transitions={e_t} vs Naive transitions={n_t} (flicker reduction={red:.1f}%)"
            )
            results.append(
                {
                    "scenario": f"video:{video_path.name}",
                    "steps": len(counts),
                    "engine_false_alarms": eng_v["false_alarms"],
                    "engine_missed_alarms": eng_v["missed_alarms"],
                    "naive_false_alarms": naive_v["false_alarms"],
                    "naive_missed_alarms": naive_v["missed_alarms"],
                    "engine_transitions": e_t,
                    "naive_transitions": n_t,
                    "flicker_reduction_pct": round(red, 1),
                }
            )

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)
    print(f"\nWrote alert evaluation CSV -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
