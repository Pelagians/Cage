"use client";

import { useEffect, useRef, useState } from "react";
import { extractYouTubeId } from "@/lib/domain/youtube";
import { api } from "@/lib/client/api";

export interface Lookup {
  state: "idle" | "invalid" | "checking" | "ok";
  videoId: string | null;
  existingSourceId: string | null;
  status: string | null; // ok | not_embeddable | not_found | unreachable
}

interface MetaResponse {
  videoId: string;
  existingSourceId: string | null;
  meta: { title: string; channel: string } | null;
  status: string;
}

/** Validate a pasted YouTube URL locally, then (debounced) look up title/channel. */
export function useVideoLookup(url: string, onMeta?: (meta: { title: string; channel: string }) => void): Lookup {
  const [lookup, setLookup] = useState<Lookup>({ state: "idle", videoId: null, existingSourceId: null, status: null });
  const onMetaRef = useRef(onMeta);
  useEffect(() => {
    onMetaRef.current = onMeta;
  });

  useEffect(() => {
    const trimmed = url.trim();
    const videoId = trimmed ? extractYouTubeId(trimmed) : null;
    let cancelled = false;
    const timer = setTimeout(() => {
      if (!trimmed) return setLookup({ state: "idle", videoId: null, existingSourceId: null, status: null });
      if (!videoId) return setLookup({ state: "invalid", videoId: null, existingSourceId: null, status: null });
      setLookup({ state: "checking", videoId, existingSourceId: null, status: null });
      api<MetaResponse>(`/api/youtube/meta?url=${encodeURIComponent(trimmed)}`)
        .then((res) => {
          if (cancelled) return;
          setLookup({ state: "ok", videoId: res.videoId, existingSourceId: res.existingSourceId, status: res.status });
          if (res.meta) onMetaRef.current?.(res.meta);
        })
        .catch(() => !cancelled && setLookup({ state: "ok", videoId, existingSourceId: null, status: "unreachable" }));
    }, trimmed ? 450 : 0);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [url]);

  return lookup;
}

export function VideoLookupHint({ lookup }: { lookup: Lookup }) {
  if (lookup.state === "idle") return null;
  if (lookup.state === "invalid")
    return <p className="mt-1 text-xs text-red-300">That doesn’t look like a YouTube video URL (try youtube.com/watch?v=… or youtu.be/…).</p>;
  if (lookup.state === "checking") return <p className="mt-1 text-xs text-white/40">Checking video {lookup.videoId}…</p>;
  const msg =
    lookup.status === "not_embeddable"
      ? "⚠ YouTube says this video can’t be embedded, so it won’t play inside the app."
      : lookup.status === "not_found"
        ? "⚠ YouTube couldn’t find this video. Double-check the link."
        : lookup.status === "unreachable"
          ? "Couldn’t reach YouTube to fetch the title (offline?). You can still continue."
          : "✓ Found on YouTube";
  return (
    <p className={`mt-1 text-xs ${lookup.status === "ok" ? "text-emerald-300/80" : lookup.status === "unreachable" ? "text-white/40" : "text-amber-200/90"}`}>
      Video ID <code>{lookup.videoId}</code>. {msg}
      {lookup.existingSourceId ? " Already in your library; new clips will be added to it." : ""}
    </p>
  );
}
