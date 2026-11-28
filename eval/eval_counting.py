"""eval/eval_counting.py — Counting accuracy & tracker comparison evaluation (contract §13, B9).

Runs the real UltralyticsDetector in the exact same tracker-free single-image
mode used by the live pipeline:
  - Resized internally by YOLO to `imgsz` (default 640)
  - Confidence threshold `conf` (default 0.35), COCO class 0 (person) only
  - Occupancy count = raw `len(boxes)` (no tracker gating)

Supports:
  1. Image dataset evaluation against a CSV (`filename` or `image_name`, `true_count`),
     printing per-image predictions + MAE, RMSE (scikit-learn), and mean signed error,
     and writing `eval/results/counting.csv`.
  2. Hyperparameter grid comparison (`--compare --imgsz-list 640 960 --conf-list 0.25 0.35 0.5`).
  3. Video mode (`--video PATH`) comparing raw-detection counts vs `trackers.ByteTrackTracker`
     confirmed counts (plan §8.2 settings: `frame_rate=target_fps`,
     `track_activation_threshold=detect_conf`) to document why tracking is NOT used for counts.

Run from backend venv (e.g. D:\\crowdvision\\backend\\.venv-gpu\\Scripts\\python.exe):
  python eval/eval_counting.py
  python eval/eval_counting.py --compare --imgsz-list 640 960 --conf-list 0.25 0.35 0.5
  python eval/eval_counting.py --video eval/data/crowd-photos-and-videos/crowd-video.mp4
"""
from __future__ import annotations

import argparse
import csv
import itertools
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from sklearn.metrics import mean_absolute_error, root_mean_squared_error

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.detection.detector import UltralyticsDetector  # noqa: E402
from app.detection.tracker import ByteTrackTrackerHook  # noqa: E402


def _default_model_path() -> str:
    for candidate in (
        ROOT_DIR / "people_model.pt",
        ROOT_DIR / "docs" / "model" / "best.pt",
        BACKEND_DIR / "docs" / "model" / "best.pt",
    ):
        if candidate.is_file():
            return str(candidate)
    return str(ROOT_DIR / "people_model.pt")


def _default_labels_path() -> Path:
    for candidate in (
        ROOT_DIR / "eval" / "data" / "labels.csv",
        ROOT_DIR / "eval" / "data" / "crowd-photos-and-videos" / "labels.csv",
    ):
        if candidate.is_file():
            return candidate
    return ROOT_DIR / "eval" / "data" / "labels.csv"


def _resolve_image_path(data_dir: Path, raw_name: str) -> Path:
    """Resolve CSV filename (`IMG_1.jpg` or `processed_IMG_1.jpg`) inside *data_dir*."""
    cleaned = raw_name.strip()
    candidates = [
        data_dir / cleaned,
        data_dir / f"processed_{cleaned}",
        data_dir / Path(cleaned).name,
        data_dir / f"processed_{Path(cleaned).name}",
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"Image {cleaned!r} not found in {data_dir} (also checked processed_{cleaned!r})."
    )


def _load_labelled_samples(labels_csv: Path, data_dir: Path) -> list[tuple[str, Path, int]]:
    if not labels_csv.is_file():
        raise FileNotFoundError(f"Labels CSV not found: {labels_csv}")

    samples: list[tuple[str, Path, int]] = []
    with labels_csv.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"Empty CSV header in {labels_csv}")
        fields = {f.strip(): f for f in reader.fieldnames}
        name_col = fields.get("filename") or fields.get("image_name") or fields.get("file")
        count_col = fields.get("true_count") or fields.get("count")
        if name_col is None or count_col is None:
            raise ValueError(
                f"Expected filename/image_name and true_count columns in {labels_csv}; got {reader.fieldnames}"
            )
        for row in reader:
            raw_name = (row.get(name_col) or "").strip()
            raw_count = (row.get(count_col) or "").strip()
            if not raw_name:
                continue
            img_path = _resolve_image_path(data_dir, raw_name)
            samples.append((raw_name, img_path, int(float(raw_count))))
    if not samples:
        raise ValueError(f"No rows found in {labels_csv}")
    return samples


def _read_image_jpeg_bytes(img_path: Path) -> tuple[bytes, int, int]:
    img = cv2.imread(str(img_path))
    if img is None:
        raise RuntimeError(f"Failed to decode image with OpenCV: {img_path}")
    h, w = img.shape[:2]
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    if not ok:
        raise RuntimeError(f"Failed to JPEG-encode image: {img_path}")
    return buf.tobytes(), int(w), int(h)


