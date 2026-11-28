import { memo, useCallback, useEffect, useRef, useState } from 'react';
import type { FrameResult } from '@contract/types';
import { computeContainRect, mapBoxes } from './overlay';

interface DetectionOverlayProps {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  lastResult: FrameResult | null;
  /** Time (Date.now() ms) when lastResult arrived, used for the 1 s stale clear. */
  resultTimestamp?: number | null;
}

const STALE_MS = 1000;

function DetectionOverlayBase({
  videoRef,
  lastResult,
  resultTimestamp,
}: DetectionOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [showConf, setShowConf] = useState(false);

  const clearCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
  }, []);

  const drawBoxes = useCallback(() => {
    const canvas = canvasRef.current;
    const video = videoRef.current;
    if (!canvas || !video) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = video.getBoundingClientRect();
    const targetW = Math.max(0, Math.round(rect.width * dpr));
    const targetH = Math.max(0, Math.round(rect.height * dpr));

    if (canvas.width !== targetW) canvas.width = targetW;
    if (canvas.height !== targetH) canvas.height = targetH;
    canvas.style.width = `${rect.width}px`;
    canvas.style.height = `${rect.height}px`;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (!lastResult || !lastResult.ok || lastResult.boxes.length === 0) {
      return;
    }

    const display = computeContainRect(
      video.videoWidth,
      video.videoHeight,
      rect.width,
      rect.height,
    );
    const boxes = mapBoxes(lastResult.boxes, display, dpr);

    ctx.strokeStyle = '#00ff88';
    ctx.lineWidth = 1.5 * dpr;

    for (const box of boxes) {
      ctx.strokeRect(box.x, box.y, box.w, box.h);
      if (showConf) {
        const fontSize = 11 * dpr;
        const labelH = fontSize + 4 * dpr;
        const labelY = box.y >= labelH ? box.y - labelH : box.y;
        ctx.font = `${fontSize}px system-ui`;
        const label = `${Math.round(box.conf * 100)}%`;
        const textWidth = ctx.measureText(label).width;
        ctx.fillStyle = 'rgba(0, 0, 0, 0.72)';
        ctx.fillRect(box.x, labelY, textWidth + 6 * dpr, labelH);
        ctx.fillStyle = '#00ff88';
        ctx.fillText(label, box.x + 3 * dpr, labelY + fontSize);
      }
    }
  }, [videoRef, lastResult, showConf]);

  const drawBoxesRef = useRef(drawBoxes);
  drawBoxesRef.current = drawBoxes;

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const onResize = () => drawBoxesRef.current();
    const observer =
      typeof ResizeObserver !== 'undefined'
        ? new ResizeObserver(onResize)
        : null;
    observer?.observe(video);
    window.addEventListener('resize', onResize);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', onResize);
    };
  }, [videoRef]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) {
      clearCanvas();
      return;
    }

    const age =
      typeof resultTimestamp === 'number' && resultTimestamp > 0
        ? Date.now() - resultTimestamp
        : 0;
    const remaining = STALE_MS - age;

    if (!lastResult || !lastResult.ok || remaining <= 0) {
      clearCanvas();
      return;
    }

    drawBoxes();

    const timer = setTimeout(clearCanvas, remaining);
    return () => {
      clearTimeout(timer);
    };
  }, [videoRef, lastResult, resultTimestamp, drawBoxes, clearCanvas]);

  return (
    <>
      <canvas
        ref={canvasRef}
        className="pointer-events-none absolute inset-0"
        aria-hidden="true"
      />
      <button
        type="button"
        aria-pressed={showConf}
        onClick={() => setShowConf((v) => !v)}
        className="absolute right-2 top-2 z-10 min-h-11 min-w-11 rounded bg-black/70 px-3 py-1 text-xs font-medium text-white hover:bg-black/85"
      >
        {showConf ? 'Hide conf' : 'Show conf'}
      </button>
    </>
  );
}

export const DetectionOverlay = memo(DetectionOverlayBase);
