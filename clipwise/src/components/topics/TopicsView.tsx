"use client";

import { useState } from "react";
import type { ProfileSummary, TopicSummary } from "@/lib/recommend/service";
import { api, ApiError } from "@/lib/client/api";
import { topicHue } from "@/lib/client/topic-color";
import { useToast } from "../Toast";
import { EmptyState, PageHeader } from "../States";

const TREND: Record<TopicSummary["trend"], { arrow: string; label: string; cls: string }> = {
  "strong-up": { arrow: "↑", label: "Loving it", cls: "text-emerald-300" },
  up: { arrow: "↗", label: "Leaning in", cls: "text-emerald-200/80" },
  neutral: { arrow: "→", label: "Neutral", cls: "text-white/40" },
  down: { arrow: "↘", label: "Cooling", cls: "text-orange-200/80" },
  "strong-down": { arrow: "↓", label: "Showing less", cls: "text-red-300" },
};

export function TopicsView({ initial }: { initial: ProfileSummary }) {
  const toast = useToast();
  const [summary, setSummary] = useState(initial);
  const [busy, setBusy] = useState(false);

  const reset = async () => {
    if (!window.confirm("Reset learned preferences? Your history and saved clips stay; the feed just stops using them.")) return;
    setBusy(true);
    try {
      setSummary(await api<ProfileSummary>("/api/preferences/reset", { body: {} }));
      toast("Preferences reset");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't reset");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title="Topics" subtitle="What the feed has learned from your watching, saves and More/Less taps." />
      {summary.topics.length === 0 ? (
        <EmptyState title="No topics yet" body="Topics appear once you have clips in your library." action={{ href: "/ingest", label: "Add a video" }} />
      ) : (
        <ul className="space-y-2" data-testid="topics">
          {summary.topics.map((t) => {
            const trend = TREND[t.trend];
            const hue = topicHue(t.topic);
            // Map affinity (-1..1) to a bar centred on neutral; coarse on purpose.
            const pct = Math.round(((t.affinity + 1) / 2) * 100);
            return (
              <li key={t.topic} className="rounded-2xl bg-panel px-4 py-3" data-topic={t.topic} data-trend={t.trend}>
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-semibold">{t.topic}</p>
                    <p className="text-xs text-white/40">
                      {t.clipCount} clip{t.clipCount === 1 ? "" : "s"}
                    </p>
                  </div>
                  <p className={`flex shrink-0 items-center gap-1.5 text-sm font-medium ${trend.cls}`}>
                    <span className="text-lg leading-none" aria-hidden>
                      {trend.arrow}
                    </span>
                    {trend.label}
                  </p>
                </div>
                <div className="relative mt-2.5 h-1.5 rounded-full bg-white/8" aria-hidden>
                  <div className="absolute left-1/2 top-[-2px] h-[10px] w-px bg-white/25" />
                  <div
                    className="absolute top-0 h-full rounded-full"
                    style={{
                      left: `${Math.min(50, pct)}%`,
                      width: `${Math.abs(pct - 50)}%`,
                      background: t.affinity >= 0 ? `hsl(${hue} 75% 62%)` : "rgb(248 113 113 / 0.7)",
                    }}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {(summary.likedTags.length > 0 || summary.dislikedTags.length > 0) && (
        <div className="mt-6 space-y-3">
          {summary.likedTags.length > 0 && <TagLine label="More of" tags={summary.likedTags} tone="text-emerald-200/90" />}
          {summary.dislikedTags.length > 0 && <TagLine label="Less of" tags={summary.dislikedTags} tone="text-red-200/80" />}
        </div>
      )}

      <div className="mt-8 rounded-2xl border border-line p-4">
        <p className="text-sm text-white/55">
          Based on {summary.interactionCount} interaction{summary.interactionCount === 1 ? "" : "s"}
          {summary.preferencesResetAt ? ` since your reset on ${new Date(summary.preferencesResetAt).toLocaleDateString()}` : ""}. About a
          quarter of the feed is always kept for exploration (adjust in Settings).
        </p>
        <button type="button" className="btn btn-ghost mt-3" onClick={() => void reset()} disabled={busy}>
          Reset preferences
        </button>
      </div>
    </>
  );
}

function TagLine({ label, tags, tone }: { label: string; tags: string[]; tone: string }) {
  return (
    <div>
      <p className="mb-1.5 text-xs font-semibold uppercase tracking-[0.12em] text-white/40">{label}</p>
      <div className="flex flex-wrap gap-1.5">
        {tags.map((t) => (
          <span key={t} className={`rounded-full bg-white/6 px-2.5 py-1 text-xs ${tone}`}>
            {t}
          </span>
        ))}
      </div>
    </div>
  );
}