def _evaluate_image_config(
    detector: UltralyticsDetector,
    encoded_samples: list[tuple[str, Path, bytes, int, int, int]],
    *,
    conf: float,
    imgsz: int,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    rows: list[dict[str, Any]] = []
    y_true: list[int] = []
    y_pred: list[int] = []
    infer_times: list[float] = []

    for label, img_path, jpeg_bytes, width, height, true_count in encoded_samples:
        t0 = time.perf_counter()
        boxes = detector.detect(jpeg_bytes, source_id=-1, conf=conf, imgsz=imgsz)
        infer_ms = (time.perf_counter() - t0) * 1000.0
        pred_count = len(boxes)
        signed_err = pred_count - true_count
        abs_err = abs(signed_err)

        y_true.append(true_count)
        y_pred.append(pred_count)
        infer_times.append(infer_ms)
        rows.append(
            {
                "filename": label,
                "resolved_file": img_path.name,
                "width": width,
                "height": height,
                "imgsz": imgsz,
                "conf": conf,
                "true_count": true_count,
                "pred_count": pred_count,
                "signed_error": signed_err,
                "abs_error": abs_err,
                "infer_ms": round(infer_ms, 2),
            }
        )

    mae = float(mean_absolute_error(y_true, y_pred))
    rmse = float(root_mean_squared_error(y_true, y_pred))
    mse_signed = float(statistics.mean(p - t for p, t in zip(y_pred, y_true)))
    mean_true = float(statistics.mean(y_true))
    rel_mae_pct = (mae / mean_true * 100.0) if mean_true > 0 else 0.0
    summary = {
        "imgsz": float(imgsz),
        "conf": float(conf),
        "n": float(len(rows)),
        "mae": round(mae, 3),
        "rmse": round(rmse, 3),
        "mean_signed_error": round(mse_signed, 3),
        "rel_mae_pct": round(rel_mae_pct, 2),
        "mean_infer_ms": round(statistics.mean(infer_times), 2),
    }
    return rows, summary


def run_image_eval(args: argparse.Namespace) -> int:
    labels_csv = Path(args.labels).resolve() if args.labels else _default_labels_path()
    data_dir = Path(args.data_dir).resolve() if args.data_dir else labels_csv.parent
    samples = _load_labelled_samples(labels_csv, data_dir)

    encoded_samples = []
    for label, img_path, true_count in samples:
        jpeg_bytes, w, h = _read_image_jpeg_bytes(img_path)
        encoded_samples.append((label, img_path, jpeg_bytes, w, h, true_count))

    imgsz_values = [int(v) for v in (args.imgsz_list if args.compare else [args.imgsz])]
    conf_values = [float(v) for v in (args.conf_list if args.compare else [args.conf])]

    detector = UltralyticsDetector(
        model_path=args.model,
        warmup_imgsz=imgsz_values[0],
        default_conf=conf_values[0],
    )

    import torch

    if torch.cuda.is_available():
        device = f"cuda:0 ({torch.cuda.get_device_name(0)})"
    else:
        device = "cpu"
    print("=== CrowdVision Counting Evaluation (tracker-free single-image pipeline mode) ===")
    print(f"Platform:   {platform.platform()} | CPU: {platform.processor()}")
    print(f"Model:      {args.model} | Torch device: {device}")
    print(f"Dataset:    {labels_csv} ({len(encoded_samples)} images from {data_dir})")
    print("Mode:       UltralyticsDetector single-image detection, COCO class=0 (person), no tracker gating")

    primary_rows: list[dict[str, Any]] | None = None
    primary_summary: dict[str, float] | None = None
    compare_rows: list[dict[str, float]] = []

    for imgsz, conf in itertools.product(imgsz_values, conf_values):
        rows, summary = _evaluate_image_config(
            detector,
            encoded_samples,
            conf=conf,
            imgsz=imgsz,
        )
        compare_rows.append(summary)
        if primary_rows is None or (imgsz == int(args.imgsz) and abs(conf - float(args.conf)) < 1e-9):
            primary_rows = rows
            primary_summary = summary

    assert primary_rows is not None and primary_summary is not None

    print(
        f"\nPer-image results (imgsz={int(primary_summary['imgsz'])}, conf={primary_summary['conf']:.2f}):"
    )
    print(f"{'Image':<18} {'Resolved File':<26} {'True':>6} {'Pred':>6} {'Err':>7} {'|Err|':>6} {'Infer(ms)':>10}")
    print("-" * 85)
    for row in primary_rows:
        print(
            f"{row['filename']:<18} {row['resolved_file']:<26} "
            f"{row['true_count']:>6d} {row['pred_count']:>6d} "
            f"{row['signed_error']:>+7d} {row['abs_error']:>6d} {row['infer_ms']:>10.2f}"
        )

    print("-" * 85)
    print(
        f"MAE={primary_summary['mae']:.3f} | RMSE={primary_summary['rmse']:.3f} | "
        f"MeanSignedErr={primary_summary['mean_signed_error']:+.3f} | "
        f"RelMAE={primary_summary['rel_mae_pct']:.2f}% | "
        f"MeanInfer={primary_summary['mean_infer_ms']:.2f} ms"
    )

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(primary_rows[0].keys())
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(primary_rows)
    print(f"Wrote per-image CSV -> {out_path}")

    if args.compare or len(compare_rows) > 1:
        print("\n=== Settings Comparison (imgsz x conf) ===")
        print(f"{'imgsz':>6} {'conf':>6} {'MAE':>8} {'RMSE':>8} {'MeanErr':>9} {'RelMAE%':>8} {'Infer(ms)':>10}")
        print("-" * 62)
        for s in compare_rows:
            print(
                f"{int(s['imgsz']):>6d} {s['conf']:>6.2f} {s['mae']:>8.3f} "
                f"{s['rmse']:>8.3f} {s['mean_signed_error']:>+9.3f} "
                f"{s['rel_mae_pct']:>8.2f} {s['mean_infer_ms']:>10.2f}"
            )
        cmp_path = out_path.parent / "counting_compare.csv"
        with cmp_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(compare_rows[0].keys()))
            writer.writeheader()
            writer.writerows(compare_rows)
        print(f"Wrote comparison CSV -> {cmp_path}")

    return 0


