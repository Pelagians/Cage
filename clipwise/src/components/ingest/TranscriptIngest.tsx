"use client";

import Link from "next/link";
import { useState } from "react";
import type { ClipCandidate } from "@/lib/ingest/pipeline";
import { formatDuration, formatTimestamp, parseTimestamp } from "@/lib/domain/time";
import { validateClipDraft } from "@/lib/domain/validation";
import { extractYouTubeId } from "@/lib/domain/youtube";
import { api, ApiError } from "@/lib/client/api";
import { clearFeedCache } from "@/lib/client/session";
import { useToast } from "../Toast";
import { ErrorPanel } from "../States";
import { CheckIcon, PlayIcon, TrashIcon } from "../icons";
import { ClipFields, type ClipFieldValues } from "./ClipFields";
import { PreviewPlayer } from "./PreviewPlayer";
import { useVideoLookup, VideoLookupHint } from "./useVideoLookup";

interface Proposal {
  videoId: string;
  existingSourceId: string | null;
  candidates: ClipCandidate[];
  cueCount: number;
  warnings: string[];
  enrichment: string;
}

interface Draft extends ClipFieldValues {
  id: string;
  approved: boolean;
  qualityScore: number;
  lowValue: boolean;
  notes: string[];
  enrichedBy: string;
}

const SAMPLE = `0:00 Introduction
0:04 In the third century the Roman Empire faced a crisis that nearly destroyed it.
0:21 Underneath the political chaos was a slower and quieter problem: money.
0:38 The Roman Monetary System
0:42 The backbone of Roman money was the silver denarius.
0:51 Its value came from the silver it contained, and everyone knew roughly how much that was.
1:14 As long as the silver content stayed stable, prices stayed fairly stable too.
2:02 This worked for two centuries, until the state began spending more than it could collect.
2:15 Debasement
2:18 Now, what do you do when you owe more silver than you have?
2:26 Emperors found a tempting answer: put less silver in each coin.
3:01 In the short run this looked like free money for the treasury.
3:36 Good coins vanished from circulation while debased coins flooded the markets.
4:00 Why the Army Became So Expensive
4:04 The biggest item in the imperial budget was the army.
4:35 Each new emperor offered donatives, special bonuses, to secure the loyalty of the troops.
4:59 So military spending rose at exactly the moment the silver supply was shrinking.
5:36 Eventually the state started paying soldiers in food, clothing and goods instead of money.`;

function toDraft(c: ClipCandidate): Draft {
  return {
    id: c.candidateId,
    title: c.title,
    hook: c.hook,
    summary: c.summary,
    topic: c.topic,
    tags: c.tags.join(", "),
    start: formatTimestamp(c.startSeconds),
    end: formatTimestamp(c.endSeconds),
    approved: false,
    qualityScore: c.qualityScore,
    lowValue: c.lowValue,
    notes: c.notes,
    enrichedBy: c.enrichedBy,
  };
}

