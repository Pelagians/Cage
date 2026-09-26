"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ClipView, SourceVideo } from "@/lib/types";
import { formatDuration } from "@/lib/domain/time";
import { api, ApiError } from "@/lib/client/api";
import { sessionStore } from "@/lib/client/session";
import { useToast } from "../Toast";
import { ClipRow } from "../ClipRow";
import { EmptyState } from "../States";
import { EditIcon, PlusIcon, TrashIcon } from "../icons";

export function LibraryView({ sources, clips }: { sources: (SourceVideo & { clipCount: number })[]; clips: ClipView[] }) {
  const router = useRouter();
  const toast = useToast();

  const removeSource = async (s: SourceVideo & { clipCount: number }) => {
    if (!window.confirm(`Delete “${s.title}” and its ${s.clipCount} clip(s)?`)) return;
    try {
      await api(`/api/sources/${s.id}`, { method: "DELETE" });
      sessionStore.write("clipwise.feed", null);
      toast("Video deleted");
      router.refresh();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't delete");
    }
  };

  if (sources.length === 0) {
    return <EmptyState title="No videos yet" body="Add a YouTube video with a transcript or a single manual clip." action={{ href: "/ingest", label: "Add a video" }} />;
  }

  return (
    <div className="space-y-6">
      {sources.map((s) => {
        const own = clips.filter((c) => c.sourceVideoId === s.id).sort((a, b) => a.startSeconds - b.startSeconds);
        return (
          <section key={s.id} className="rounded-2xl border border-line p-3">
            <div className="flex items-start justify-between gap-2 px-1 pb-2">
              <div className="min-w-0">
                <p className="font-semibold leading-snug">{s.title}</p>
                <p className="text-xs text-white/45">
                  {s.channel || "Unknown channel"}
                  {s.durationSeconds ? ` · ${formatDuration(s.durationSeconds)}` : ""}
                  {s.isDemo ? " · demo" : ""}
                  {` · ${s.clipCount} clip${s.clipCount === 1 ? "" : "s"}`}
                </p>
              </div>
              <div className="flex shrink-0 gap-1">
                <Link href={`/ingest?tab=manual&source=${s.id}`} className="flex h-9 w-9 items-center justify-center rounded-full bg-white/8 hover:bg-white/14" aria-label={`Add clip to ${s.title}`} title="Add clip">
                  <PlusIcon size={16} />
                </Link>
                <button type="button" onClick={() => void removeSource(s)} className="flex h-9 w-9 items-center justify-center rounded-full text-white/50 hover:bg-red-500/15 hover:text-red-300" aria-label={`Delete ${s.title}`} title="Delete video">
                  <TrashIcon size={16} />
                </button>
              </div>
            </div>
            {own.length > 0 && (
              <ul className="space-y-2">
                {own.map((c) => (
                  <ClipRow
                    key={c.id}
                    clip={c}
                    actions={
                      <Link href={`/clips/${c.id}/edit`} className="flex h-10 w-10 items-center justify-center rounded-full bg-white/8 hover:bg-white/14" aria-label={`Edit ${c.title}`} title="Edit">
                        <EditIcon size={16} />
                      </Link>
                    }
                  />
                ))}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}
