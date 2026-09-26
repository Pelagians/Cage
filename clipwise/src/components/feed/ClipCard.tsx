"use client";

import { useState } from "react";
import type { ClipView } from "@/lib/types";
import { formatDuration, formatTimestamp } from "@/lib/domain/time";
import { topicHue } from "@/lib/client/topic-color";
import { BookmarkIcon, LessLikeIcon, MoreLikeIcon, PlayIcon } from "../icons";

interface Props {
  clip: ClipView & { slot?: "personal" | "explore" };
  index: number;
  onWatch: () => void;
  onSave: () => void;
  onMore: () => void;
  onLess: () => void;
  /** Render the (lazy) thumbnail only for cards near the viewport. */
  near: boolean;
}

export function ClipCard({ clip, index, onWatch, onSave, onMore, onLess, near }: Props) {
  const hue = topicHue(clip.topic);
  const [thumbOk, setThumbOk] = useState(true);
  const channel = clip.source.channel;

  return (
    <article
      data-index={index}
      data-clip-id={clip.id}
      aria-label={clip.title}
      className="feed-card relative flex h-[100dvh] w-full snap-start snap-always flex-col overflow-hidden"
      style={{
        background: `radial-gradient(120% 70% at 20% 0%, hsl(${hue} 55% 22% / 0.9), transparent 60%), linear-gradient(180deg, hsl(${hue} 30% 10%), #0b0b0d 75%)`,
      }}
    >
      {near && clip.source.thumbnailUrl && thumbOk && (
        <img
          src={clip.source.thumbnailUrl}
          alt=""
          loading="lazy"
          decoding="async"
          onError={() => setThumbOk(false)}
          className="pointer-events-none absolute inset-0 h-full w-full scale-125 object-cover opacity-[0.18] blur-2xl"
        />
      )}
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-black/10 via-transparent to-black/70" />

      <div
        className="relative mx-auto flex h-full w-full max-w-xl flex-col px-6"
        style={{
          paddingTop: "calc(var(--safe-top) + 1.25rem)",
          paddingBottom: "calc(var(--nav-h) + var(--safe-bottom) + 1.25rem)",
        }}
      >
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-white/60">
          <span className="rounded-full px-2.5 py-1" style={{ background: `hsl(${hue} 60% 50% / 0.18)`, color: `hsl(${hue} 85% 78%)` }}>
            {clip.topic}
          </span>
          {clip.slot === "explore" && (
            <span className="rounded-full bg-white/8 px-2.5 py-1 text-white/55" title="Outside your usual topics, to keep the feed from becoming a bubble">
              Explore
            </span>
          )}
        </div>

        <div className="flex flex-1 flex-col justify-center py-6">
          <h2 className="text-balance text-[2rem] font-extrabold leading-[1.08] tracking-tight sm:text-[2.4rem]">{clip.title}</h2>
          {clip.hook && <p className="mt-4 text-pretty text-[1.07rem] leading-relaxed text-white/75">{clip.hook}</p>}

          <div className="mt-5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-white/50">
            <span className="font-semibold text-white/80">{formatDuration(clip.durationSeconds)}</span>
            {channel && (
              <>
                <span aria-hidden>·</span>
                <span className="truncate">{channel}</span>
              </>
            )}
          </div>
          {clip.tags.length > 0 && (
            <ul className="mt-3 flex flex-wrap gap-1.5" aria-label="Tags">
              {clip.tags.slice(0, 4).map((t) => (
                <li key={t} className="rounded-full border border-white/10 px-2.5 py-0.5 text-xs text-white/55">
                  {t}
                </li>
              ))}
            </ul>
          )}
        </div>

        <p className="mb-3 truncate text-xs text-white/40">
          From “{clip.source.title}” · {formatTimestamp(clip.startSeconds)}–{formatTimestamp(clip.endSeconds)}
        </p>

        <div className="flex items-center gap-2">
          <button type="button" onClick={onWatch} className="btn btn-light h-14 flex-1 text-base" aria-label={`Watch ${clip.title}`}>
            <PlayIcon size={20} />
            Watch
          </button>
          <CardAction label={clip.saved ? "Saved" : "Save"} onClick={onSave} active={clip.saved}>
            <BookmarkIcon filled={clip.saved} />
          </CardAction>
          <CardAction label="More" onClick={onMore} title="More like this">
            <MoreLikeIcon />
          </CardAction>
          <CardAction label="Less" onClick={onLess} title="Less like this">
            <LessLikeIcon />
          </CardAction>
        </div>
      </div>
    </article>
  );
}

function CardAction({
  label,
  title,
  onClick,
  active,
  children,
}: {
  label: string;
  title?: string;
  onClick: () => void;
  active?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title ?? label}
      aria-label={title ?? label}
      aria-pressed={active}
      className={`flex h-14 w-14 shrink-0 flex-col items-center justify-center gap-0.5 rounded-2xl text-[10px] font-medium transition active:scale-95 ${
        active ? "bg-accent/20 text-accent" : "bg-white/8 text-white/80 hover:bg-white/14"
      }`}
    >
      {children}
      <span aria-hidden>{label}</span>
    </button>
  );
}
