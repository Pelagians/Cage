"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ClipView } from "@/lib/types";
import { formatDuration, formatTimestamp } from "@/lib/domain/time";
import { youTubeWatchUrl } from "@/lib/domain/youtube";
import { topicHue } from "@/lib/client/topic-color";
import { api, ApiError } from "@/lib/client/api";
import { track } from "@/lib/client/interactions";
import { getSeen, markSeen, sessionStore } from "@/lib/client/session";
import { useToast } from "../Toast";
import { YouTubePlayer, type YouTubePlayerHandle } from "../player/YouTubePlayer";
import {
  ArrowLeftIcon,
  BookmarkIcon,
  CheckIcon,
  ContinueIcon,
  DeeperIcon,
  EditIcon,
  ExternalIcon,
  LessLikeIcon,
  MoreLikeIcon,
  NextIcon,
  ReplayIcon,
} from "../icons";

type Mode = "segment" | "completed" | "original";

export function WatchView({ initialClip, autoplay }: { initialClip: ClipView; autoplay: boolean }) {
  const toast = useToast();
  const playerRef = useRef<YouTubePlayerHandle>(null);
  const [clip, setClip] = useState(initialClip);
  const [mode, setMode] = useState<Mode>("segment");
  const [position, setPosition] = useState(initialClip.startSeconds);
  const [error, setError] = useState<string | null>(null);
  const [hintDueFor, setHintDueFor] = useState<string | null>(null);
  const [playedId, setPlayedId] = useState<string | null>(null);
  const [next, setNext] = useState<ClipView | null>(null);
  const [deeper, setDeeper] = useState<ClipView[]>([]);
  const [deeperOpen, setDeeperOpen] = useState(false);
  const watched = useRef({ seconds: 0, last: null as number | null, maxPos: initialClip.startSeconds });
  const openedLogged = useRef(new Set<string>());

  const clipRef = useRef(clip);
  const modeRef = useRef(mode);
  useEffect(() => {
    clipRef.current = clip;
    modeRef.current = mode;
  });

  const youtubeId = clip.source.youtubeVideoId;
  const hue = topicHue(clip.topic);
  const segmentLength = clip.endSeconds - clip.startSeconds;
  const progress = Math.min(1, Math.max(0, (position - clip.startSeconds) / segmentLength));

  // Per-clip setup: log "opened", prefetch Next / Go Deeper so taps respond instantly.
  useEffect(() => {
    markSeen(clip.id);
    if (!openedLogged.current.has(clip.id)) {
      openedLogged.current.add(clip.id);
      void track({ clipId: clip.id, action: "opened" });
    }
    const exclude = encodeURIComponent(getSeen().join(","));
    let cancelled = false;
    api<{ clip: ClipView | null }>(`/api/clips/${clip.id}/next?exclude=${exclude}`)
      .then((r) => !cancelled && setNext(r.clip))
      .catch(() => undefined);
    api<{ clips: ClipView[] }>(`/api/clips/${clip.id}/deeper?exclude=${exclude}`)
      .then((r) => !cancelled && setDeeper(r.clips.slice(0, 3)))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [clip.id]);

  // If autoplay is blocked (common on iOS), nudge the user to tap the video.
  const waitingToPlay = autoplay && playedId !== clip.id && !error && mode === "segment";
  useEffect(() => {
    if (!waitingToPlay) return;
    const t = setTimeout(() => setHintDueFor(clip.id), 3500);
    return () => clearTimeout(t);
  }, [waitingToPlay, clip.id]);
  const showTapHint = waitingToPlay && hintDueFor === clip.id;

  const onReady = useCallback((duration: number) => {
    const source = clipRef.current.source;
    const key = `clipwise.meta.${source.id}`;
    if (sessionStore.read(key)) return;
    sessionStore.write(key, true);
    // Fill in missing duration/channel for this video (server only overwrites blanks).
    void api(`/api/sources/${source.id}/refresh`, { body: { durationSeconds: duration > 0 ? duration : null } }).catch(() => undefined);
  }, []);

  const onProgress = useCallback((t: number) => {
    const c = clipRef.current;
    // Ignore stale readings from the previous clip right after switching.
    if (modeRef.current === "segment" && (t < c.startSeconds - 3 || t > c.endSeconds + 3)) return;
    const w = watched.current;
    if (w.last !== null && t > w.last && t - w.last < 2) w.seconds += t - w.last;
    w.last = t;
    w.maxPos = Math.max(w.maxPos, t);
    setPosition(t);
  }, []);

  const onSegmentEnd = useCallback(() => {
    if (modeRef.current !== "segment") return;
    const c = clipRef.current;
    setMode("completed");
    setPosition(c.endSeconds);
    void track({ clipId: c.id, action: "completed", watchSeconds: Math.round(watched.current.seconds), completionRatio: 1 });
  }, []);

  const onError = useCallback((message: string) => setError(message), []);

  const onPlayingChange = useCallback((p: boolean) => {
    if (p) setPlayedId(clipRef.current.id);
  }, []);

  const goTo = useCallback((target: ClipView) => {
    watched.current = { seconds: 0, last: null, maxPos: target.startSeconds };
    clipRef.current = target;
    modeRef.current = "segment";
    setClip(target);
    setMode("segment");
    setPosition(target.startSeconds);
    setError(null);
    setDeeperOpen(false);
    setNext(null);
    setDeeper([]);
    window.history.replaceState(null, "", `/watch/${target.id}`);
    window.scrollTo({ top: 0 });
  }, []);

  const completionRatio = () =>
    Math.min(1, Math.max(0, (watched.current.maxPos - clipRef.current.startSeconds) / (clipRef.current.endSeconds - clipRef.current.startSeconds)));

  const handleNext = async () => {
    if (mode === "segment" && completionRatio() < 0.25) {
      void track({ clipId: clip.id, action: "skipped", watchSeconds: Math.round(watched.current.seconds), completionRatio: completionRatio() });
    }
    let target = next;
    if (!target) {
      try {
        target = (await api<{ clip: ClipView | null }>(`/api/clips/${clip.id}/next?exclude=${encodeURIComponent(getSeen().join(","))}`)).clip;
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "Couldn't load the next clip");
        return;
      }
    }
    if (target) goTo(target);
    else toast("No other clips yet. Add some videos!");
  };

  const continueOriginal = () => {
    setMode("original");
    void track({ clipId: clip.id, action: "continued_original" });
    playerRef.current?.play();
  };

  const replay = () => {
    watched.current = { seconds: 0, last: null, maxPos: clip.startSeconds };
    setMode("segment");
    setPosition(clip.startSeconds);
    playerRef.current?.restartSegment();
  };

  const toggleSave = async () => {
    const saved = !clip.saved;
    setClip((c) => ({ ...c, saved }));
    try {
      await api(`/api/clips/${clip.id}/save`, { body: { saved } });
      toast(saved ? "Saved" : "Removed from Saved");
    } catch (err) {
      setClip((c) => ({ ...c, saved: !saved }));
      toast(err instanceof ApiError ? err.message : "Couldn't save");
    }
  };

  const feedback = async (action: "more_like_this" | "less_like_this") => {
    await track({ clipId: clip.id, action });
    toast(action === "more_like_this" ? `More ${clip.topic} in your feed` : `Less ${clip.topic} in your feed`);
    // Refresh the prefetched Next pick so it reflects the new preference.
    api<{ clip: ClipView | null }>(`/api/clips/${clip.id}/next?exclude=${encodeURIComponent(getSeen().join(","))}`)
      .then((r) => setNext(r.clip))
      .catch(() => undefined);
  };

  return (
    <div className="min-h-[100dvh] bg-black pb-[calc(var(--safe-bottom)+2rem)]">
      <header
        className="sticky top-0 z-30 flex items-center gap-2 bg-black/85 px-2 backdrop-blur"
        style={{ paddingTop: "var(--safe-top)" }}
      >
        <Link href="/" className="flex h-12 items-center gap-1 rounded-full px-3 text-sm font-medium text-white/80 hover:text-white" aria-label="Back to feed">
          <ArrowLeftIcon size={20} /> Feed
        </Link>
        <p className="min-w-0 flex-1 truncate text-center text-xs text-white/45">
          {clip.source.channel ? `${clip.source.channel} · ` : ""}
          {clip.source.title}
        </p>
        {youtubeId && (
          <a
            href={youTubeWatchUrl(youtubeId, clip.startSeconds)}
            target="_blank"
            rel="noreferrer"
            className="flex h-12 w-12 items-center justify-center text-white/60 hover:text-white"
            aria-label="Open on YouTube"
            title="Open on YouTube"
          >
            <ExternalIcon size={18} />
          </a>
        )}
      </header>

      <div className="mx-auto w-full max-w-4xl">
        <div className="relative aspect-video w-full overflow-hidden bg-neutral-900 sm:rounded-2xl">
          {youtubeId ? (
            <YouTubePlayer
              ref={playerRef}
              videoId={youtubeId}
              startSeconds={clip.startSeconds}
              endSeconds={clip.endSeconds}
              boundaryActive={mode === "segment"}
              autoplay={autoplay}
              onReady={onReady}
              onProgress={onProgress}
              onPlayingChange={onPlayingChange}
              onSegmentEnd={onSegmentEnd}
              onError={onError}
              className="absolute inset-0 [&_iframe]:h-full [&_iframe]:w-full"
            />
          ) : (
            <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-white/60">
              This source isn’t a YouTube video. Local media playback isn’t available yet.
            </div>
          )}
          {error && (
            <div role="alert" data-testid="player-error" className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-neutral-950/95 p-6 text-center">
              <p className="font-semibold">Can’t play this here</p>
              <p className="max-w-sm text-sm text-white/60">{error}</p>
              <div className="flex flex-wrap justify-center gap-2">
                {youtubeId && (
                  <a className="btn btn-ghost" href={youTubeWatchUrl(youtubeId, clip.startSeconds)} target="_blank" rel="noreferrer">
                    <ExternalIcon size={16} /> Open on YouTube
                  </a>
                )}
                <button type="button" className="btn btn-ghost" onClick={() => void handleNext()}>
                  <NextIcon size={16} /> Next clip
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Segment progress */}
        <div className="px-4 pt-3" data-testid="segment-progress">
          <div className="relative h-1.5 overflow-hidden rounded-full bg-white/10" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)} aria-label="Segment progress">
            <div className="h-full rounded-full transition-[width] duration-200" style={{ width: `${progress * 100}%`, background: `hsl(${hue} 85% 65%)` }} />
          </div>
          <div className="mt-1.5 flex justify-between text-[11px] tabular-nums text-white/45">
            <span>{formatTimestamp(clip.startSeconds)}</span>
            <span data-testid="watch-mode">
              {mode === "original" ? "Playing full video" : mode === "completed" ? "Segment complete" : `${formatDuration(segmentLength)} segment`}
            </span>
            <span>{formatTimestamp(clip.endSeconds)}</span>
          </div>
          {showTapHint && <p className="mt-2 text-center text-xs text-accent">Tap the video to start. Your browser blocked autoplay.</p>}
        </div>

        <section className="fade-up px-5 pt-5" key={clip.id}>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.12em]" style={{ background: `hsl(${hue} 60% 50% / 0.18)`, color: `hsl(${hue} 85% 78%)` }}>
              {clip.topic}
            </span>
            {!clip.timestampsVerified && (
              <Link href={`/clips/${clip.id}/edit`} className="inline-flex items-center gap-1 rounded-full bg-white/8 px-2.5 py-1 text-xs text-white/60 hover:text-white" title="Demo clip boundaries are estimates. Tap to adjust.">
                <EditIcon size={12} /> Approximate timestamps
              </Link>
            )}
          </div>
          <h1 className="mt-3 text-balance text-2xl font-bold leading-tight tracking-tight sm:text-3xl" data-testid="watch-title">
            {clip.title}
          </h1>
          {clip.hook && <p className="mt-2 text-pretty text-white/75">{clip.hook}</p>}
          {clip.summary && <p className="mt-3 text-pretty text-sm leading-relaxed text-white/50">{clip.summary}</p>}

          <div className="mt-5 grid grid-cols-4 gap-2">
            <ActionButton label={clip.saved ? "Saved" : "Save"} active={clip.saved} onClick={() => void toggleSave()}>
              <BookmarkIcon filled={clip.saved} />
            </ActionButton>
            <ActionButton label="More like this" onClick={() => void feedback("more_like_this")}>
              <MoreLikeIcon />
            </ActionButton>
            <ActionButton label="Less like this" onClick={() => void feedback("less_like_this")}>
              <LessLikeIcon />
            </ActionButton>
            <ActionButton label="Next" onClick={() => void handleNext()}>
              <NextIcon />
            </ActionButton>
          </div>

          {mode === "original" && (
            <button type="button" onClick={replay} className="btn btn-ghost mt-4 w-full">
              <ReplayIcon size={18} /> Back to the segment
            </button>
          )}
        </section>
      </div>

      {mode === "completed" && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 backdrop-blur-sm sm:items-center" role="dialog" aria-modal="true" aria-labelledby="done-title" data-testid="completion">
          <div className="fade-up w-full max-w-md rounded-t-3xl border border-line bg-panel p-5 sm:rounded-3xl" style={{ paddingBottom: "calc(var(--safe-bottom) + 1.25rem)" }}>
            <div className="flex items-center gap-2 text-sm font-semibold text-emerald-300">
              <CheckIcon size={18} /> Segment complete
            </div>
            <p id="done-title" className="mt-1 line-clamp-2 text-lg font-bold leading-snug">
              {clip.title}
            </p>

            {!deeperOpen ? (
              <>
                <div className="mt-4 grid grid-cols-2 gap-2">
                  <button type="button" className="btn btn-light h-12" onClick={() => void handleNext()} autoFocus>
                    <NextIcon size={18} /> Next
                  </button>
                  <button type="button" className="btn btn-ghost h-12" onClick={continueOriginal}>
                    <ContinueIcon size={18} /> Continue original
                  </button>
                  <button type="button" className="btn btn-ghost h-12" onClick={() => setDeeperOpen(true)} disabled={deeper.length === 0}>
                    <DeeperIcon size={18} /> Go deeper
                  </button>
                  <button type="button" className="btn btn-ghost h-12" onClick={replay}>
                    <ReplayIcon size={18} /> Replay
                  </button>
                </div>
                <div className="mt-3 grid grid-cols-3 gap-2">
                  <SmallAction label={clip.saved ? "Saved" : "Save"} active={clip.saved} onClick={() => void toggleSave()}>
                    <BookmarkIcon size={18} filled={clip.saved} />
                  </SmallAction>
                  <SmallAction label="More like this" onClick={() => void feedback("more_like_this")}>
                    <MoreLikeIcon size={18} />
                  </SmallAction>
                  <SmallAction label="Less like this" onClick={() => void feedback("less_like_this")}>
                    <LessLikeIcon size={18} />
                  </SmallAction>
                </div>
                {next && (
                  <p className="mt-3 truncate text-center text-xs text-white/40">
                    Up next: {next.title}
                  </p>
                )}
              </>
            ) : (
              <div className="mt-4">
                <p className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-white/45">Go deeper</p>
                <ul className="space-y-2">
                  {deeper.map((d) => (
                    <li key={d.id}>
                      <button type="button" onClick={() => goTo(d)} className="w-full rounded-2xl bg-white/6 px-4 py-3 text-left transition hover:bg-white/10 active:scale-[0.99]">
                        <p className="line-clamp-2 font-semibold leading-snug">{d.title}</p>
                        <p className="mt-0.5 text-xs text-white/45">
                          {d.topic} · {formatDuration(d.durationSeconds)}
                          {d.sourceVideoId === clip.sourceVideoId ? " · same video" : ""}
                        </p>
                      </button>
                    </li>
                  ))}
                </ul>
                <button type="button" className="btn btn-ghost mt-3 w-full" onClick={() => setDeeperOpen(false)}>
                  Back
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ActionButton({ label, onClick, active, children }: { label: string; onClick: () => void; active?: boolean; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`flex h-16 flex-col items-center justify-center gap-1 rounded-2xl text-[11px] font-medium transition active:scale-95 ${
        active ? "bg-accent/20 text-accent" : "bg-white/7 text-white/80 hover:bg-white/12"
      }`}
    >
      {children}
      {label}
    </button>
  );
}

function SmallAction({ label, onClick, active, children }: { label: string; onClick: () => void; active?: boolean; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`flex h-11 items-center justify-center gap-1.5 rounded-xl text-xs font-medium transition active:scale-95 ${
        active ? "bg-accent/20 text-accent" : "bg-white/5 text-white/70 hover:bg-white/10"
      }`}
    >
      {children}
      <span className="truncate">{label}</span>
    </button>
  );
}
