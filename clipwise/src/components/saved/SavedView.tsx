"use client";

import { useMemo, useState } from "react";
import type { ClipView } from "@/lib/types";
import { api, ApiError } from "@/lib/client/api";
import { useToast } from "../Toast";
import { ClipRow } from "../ClipRow";
import { EmptyState, PageHeader } from "../States";
import { BookmarkIcon, PlayIcon } from "../icons";
import Link from "next/link";

export function SavedView({ initialClips }: { initialClips: ClipView[] }) {
  const toast = useToast();
  const [clips, setClips] = useState(initialClips);
  const [selected, setTopic] = useState<string | null>(null);
  const topics = useMemo(() => [...new Set(clips.map((c) => c.topic))].sort(), [clips]);
  const topic = selected && topics.includes(selected) ? selected : null;
  const visible = topic ? clips.filter((c) => c.topic === topic) : clips;

  const unsave = async (clip: ClipView) => {
    setClips((list) => list.filter((c) => c.id !== clip.id));
    try {
      await api(`/api/clips/${clip.id}/save`, { body: { saved: false } });
      toast("Removed from Saved");
    } catch (err) {
      setClips((list) => [clip, ...list]);
      toast(err instanceof ApiError ? err.message : "Couldn't update");
    }
  };

  return (
    <>
      <PageHeader title="Saved" subtitle={clips.length ? `${clips.length} clip${clips.length === 1 ? "" : "s"} to come back to` : undefined} />
      {clips.length === 0 ? (
        <EmptyState title="Nothing saved yet" body="Tap Save on any idea in the feed and it will wait for you here." action={{ href: "/", label: "Browse the feed" }} />
      ) : (
        <>
          {topics.length > 1 && (
            <div className="no-scrollbar -mx-4 mb-4 flex gap-2 overflow-x-auto px-4" role="toolbar" aria-label="Filter by topic">
              <FilterChip active={!topic} onClick={() => setTopic(null)}>
                All
              </FilterChip>
              {topics.map((t) => (
                <FilterChip key={t} active={topic === t} onClick={() => setTopic(t)}>
                  {t}
                </FilterChip>
              ))}
            </div>
          )}
          <ul className="space-y-2">
            {visible.map((clip) => (
              <ClipRow
                key={clip.id}
                clip={clip}
                actions={
                  <>
                    <Link href={`/watch/${clip.id}`} className="flex h-10 w-10 items-center justify-center rounded-full bg-white/8 hover:bg-white/14" aria-label="Watch again" title="Watch again">
                      <PlayIcon size={16} />
                    </Link>
                    <button type="button" onClick={() => void unsave(clip)} className="flex h-10 w-10 items-center justify-center rounded-full text-accent hover:bg-white/8" aria-label="Unsave" title="Unsave">
                      <BookmarkIcon size={18} filled />
                    </button>
                  </>
                }
              />
            ))}
          </ul>
        </>
      )}
    </>
  );
}

function FilterChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`h-9 shrink-0 rounded-full px-4 text-sm font-medium transition ${active ? "bg-white text-black" : "bg-white/8 text-white/70 hover:bg-white/12"}`}
    >
      {children}
    </button>
  );
}
