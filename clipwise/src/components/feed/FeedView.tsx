"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import type { FeedClip } from "@/lib/recommend/service";
import { api, ApiError } from "@/lib/client/api";
import { track, trackLater } from "@/lib/client/interactions";
import { FEED_KEY, markSeen, sessionStore } from "@/lib/client/session";
import { useToast } from "../Toast";
import { ClipCard } from "./ClipCard";
import { RefreshIcon } from "../icons";

const RESTORE_MS = 30 * 60 * 1000;
const impressed = new Set<string>(); // per tab session

interface Stored {
  items: FeedClip[];
  index: number;
  at: number;
}

export function FeedView({ initialClips }: { initialClips: FeedClip[] }) {
  const router = useRouter();
  const toast = useToast();
  const [items, setItems] = useState<FeedClip[]>(initialClips);
  const [active, setActive] = useState(0);
  const [ready, setReady] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const pendingScroll = useRef<number | null>(null);
  const itemsRef = useRef(items);
  const activeRef = useRef(active);
  useEffect(() => {
    itemsRef.current = items;
    activeRef.current = active;
  });

  const scrollToIndex = useCallback((i: number, smooth = true) => {
    const el = containerRef.current;
    if (!el) return;
    el.scrollTo({ top: i * el.clientHeight, behavior: smooth ? "smooth" : "instant" });
  }, []);

  /** Re-rank everything after the current card, keeping what you've already scrolled past. */
  const refreshTail = useCallback(async (base: FeedClip[], index: number) => {
    const head = base.slice(0, index + 1);
    try {
      const res = await api<{ clips: FeedClip[] }>(`/api/feed?exclude=${encodeURIComponent(head.map((c) => c.id).join(","))}`);
      // Keep the current head objects (their saved flags may have been updated meanwhile).
      setItems((prev) => [...prev.slice(0, index + 1), ...res.clips.filter((c) => !head.some((h) => h.id === c.id))]);
      return true;
    } catch {
      return false;
    }
  }, []);

  // Restore position when coming back from Watch mode, then refresh the ranking below it.
  useEffect(() => {
    const stored = sessionStore.read<Stored>(FEED_KEY);
    if (stored && Date.now() - stored.at < RESTORE_MS && stored.items.length > 0) {
      const index = Math.min(stored.index, stored.items.length - 1);
      // Restoring from sessionStorage can only happen after hydration (the server can't
      // see it), so this effect is the right place for it despite the extra render.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setItems(stored.items);
      setActive(index);
      pendingScroll.current = index;
      void refreshTail(stored.items, index);
      // Saves may have changed elsewhere (Saved screen, Watch mode) since this was stored.
      api<{ clips: { id: string }[] }>("/api/saved")
        .then((res) => {
          const saved = new Set(res.clips.map((c) => c.id));
          setItems((list) => list.map((c) => (c.saved === saved.has(c.id) ? c : { ...c, saved: saved.has(c.id) })));
        })
        .catch(() => undefined);
    }
    setReady(true);
  }, [refreshTail]);

  useLayoutEffect(() => {
    if (pendingScroll.current !== null && ready) {
      scrollToIndex(pendingScroll.current, false);
      pendingScroll.current = null;
    }
  }, [ready, items, scrollToIndex]);

  useEffect(() => {
    if (ready) sessionStore.write(FEED_KEY, { items, index: active, at: Date.now() } satisfies Stored);
  }, [items, active, ready]);

  // Track which card is on screen; log an impression after a short dwell.
  useEffect(() => {
    const root = containerRef.current;
    if (!root) return;
    const timers = new Map<Element, ReturnType<typeof setTimeout>>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const el = entry.target as HTMLElement;
          const index = Number(el.dataset.index);
          const clipId = el.dataset.clipId;
          if (entry.isIntersecting) {
            setActive(index);
            if (clipId && !impressed.has(clipId)) {
              timers.set(
                el,
                setTimeout(() => {
                  impressed.add(clipId);
                  trackLater({ clipId, action: "impression" });
                }, 900),
              );
            }
          } else {
            clearTimeout(timers.get(el));
            timers.delete(el);
          }
        }
      },
      { root, threshold: 0.6 },
    );
    root.querySelectorAll(".feed-card").forEach((el) => observer.observe(el));
    return () => {
      observer.disconnect();
      timers.forEach((t) => clearTimeout(t));
    };
  }, [items]);

  const watch = useCallback(
    (clip: FeedClip) => {
      markSeen(clip.id);
      router.push(`/watch/${clip.id}`);
    },
    [router],
  );

  const toggleSave = useCallback(
    async (clip: FeedClip) => {
      const saved = !clip.saved;
      setItems((list) => list.map((c) => (c.id === clip.id ? { ...c, saved } : c)));
      try {
        await api(`/api/clips/${clip.id}/save`, { body: { saved } });
        toast(saved ? "Saved" : "Removed from Saved");
      } catch (err) {
        setItems((list) => list.map((c) => (c.id === clip.id ? { ...c, saved: !saved } : c)));
        toast(err instanceof ApiError ? err.message : "Couldn't save");
      }
    },
    [toast],
  );

  const moreLike = useCallback(
    async (clip: FeedClip, index: number) => {
      await track({ clipId: clip.id, action: "more_like_this" });
      toast(`More ${clip.topic} coming up`);
      await refreshTail(itemsRef.current, index);
    },
    [refreshTail, toast],
  );

  const lessLike = useCallback(
    async (clip: FeedClip, index: number) => {
      await track({ clipId: clip.id, action: "less_like_this" });
      toast(`Showing less ${clip.topic}`);
      await refreshTail(itemsRef.current, index);
      scrollToIndex(index + 1);
    },
    [refreshTail, scrollToIndex, toast],
  );

  const startOver = useCallback(async () => {
    try {
      const res = await api<{ clips: FeedClip[] }>("/api/feed");
      setItems(res.clips);
      setActive(0);
      scrollToIndex(0, false);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't refresh the feed");
    }
  }, [scrollToIndex, toast]);

  // Keyboard navigation for desktop: j/k or arrows, Enter to watch.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
      const i = activeRef.current;
      if (e.key === "ArrowDown" || e.key === "j") {
        e.preventDefault();
        scrollToIndex(Math.min(i + 1, itemsRef.current.length));
      } else if (e.key === "ArrowUp" || e.key === "k") {
        e.preventDefault();
        scrollToIndex(Math.max(i - 1, 0));
      } else if (e.key === "Enter") {
        const clip = itemsRef.current[i];
        if (clip) watch(clip);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [scrollToIndex, watch]);

  if (items.length === 0) {
    return (
      <div className="page flex min-h-[100dvh] flex-col justify-center">
        <div className="rounded-2xl border border-dashed border-line px-6 py-12 text-center">
          <p className="text-xl font-semibold">Your feed is empty</p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-white/55">
            Add a YouTube video and a few timestamped clips, or restore the demo content from Settings.
          </p>
          <div className="mt-5 flex justify-center gap-2">
            <Link href="/ingest" className="btn btn-primary">
              Add a video
            </Link>
            <Link href="/settings" className="btn btn-ghost">
              Settings
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      data-testid="feed"
      className={`no-scrollbar h-[100dvh] snap-y snap-mandatory overflow-y-auto overscroll-contain transition-opacity duration-150 ${
        ready ? "opacity-100" : "opacity-0"
      }`}
    >
      {items.map((clip, i) => (
        <ClipCard
          key={clip.id}
          clip={clip}
          index={i}
          near={Math.abs(i - active) <= 2}
          onWatch={() => watch(clip)}
          onSave={() => void toggleSave(clip)}
          onMore={() => void moreLike(clip, i)}
          onLess={() => void lessLike(clip, i)}
        />
      ))}
      <section
        data-index={items.length}
        className="feed-card flex h-[100dvh] snap-start flex-col items-center justify-center gap-4 px-8 text-center"
        style={{ paddingBottom: "calc(var(--nav-h) + var(--safe-bottom))" }}
      >
        <p className="text-2xl font-bold">You’re all caught up</p>
        <p className="max-w-xs text-sm text-white/55">
          Start another pass (re-ranked by what you’ve liked), or add more videos to widen the feed.
        </p>
        <div className="flex gap-2">
          <button type="button" className="btn btn-light" onClick={() => void startOver()}>
            <RefreshIcon size={18} /> Start over
          </button>
          <Link href="/ingest" className="btn btn-ghost">
            Add videos
          </Link>
        </div>
      </section>
    </div>
  );
}
