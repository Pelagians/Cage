"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { ClipView } from "@/lib/types";
import { formatDuration, formatTimestamp } from "@/lib/domain/time";
import { topicHue } from "@/lib/client/topic-color";

/** Compact clip list row used by Saved and Library. */
export function ClipRow({ clip, actions }: { clip: ClipView; actions?: React.ReactNode }) {
  const [thumbOk, setThumbOk] = useState(true);
  const imgRef = useRef<HTMLImageElement>(null);
  // A server-rendered image can fail before hydration attaches onError; check once mounted.
  useEffect(() => {
    const img = imgRef.current;
    if (img && img.complete && img.naturalWidth === 0) setThumbOk(false);
  }, []);
  const hue = topicHue(clip.topic);
  return (
    <li className="flex items-center gap-3 rounded-2xl bg-panel p-2.5 pr-3" data-clip-id={clip.id}>
      <Link href={`/watch/${clip.id}`} className="relative h-14 w-24 shrink-0 sm:h-16 sm:w-28 overflow-hidden rounded-xl" style={{ background: `hsl(${hue} 40% 20%)` }} aria-label={`Watch ${clip.title}`}>
        {clip.source.thumbnailUrl && thumbOk && (
          <img ref={imgRef} src={clip.source.thumbnailUrl} alt="" loading="lazy" onError={() => setThumbOk(false)} className="h-full w-full object-cover opacity-80" />
        )}
        <span className="absolute bottom-1 right-1 rounded bg-black/75 px-1 text-[10px] font-semibold tabular-nums">{formatDuration(clip.durationSeconds)}</span>
      </Link>
      <div className="min-w-0 flex-1">
        <Link href={`/watch/${clip.id}`} className="line-clamp-2 text-[0.95rem] font-semibold leading-snug hover:underline">
          {clip.title}
        </Link>
        <p className="mt-0.5 truncate text-xs text-white/45">
          <span style={{ color: `hsl(${hue} 70% 72%)` }}>{clip.topic}</span> · {clip.source.channel || clip.source.title} · {formatTimestamp(clip.startSeconds)}
        </p>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-1">{actions}</div>}
    </li>
  );
}
