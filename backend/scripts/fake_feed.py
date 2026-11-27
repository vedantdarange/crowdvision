"""scripts/fake_feed.py — Scripted fake feed runner for Phase B3 (M3 part 1).

Drives FakeDetector -> DetectionManager.ingest_count() -> StubZoneEngine ->
RealtimeEmitter so the frontend and tests receive real `zone:update` and
`zone:detail` events without a camera or PyTorch model.

Profile counts are automatically scaled to the target zone's thresholds and
mode (`COUNT` or `DENSITY` using `source.coverage_area_m2`).
"""
from __future__ import annotations

import logging
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.core.clock import Clock, FakeClock, SystemClock  # noqa: E402
from app.core.errors import NotFound, ValidationAppError  # noqa: E402
from app.detection.detector import FakeDetector  # noqa: E402
from app.detection.manager import DetectionManager  # noqa: E402

logger = logging.getLogger(__name__)

ProfileName = Literal["ramp", "spike", "flap", "offline"]
PROFILES: tuple[str, ...] = ("ramp", "spike", "flap", "offline")


@dataclass(frozen=True)
class ProfileBounds:
    """Count anchors scaled to a specific (zone, source) pair."""

    safe_count: int
    below_warn_count: int
    above_warn_count: int
    critical_count: int
    peak_count: int


def compute_profile_bounds(zone: Any, source: Any) -> ProfileBounds:
    """Compute representative person counts relative to zone thresholds & coverage."""
    mode = str(getattr(zone, "mode", "DENSITY"))
    w_cnt_cfg = getattr(zone, "warning_count", None)
    c_cnt_cfg = getattr(zone, "critical_count", None)

    if mode == "COUNT" and w_cnt_cfg is not None and c_cnt_cfg is not None:
        w_cnt = float(w_cnt_cfg)
        c_cnt = float(c_cnt_cfg)
    else:
        coverage = max(float(getattr(source, "coverage_area_m2", 1.0)), 1e-6)
        w_cnt = float(zone.warning_density) * coverage
        c_cnt = float(zone.critical_density) * coverage

    above_warn = max(1, math.ceil(w_cnt))
    # Keep below_warn strictly below w_cnt (and below 0.85 * w_cnt hysteresis when possible)
    below_warn = max(0, math.floor(w_cnt * 0.8))
    if below_warn >= above_warn:
        below_warn = max(0, above_warn - 1)

    # Ensure above_warn sits in WARNING band when integer resolution allows
    crit_int = max(above_warn + 1, math.ceil(c_cnt))
    peak = max(math.ceil(c_cnt * 1.25), crit_int + 1)
    safe = 0

    return ProfileBounds(
        safe_count=safe,
        below_warn_count=below_warn,
        above_warn_count=above_warn,
        critical_count=crit_int,
        peak_count=peak,
    )


def build_profile_counts(profile: str, bounds: ProfileBounds) -> list[int]:
    """Build the ordered sequence of person counts for a profile."""
    if profile == "ramp":
        # 60 steps (~60 s at 1 Hz, speed=1.0): 0 -> peak_count -> 0
        up_steps = 30
        down_steps = 30
        up = [
            round(bounds.peak_count * (i / (up_steps - 1)))
            for i in range(up_steps)
        ]
        down = [
            round(bounds.peak_count * (1.0 - (i / (down_steps - 1))))
            for i in range(down_steps)
        ]
        return up + down

    if profile == "spike":
        # Baseline safe, 1-frame jump to peak critical, then immediate return to safe
        return [bounds.safe_count] * 3 + [bounds.peak_count] + [bounds.safe_count] * 10

    if profile == "flap":
        # Hovers back and forth across the warning threshold
        cycle = [
            bounds.below_warn_count,
            bounds.below_warn_count,
            bounds.above_warn_count,
            bounds.above_warn_count,
        ]
        return cycle * 5

    if profile == "offline":
        # Sends nothing so the zone goes/stays stale
        return []

    raise ValidationAppError(
        f"Unknown fake-feed profile {profile!r}. Choose from {', '.join(PROFILES)}."
    )