export function TranscriptIngest({ topics }: { topics: string[] }) {
  const toast = useToast();
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [channel, setChannel] = useState("");
  const [duration, setDuration] = useState("");
  const [transcript, setTranscript] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [draftErrors, setDraftErrors] = useState<Record<string, Record<string, string>>>({});
  const [preview, setPreview] = useState<{ start: number; end: number } | null>(null);
  const [saved, setSaved] = useState<{ count: number; firstClipId?: string } | null>(null);
  const lookup = useVideoLookup(url, (meta) => {
    if (meta.title && !title) setTitle(meta.title);
    if (meta.channel && !channel) setChannel(meta.channel);
  });

  const durationSeconds = duration.trim() ? parseTimestamp(duration) : null;

  const generate = async () => {
    setFormError(null);
    const errs: Record<string, string> = {};
    if (!url.trim()) errs.url = "Paste the YouTube URL for this transcript.";
    else if (!extractYouTubeId(url)) errs.url = "That doesn't look like a YouTube video URL.";
    if (!transcript.trim()) errs.transcript = "Paste a timestamped transcript (or use Manual clip instead).";
    if (duration.trim() && durationSeconds === null) errs.duration = "Use a format like 45:10 or 1:02:11.";
    setErrors(errs);
    if (Object.keys(errs).length) {
      const first = { url: "ing-url", duration: "ing-duration", transcript: "ing-transcript" }[Object.keys(errs)[0]!];
      const el = first ? document.getElementById(first) : null;
      el?.focus();
      el?.scrollIntoView({ block: "center", behavior: "smooth" });
      return;
    }

    setBusy(true);
    try {
      const res = await api<Proposal>("/api/ingest/propose", {
        body: { url, title, transcript, durationSeconds },
      });
      setProposal(res);
      setDrafts(res.candidates.map(toDraft));
      setDraftErrors({});
      setPreview(null);
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(err.fields);
        if (!Object.keys(err.fields).length) setFormError(err.message);
      } else setFormError("Couldn't generate clips.");
    } finally {
      setBusy(false);
    }
  };

  const update = (id: string, patch: Partial<Draft>) => {
    setDrafts((list) => list.map((d) => (d.id === id ? { ...d, ...patch } : d)));
    setDraftErrors((e) => {
      if (!e[id]) return e;
      const next = { ...e };
      delete next[id];
      return next;
    });
  };

  const approved = drafts.filter((d) => d.approved);

  const commit = async () => {
    const errs: Record<string, Record<string, string>> = {};
    for (const d of approved) {
      const r = validateClipDraft(d, { videoDurationSeconds: durationSeconds });
      if (!r.ok) errs[d.id] = r.errors;
    }
    setDraftErrors(errs);
    if (Object.keys(errs).length) {
      toast("Fix the highlighted clips first");
      return;
    }
    setBusy(true);
    try {
      const res = await api<{ clips: { id: string }[] }>("/api/ingest/commit", {
        body: {
          url,
          title,
          channel,
          durationSeconds,
          clips: approved.map((d) => ({
            candidateId: d.id,
            title: d.title,
            hook: d.hook,
            summary: d.summary,
            topic: d.topic,
            tags: d.tags,
            start: d.start,
            end: d.end,
            qualityScore: d.qualityScore,
          })),
        },
      });
      clearFeedCache();
      setSaved({ count: res.clips.length, firstClipId: res.clips[0]?.id });
    } catch (err) {
      if (err instanceof ApiError && Object.keys(err.fields).length) {
        const byDraft: Record<string, Record<string, string>> = {};
        for (const [key, msg] of Object.entries(err.fields)) {
          const [id, field] = key.split(".");
          if (id && field) (byDraft[id] ??= {})[field] = msg;
        }
        setDraftErrors(byDraft);
      }
      toast(err instanceof ApiError ? err.message : "Couldn't save clips");
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    setProposal(null);
    setDrafts([]);
    setSaved(null);
    setTranscript("");
    setUrl("");
    setTitle("");
    setChannel("");
    setDuration("");
    setPreview(null);
  };

  if (saved) {
    return (
      <div className="rounded-2xl bg-panel p-6 text-center" data-testid="ingest-success">
        <CheckIcon size={32} className="mx-auto text-emerald-300" />
        <p className="mt-2 text-lg font-semibold">
          Saved {saved.count} clip{saved.count === 1 ? "" : "s"}
        </p>
        <p className="mt-1 text-sm text-white/55">They’re in your feed now, and new clips get a small novelty boost.</p>
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          <Link href="/" className="btn btn-primary">
            Open feed
          </Link>
          {saved.firstClipId && (
            <Link href={`/watch/${saved.firstClipId}`} className="btn btn-ghost">
              Watch first clip
            </Link>
          )}
          <button type="button" className="btn btn-ghost" onClick={reset}>
            Ingest another
          </button>
        </div>
      </div>
    );
  }

  if (proposal) {
    return (
      <div className="space-y-4" data-testid="review">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-lg font-semibold">Review {drafts.length} proposed clips</p>
            <p className="text-xs text-white/45">
              {proposal.cueCount} transcript lines · {proposal.enrichment}. Nothing is saved until you approve.
            </p>
          </div>
          <button type="button" className="btn btn-ghost shrink-0" onClick={() => setProposal(null)}>
            Edit input
          </button>
        </div>
        {proposal.warnings.map((w) => (
          <p key={w} className="rounded-xl bg-amber-400/10 px-3 py-2 text-sm text-amber-100/85">
            {w}
          </p>
        ))}

        {preview && (
          <div className="sticky top-2 z-20">
            <PreviewPlayer videoId={proposal.videoId} start={preview.start} end={preview.end} onClose={() => setPreview(null)} />
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn btn-ghost" onClick={() => setDrafts((l) => l.map((d) => ({ ...d, approved: !d.lowValue })))}>
            Approve all
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => setDrafts((l) => l.map((d) => ({ ...d, approved: false })))}>
            Clear approvals
          </button>
        </div>

        {drafts.length === 0 && <p className="text-sm text-white/55">All candidates deleted. Edit the input to try again.</p>}

        <ol className="space-y-3">
          {drafts.map((d, i) => {
            const s = parseTimestamp(d.start);
            const e = parseTimestamp(d.end);
            const errs = draftErrors[d.id];
            return (
              <li
                key={d.id}
                data-testid="candidate"
                className={`rounded-2xl border p-4 transition ${d.approved ? "border-emerald-400/40 bg-emerald-400/[0.04]" : "border-line bg-panel"}`}
              >
                <div className="mb-3 flex items-center justify-between gap-2">
                  <p className="text-xs font-semibold uppercase tracking-[0.12em] text-white/45">
                    Clip {i + 1} · {s !== null && e !== null && e > s ? formatDuration(e - s) : "invalid time"}
                    {d.enrichedBy === "ai" ? " · AI" : ""}
                    {d.lowValue ? " · likely promo" : ""}
                  </p>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      onClick={() => update(d.id, { approved: !d.approved })}
                      aria-pressed={d.approved}
                      className={`flex h-11 items-center gap-1 rounded-full px-3 text-sm font-semibold ${d.approved ? "bg-emerald-400/20 text-emerald-200" : "bg-white/8 text-white/80 hover:bg-white/14"}`}
                    >
                      <CheckIcon size={16} /> {d.approved ? "Approved" : "Approve"}
                    </button>
                    <button
                      type="button"
                      className="flex h-11 w-11 items-center justify-center rounded-full hover:bg-white/10 disabled:opacity-40"
                      disabled={s === null || e === null || e <= s}
                      onClick={() => s !== null && e !== null && setPreview({ start: s, end: e })}
                      aria-label={`Preview clip ${i + 1}`}
                      title="Preview"
                    >
                      <PlayIcon size={16} />
                    </button>
                    <button
                      type="button"
                      className="flex h-11 w-11 items-center justify-center rounded-full text-white/60 hover:bg-red-500/15 hover:text-red-300"
                      onClick={() => setDrafts((l) => l.filter((x) => x.id !== d.id))}
                      aria-label={`Delete clip ${i + 1}`}
                      title="Delete"
                    >
                      <TrashIcon size={16} />
                    </button>
                  </div>
                </div>
                <ClipFields idPrefix={`cand-${d.id}`} values={d} errors={errs} onChange={(p) => update(d.id, p)} topics={topics} />
                {d.notes.length > 0 && <p className="mt-2 text-xs text-white/40">{d.notes.join(" ")}</p>}
              </li>
            );
          })}
        </ol>

        <div className="sticky z-20 rounded-2xl border border-line bg-ink/90 p-3 backdrop-blur" style={{ bottom: "calc(var(--nav-h) + var(--safe-bottom) + 0.5rem)" }}>
          <button type="button" className="btn btn-primary w-full" disabled={busy || approved.length === 0} onClick={() => void commit()}>
            {busy ? "Saving…" : approved.length ? `Save ${approved.length} approved clip${approved.length === 1 ? "" : "s"}` : "Approve clips to save them"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        void generate();
      }}
      noValidate
    >
      {formError && <ErrorPanel message={formError} />}
      <div>
        <label htmlFor="ing-url" className="mb-1 block text-xs font-medium text-white/60">
          YouTube URL
        </label>
        <input
          id="ing-url"
          className="field"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://www.youtube.com/watch?v=…"
          aria-invalid={!!errors.url || lookup.state === "invalid"}
          autoComplete="off"
          inputMode="url"
        />
        {errors.url ? <p className="mt-1 text-xs text-red-300">{errors.url}</p> : <VideoLookupHint lookup={lookup} />}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="ing-title" className="mb-1 block text-xs font-medium text-white/60">
            Video title <span className="text-white/35">(optional)</span>
          </label>
          <input id="ing-title" className="field" value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div>
          <label htmlFor="ing-channel" className="mb-1 block text-xs font-medium text-white/60">
            Channel <span className="text-white/35">(optional)</span>
          </label>
          <input id="ing-channel" className="field" value={channel} onChange={(e) => setChannel(e.target.value)} />
        </div>
      </div>
      <div>
        <label htmlFor="ing-duration" className="mb-1 block text-xs font-medium text-white/60">
          Video length <span className="text-white/35">(optional, e.g. 45:10)</span>
        </label>
        <input
          id="ing-duration"
          className="field max-w-[10rem] tabular-nums"
          value={duration}
          onChange={(e) => setDuration(e.target.value)}
          aria-invalid={!!errors.duration}
          placeholder="45:10"
        />
        {errors.duration && <p className="mt-1 text-xs text-red-300">{errors.duration}</p>}
      </div>
      <div>
        <div className="mb-1 flex items-baseline justify-between">
          <label htmlFor="ing-transcript" className="text-xs font-medium text-white/60">
            Timestamped transcript
          </label>
          <button type="button" className="text-xs text-accent hover:underline" onClick={() => {
              setTranscript(SAMPLE);
              if (!url.trim()) {
                setUrl("https://www.youtube.com/watch?v=qrebO_9bhuM");
                setTitle((t) => t || "How Inflation Ruined the Roman Economy");
              }
            }}>
            Paste a sample
          </button>
        </div>
        <textarea
          id="ing-transcript"
          className="field min-h-[14rem] font-mono text-sm leading-relaxed"
          value={transcript}
          onChange={(e) => setTranscript(e.target.value)}
          aria-invalid={!!errors.transcript}
          placeholder={"00:00 Introduction…\n00:32 The Roman monetary system…\n01:14 Debasement accelerated when…\n02:41 Military expenses…"}
          spellCheck={false}
        />
        {errors.transcript ? (
          <p className="mt-1 text-xs text-red-300">{errors.transcript}</p>
        ) : (
          <p className="mt-1 text-xs text-white/40">
            Accepts “0:32 text”, “[01:02:11] text”, YouTube’s “Show transcript” copy (time on its own line), SRT and WebVTT.
          </p>
        )}
      </div>
      <button type="submit" className="btn btn-primary w-full" disabled={busy}>
        {busy ? "Finding clips…" : "Generate candidate clips"}
      </button>
    </form>
  );
}
