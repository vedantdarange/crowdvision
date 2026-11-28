import { useCallback, useEffect, useRef, useState } from 'react';

export interface VideoFileState {
  /** Ref to attach to a <video> element. */
  videoRef: React.RefObject<HTMLVideoElement | null>;
  /** Whether a file is loaded. */
  loaded: boolean;
  /** Whether video is currently playing. */
  playing: boolean;
  /** Whether loop mode is on. */
  loop: boolean;
  /** True when a loop restart was detected; consumed by the frame streamer. */
  loopRestarted: boolean;
  /** Clear the loop-restart flag after the streamer has read it. */
  clearLoopRestart: () => void;
  /** Load a video file. */
  loadFile: (file: File) => void;
  /** Play the loaded video. */
  play: () => void;
  /** Pause the loaded video. */
  pause: () => void;
  /** Toggle loop on/off. */
  toggleLoop: () => void;
  /** Unload the current file and clean up. */
  unload: () => void;
}

export function useVideoFile(): VideoFileState {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const urlRef = useRef<string | null>(null);
  const lastTimeRef = useRef<number>(0);
  const [loaded, setLoaded] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [loop, setLoop] = useState(true);
  const [loopRestarted, setLoopRestarted] = useState(false);

  const revokeUrl = useCallback(() => {
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
  }, []);

  const unload = useCallback(() => {
    const video = videoRef.current;
    if (video) {
      if (typeof video.pause === 'function') video.pause();
      video.removeAttribute('src');
      if (typeof video.load === 'function') video.load();
    }
    revokeUrl();
    setLoaded(false);
    setPlaying(false);
    setLoopRestarted(false);
    lastTimeRef.current = 0;
  }, [revokeUrl]);

  const loadFile = useCallback(
    (file: File) => {
      revokeUrl();
      const url = URL.createObjectURL(file);
      urlRef.current = url;
      const video = videoRef.current;
      if (video) {
        video.src = url;
        video.loop = loop;
        if (typeof video.load === 'function') video.load();
      }
      setLoaded(true);
      setPlaying(false);
      setLoopRestarted(false);
      lastTimeRef.current = 0;
    },
    [revokeUrl, loop],
  );

  const play = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    const maybePromise = video.play?.();
    if (maybePromise && typeof maybePromise.then === 'function') {
      maybePromise.then(() => setPlaying(true)).catch(() => setPlaying(false));
    } else {
      setPlaying(true);
    }
  }, []);

  const pause = useCallback(() => {
    videoRef.current?.pause?.();
    setPlaying(false);
  }, []);

  const toggleLoop = useCallback(() => {
    setLoop((prev) => {
      const next = !prev;
      if (videoRef.current) videoRef.current.loop = next;
      return next;
    });
  }, []);

  const clearLoopRestart = useCallback(() => {
    setLoopRestarted(false);
  }, []);

  // Detect loop restart (currentTime decreases) and keep src/playing state synced.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (urlRef.current && video.src !== urlRef.current) {
      video.src = urlRef.current;
      video.loop = loop;
    }
    const onTimeUpdate = () => {
      const currentTime = video.currentTime;
      if (lastTimeRef.current > 0 && currentTime < lastTimeRef.current) {
        setLoopRestarted(true);
      }
      lastTimeRef.current = currentTime;
    };
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onEnded = () => setPlaying(false);
    video.addEventListener('timeupdate', onTimeUpdate);
    video.addEventListener('play', onPlay);
    video.addEventListener('pause', onPause);
    video.addEventListener('ended', onEnded);
    return () => {
      video.removeEventListener('timeupdate', onTimeUpdate);
      video.removeEventListener('play', onPlay);
      video.removeEventListener('pause', onPause);
      video.removeEventListener('ended', onEnded);
    };
  }, [loaded, loop]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      revokeUrl();
    };
  }, [revokeUrl]);

  return {
    videoRef,
    loaded,
    playing,
    loop,
    loopRestarted,
    clearLoopRestart,
    loadFile,
    play,
    pause,
    toggleLoop,
    unload,
  };
}