def _load_video_labels(path: Path | None) -> dict[int, int]:
    if path is None or not path.is_file():
        return {}
    mapping: dict[int, int] = {}
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            return {}
        for row in reader:
            idx_val = row.get("frame_idx") or row.get("sampled_idx") or row.get("frame")
            cnt_val = row.get("true_count") or row.get("count")
            if idx_val is not None and cnt_val is not None:
                mapping[int(idx_val)] = int(float(cnt_val))
    return mapping


def run_video_eval(args: argparse.Namespace) -> int:
    video_path = Path(args.video).resolve()
    if not video_path.is_file():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    native_fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    if native_fps <= 0:
        native_fps = 25.0
    target_fps = max(1.0, float(args.sample_fps))
    step = max(1, int(round(native_fps / target_fps)))

    detector = UltralyticsDetector(
        model_path=args.model,
        warmup_imgsz=int(args.imgsz),
        default_conf=float(args.conf),
    )
    tracker = ByteTrackTrackerHook(
        frame_rate=target_fps,
        track_activation_threshold=float(args.conf),
    )
    hand_labels = _load_video_labels(Path(args.video_labels) if args.video_labels else None)

    rows: list[dict[str, Any]] = []
    frame_pos = 0
    sampled_idx = 0
    try:
        while sampled_idx < int(args.max_frames):
            ok, frame = cap.read()
            if not ok:
                break
            if frame_pos % step != 0:
                frame_pos += 1
                continue
            ok_enc, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok_enc:
                frame_pos += 1
                continue

            ts_s = sampled_idx / target_fps
            boxes = detector.detect(
                buf.tobytes(),
                source_id=1,
                conf=float(args.conf),
                imgsz=int(args.imgsz),
            )
            tracked_boxes = tracker.update(1, boxes, now_s=ts_s, reset=(sampled_idx == 0))
            raw_cnt = len(boxes)
            trk_cnt = len(tracked_boxes)
            true_cnt = hand_labels.get(sampled_idx, hand_labels.get(frame_pos))
            diff = raw_cnt - trk_cnt
            rows.append(
                {
                    "sampled_idx": sampled_idx,
                    "source_frame_idx": frame_pos,
                    "timestamp_s": round(ts_s, 3),
                    "raw_count": raw_cnt,
                    "tracker_confirmed_count": trk_cnt,
                    "dropped_by_tracker": diff,
                    "true_count": "" if true_cnt is None else true_cnt,
                }
            )
            sampled_idx += 1
            frame_pos += 1
    finally:
        cap.release()

    if not rows:
        print("No frames decoded from video.", file=sys.stderr)
        return 1

    out_path = Path(args.video_out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    mean_raw = statistics.mean(r["raw_count"] for r in rows)
    mean_trk = statistics.mean(r["tracker_confirmed_count"] for r in rows)
    mean_drop = mean_raw - mean_trk
    drop_pct = (mean_drop / mean_raw * 100.0) if mean_raw > 0 else 0.0

    print("=== CrowdVision Video Raw vs ByteTrack Confirmed Count Comparison ===")
    print(
        f"Video: {video_path} | native_fps={native_fps:.2f} | sampled={len(rows)} frames at {target_fps:.1f} fps (step={step})"
    )
    print(
        f"Tracker: trackers.ByteTrackTracker(frame_rate={target_fps:.1f}, track_activation_threshold={args.conf})"
    )
    print(f"{'Sample':>6} {'Frame':>6} {'t(s)':>6} {'Raw':>6} {'Tracked':>8} {'Diff':>6} {'True':>6}")
    print("-" * 52)
    preview = rows if len(rows) <= 20 else rows[:10] + rows[-10:]
    for r in preview:
        print(
            f"{r['sampled_idx']:>6d} {r['source_frame_idx']:>6d} {r['timestamp_s']:>6.2f} "
            f"{r['raw_count']:>6d} {r['tracker_confirmed_count']:>8d} "
            f"{r['dropped_by_tracker']:>+6d} {str(r['true_count'] or '-'):>6}"
        )
    print("-" * 52)
    print(
        f"Mean raw={mean_raw:.2f} vs mean tracker-confirmed={mean_trk:.2f} "
        f"(mean difference={mean_drop:+.2f}, tracker suppressed {drop_pct:.1f}% of raw detections)"
    )

    labelled_rows = [r for r in rows if r["true_count"] != ""]
    if labelled_rows:
        y_t = [int(r["true_count"]) for r in labelled_rows]
        y_r = [int(r["raw_count"]) for r in labelled_rows]
        y_k = [int(r["tracker_confirmed_count"]) for r in labelled_rows]
        print(
            f"Against {len(labelled_rows)} hand-counted frames -> "
            f"Raw MAE={mean_absolute_error(y_t, y_r):.3f} | "
            f"Tracker MAE={mean_absolute_error(y_t, y_k):.3f}"
        )
    else:
        print("Note: No --video-labels CSV supplied; hand-counted subset MAE omitted (see TODO in docs/EVALUATION.md).")

    print(f"Wrote video comparison CSV -> {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate counting accuracy & tracker vs raw counts.")
    parser.add_argument("--labels", default="", help="Path to labels CSV (filename/image_name, true_count).")
    parser.add_argument("--data-dir", default="", help="Directory containing evaluation images (defaults to labels.csv parent).")
    parser.add_argument("--model", default=_default_model_path(), help="Path to YOLO weights (.pt).")
    parser.add_argument("--imgsz", type=int, default=640, help="Primary detector imgsz (matches default frame_width=640).")
    parser.add_argument("--conf", type=float, default=0.35, help="Primary confidence threshold (matches default detect_conf=0.35).")
    parser.add_argument("--out", default=str(ROOT_DIR / "eval" / "results" / "counting.csv"), help="Output CSV path.")
    parser.add_argument("--compare", action="store_true", help="Compare multiple imgsz x conf settings.")
    parser.add_argument("--imgsz-list", nargs="+", type=int, default=[640, 960], help="imgsz values for --compare.")
    parser.add_argument("--conf-list", nargs="+", type=float, default=[0.25, 0.35, 0.5], help="conf values for --compare.")
    parser.add_argument("--video", default="", help="Optional video path for raw vs ByteTrack comparison.")
    parser.add_argument("--video-labels", default="", help="Optional CSV (frame_idx,true_count) for video subset.")
    parser.add_argument("--sample-fps", type=float, default=3.0, help="Sampling rate for --video mode (matches target_fps).")
    parser.add_argument("--max-frames", type=int, default=90, help="Max sampled frames in --video mode.")
    parser.add_argument("--video-out", default=str(ROOT_DIR / "eval" / "results" / "counting_video.csv"), help="Output CSV for --video mode.")
    args = parser.parse_args()

    rc = 0
    if not args.video or Path(_default_labels_path()).is_file() or args.labels:
        rc = run_image_eval(args)
    if args.video:
        rc2 = run_video_eval(args)
        rc = rc or rc2
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
