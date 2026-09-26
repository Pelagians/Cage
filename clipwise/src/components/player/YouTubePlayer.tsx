"use client";
/**
 * Reusable segment player on top of the official YouTube IFrame API.
 *
 * - Creates exactly one YT.Player per mount (strict-mode safe: a cancelled mount never
 *   creates a player) and destroys it on unmount.
 * - Changing videoId/startSeconds reuses the same player: same video → seek, different
 *   video → loadVideoById. So "Next"/"Go Deeper" keep the user's tap gesture and
 *   autoplay reliably on mobile.
 * - Polls the playhead every 250 ms. When `boundaryActive` is set it pauses at
 *   endSeconds and calls onSegmentEnd once (see SegmentBoundary).
 * - Callbacks are read through refs, so handlers are never stale.
 */
import { useEffect, useImperativeHandle, useLayoutEffect, useRef, useState, type Ref } from "react";
import { describePlayerError } from "@/lib/domain/youtube";
import { loadYouTubeApi, PLAYER_STATE, type YTPlayer } from "./youtube-api";
import { SegmentBoundary } from "./segment-boundary";

export interface YouTubePlayerHandle {
  play(): void;
  pause(): void;
  /** Seek back to startSeconds and play with the boundary re-armed. */
  restartSegment(): void;
  seekTo(seconds: number): void;
  getCurrentTime(): number;
  getDuration(): number;
}

export interface YouTubePlayerProps {
  videoId: string;
  startSeconds: number;
  endSeconds: number;
  /** When false (Continue Original), playback runs past endSeconds. */
  boundaryActive: boolean;
  autoplay: boolean;
  /** Called once per loaded video with the duration the player reports. */
  onReady?: (durationSeconds: number, videoId: string) => void;
  onProgress?: (seconds: number) => void;
  onPlayingChange?: (playing: boolean) => void;
  onSegmentEnd?: () => void;
  onError?: (message: string, code: number) => void;
  ref?: Ref<YouTubePlayerHandle>;
  className?: string;
}

export function YouTubePlayer(props: YouTubePlayerProps) {
  const { videoId, startSeconds, endSeconds, ref, className } = props;
  const containerRef = useRef<HTMLDivElement>(null);
  const playerRef = useRef<YTPlayer | null>(null);
  const [ready, setReady] = useState(false);
  const boundary = useRef(new SegmentBoundary(startSeconds, endSeconds));
  const loaded = useRef<{ videoId: string; start: number } | null>(null);
  const reportedVideo = useRef<string | null>(null);

  // Latest props for use inside long-lived callbacks.
  const latest = useRef(props);
  useLayoutEffect(() => {
    latest.current = props;
    boundary.current.enabled = props.boundaryActive;
  });

  // Create the player once per mount.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    let cancelled = false;
    const host = document.createElement("div");
    container.appendChild(host);

    loadYouTubeApi()
      .then((YT) => {
        if (cancelled) return;
        const p = latest.current;
        loaded.current = { videoId: p.videoId, start: p.startSeconds };
        boundary.current.reset(p.startSeconds, p.endSeconds);
        playerRef.current = new YT.Player(host, {
          host: "https://www.youtube-nocookie.com",
          videoId: p.videoId,
          width: "100%",
          height: "100%",
          playerVars: {
            start: Math.floor(p.startSeconds),
            autoplay: p.autoplay ? 1 : 0,
            playsinline: 1,
            rel: 0,
            modestbranding: 1,
            iv_load_policy: 3,
            origin: window.location.origin,
          },
          events: {
            onReady: (e) => {
              if (cancelled) return;
              setReady(true);
              reportedVideo.current = p.videoId;
              latest.current.onReady?.(e.target.getDuration(), p.videoId);
              if (latest.current.autoplay) e.target.playVideo();
            },
            onStateChange: (e) => {
              if (cancelled) return;
              latest.current.onPlayingChange?.(e.data === PLAYER_STATE.PLAYING);
              // Videos switched in via loadVideoById report their duration once they play.
              const current = loaded.current?.videoId;
              if (e.data === PLAYER_STATE.PLAYING && current && reportedVideo.current !== current) {
                reportedVideo.current = current;
                latest.current.onReady?.(e.target.getDuration(), current);
              }
              if (e.data === PLAYER_STATE.ENDED && boundary.current.videoEnded()) latest.current.onSegmentEnd?.();
            },
            onError: (e) => {
              if (!cancelled) latest.current.onError?.(describePlayerError(e.data), e.data);
            },
          },
        });
      })
      .catch(() => {
        if (!cancelled) latest.current.onError?.("Couldn't load the YouTube player. Check your internet connection.", -1);
      });

    const tick = setInterval(() => {
      const player = playerRef.current;
      if (!player || cancelled) return;
      let state: number;
      let t: number;
      try {
        state = player.getPlayerState();
        t = player.getCurrentTime();
      } catch {
        return; // player not fully initialised yet
      }
      const playing = state === PLAYER_STATE.PLAYING;
      if (playing) latest.current.onProgress?.(t);
      if (boundary.current.update(t, playing)) {
        player.pauseVideo();
        latest.current.onSegmentEnd?.();
      }
    }, 250);

    return () => {
      cancelled = true;
      clearInterval(tick);
      try {
        playerRef.current?.destroy();
      } catch {
        // already gone
      }
      playerRef.current = null;
      loaded.current = null;
      setReady(false);
      container.replaceChildren();
    };
  }, []);

  // Switch clips without recreating the iframe.
  useEffect(() => {
    const player = playerRef.current;
    if (!ready || !player || !loaded.current) return;
    if (loaded.current.videoId === videoId && loaded.current.start === startSeconds) {
      boundary.current.setEnd(endSeconds);
      return;
    }
    const sameVideo = loaded.current.videoId === videoId;
    loaded.current = { videoId, start: startSeconds };
    boundary.current.reset(startSeconds, endSeconds);
    const autoplay = latest.current.autoplay;
    if (sameVideo) {
      player.seekTo(startSeconds, true);
      if (autoplay) player.playVideo();
    } else if (autoplay) {
      player.loadVideoById({ videoId, startSeconds });
    } else {
      player.cueVideoById({ videoId, startSeconds });
    }
  }, [ready, videoId, startSeconds, endSeconds]);

  useImperativeHandle(
    ref,
    () => ({
      play: () => playerRef.current?.playVideo(),
      pause: () => playerRef.current?.pauseVideo(),
      restartSegment: () => {
        const p = latest.current;
        boundary.current.reset(p.startSeconds, p.endSeconds);
        playerRef.current?.seekTo(p.startSeconds, true);
        playerRef.current?.playVideo();
      },
      seekTo: (s: number) => playerRef.current?.seekTo(s, true),
      getCurrentTime: () => {
        try {
          return playerRef.current?.getCurrentTime() ?? 0;
        } catch {
          return 0;
        }
      },
      getDuration: () => {
        try {
          return playerRef.current?.getDuration() ?? 0;
        } catch {
          return 0;
        }
      },
    }),
    [],
  );

  return <div ref={containerRef} data-testid="yt-player" className={className} />;
}