def step_fake_feed(
    *,
    manager: DetectionManager,
    detector: FakeDetector,
    source_id: int,
    count: int,
    clock: Clock,
    conf: float = 0.35,
    imgsz: int = 640,
) -> dict[str, Any]:
    """Run one frame step through FakeDetector -> DetectionManager.ingest_count."""
    detector.set_count(source_id, count)
    boxes = detector.detect(None, source_id, conf=conf, imgsz=imgsz)
    return manager.ingest_count(source_id, len(boxes), now=clock.utcnow())


def run_fake_feed(
    *,
    zone_id: int,
    profile: str,
    source_id: int | None = None,
    speed: float = 1.0,
    container: Any,
    clock: Clock | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    step_interval_s: float = 1.0,
    max_steps: int | None = None,
    on_step: Callable[[int, int, int, dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Execute a scripted fake-feed profile for *zone_id* inside an active app context."""
    if speed <= 0:
        raise ValidationAppError("--speed must be greater than 0.")
    if profile not in PROFILES:
        raise ValidationAppError(
            f"Invalid profile {profile!r}. Must be one of: {', '.join(PROFILES)}."
        )

    zone = container.zone_repo.get(zone_id)
    if zone is None or not zone.is_active:
        raise NotFound(f"Active zone {zone_id} not found.")

    if source_id is not None:
        source = container.source_repo.get(source_id)
        if source is None or not source.is_active or source.zone_id != zone.id:
            raise NotFound(f"Active source {source_id} not found for zone {zone_id}.")
    else:
        sources = container.source_repo.list_by_zone(zone.id, include_inactive=False)
        if not sources:
            raise NotFound(f"Zone {zone_id} has no active sources.")
        source = sources[0]

    sim_clock: FakeClock | None = None
    if clock is not None:
        active_clock: Clock = clock
    elif speed != 1.0:
        # Preserve simulated 1 Hz engine timestamps when fast-forwarding playback
        sim_clock = FakeClock(start=(container.clock or SystemClock()).time())
        active_clock = sim_clock
    else:
        active_clock = container.clock or SystemClock()

    detector = (
        container.detection_manager.detector
        if isinstance(container.detection_manager.detector, FakeDetector)
        else FakeDetector()
    )
    settings_dict = container.settings_service.get_settings()
    detect_conf = float(settings_dict.get("detect_conf", 0.35))
    frame_width = int(settings_dict.get("frame_width", 640))

    bounds = compute_profile_bounds(zone, source)
    counts = build_profile_counts(profile, bounds)
    if max_steps is not None:
        counts = counts[: max(0, int(max_steps))]

    results: list[dict[str, Any]] = []
    delay_s = float(step_interval_s) / float(speed)
    total = len(counts)

    for idx, count in enumerate(counts):
        state = step_fake_feed(
            manager=container.detection_manager,
            detector=detector,
            source_id=source.id,
            count=count,
            clock=active_clock,
            conf=detect_conf,
            imgsz=frame_width,
        )
        results.append(state)
        if on_step is not None:
            on_step(idx + 1, total, count, state)
        if idx + 1 < total:
            if sim_clock is not None:
                sim_clock.advance(float(step_interval_s))
            if delay_s > 0:
                sleep_fn(delay_s)

    return results


def main(argv: list[str] | None = None) -> int:
    """Standalone CLI entrypoint (`python scripts/fake_feed.py ...`)."""
    import argparse

    from app import create_app

    parser = argparse.ArgumentParser(description="Run scripted fake-feed profile for a zone.")
    parser.add_argument("--zone", type=int, required=True, help="Target zone ID.")
    parser.add_argument("--profile", choices=PROFILES, required=True, help="Profile name.")
    parser.add_argument("--source", type=int, default=None, help="Optional source ID.")
    parser.add_argument("--speed", type=float, default=1.0, help="Playback speed multiplier.")
    args = parser.parse_args(argv)

    flask_app = create_app()
    with flask_app.app_context():
        container = flask_app.extensions["container"]
        if args.profile == "offline":
            sys.stdout.write(
                f"Profile 'offline' for zone={args.zone}: sending 0 frames.\n"
            )
        run_fake_feed(
            zone_id=args.zone,
            profile=args.profile,
            source_id=args.source,
            speed=args.speed,
            container=container,
            on_step=lambda step, total, count, state: sys.stdout.write(
                f"  [{step}/{total}] zone={args.zone} count={count} "
                f"density={state['density']} level={state['level']} trend={state['trend']}\n"
            ),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
