"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { ClipView } from "@/lib/types";
import { formatTimestamp, parseTimestamp } from "@/lib/domain/time";
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

export interface SourceOption {
  id: string;
  title: string;
  channel: string;
  youtubeVideoId: string | null;
  durationSeconds: number | null;
}

const EMPTY: ClipFieldValues = { title: "", hook: "", summary: "", topic: "", tags: "", start: "", end: "" };
const NEW = "__new";

function fromClip(c: ClipView): ClipFieldValues {
  return {
    title: c.title,
    hook: c.hook,
    summary: c.summary,
    topic: c.topic,
    tags: c.tags.join(", "),
    start: formatTimestamp(c.startSeconds),
    end: formatTimestamp(c.endSeconds),
  };
}

export function ManualClipForm({
  sources,
  topics,
  editClip,
  defaultSourceId,
}: {
  sources: SourceOption[];
  topics: string[];
  editClip?: ClipView;
  defaultSourceId?: string;
}) {
  const router = useRouter();
  const toast = useToast();
  const [sourceId, setSourceId] = useState<string>(editClip?.sourceVideoId ?? defaultSourceId ?? sources[0]?.id ?? NEW);
  const [url, setUrl] = useState("");
  const [videoTitle, setVideoTitle] = useState("");
  const [channel, setChannel] = useState("");
  const [values, setValues] = useState<ClipFieldValues>(editClip ? fromClip(editClip) : EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<{ start: number; end: number } | null>(null);
  const [created, setCreated] = useState<{ id: string; title: string } | null>(null);
  const lookup = useVideoLookup(sourceId === NEW ? url : "", (meta) => {
    if (meta.title && !videoTitle) setVideoTitle(meta.title);
    if (meta.channel && !channel) setChannel(meta.channel);
  });

  const source = sources.find((s) => s.id === sourceId) ?? null;
  const videoId = sourceId === NEW ? extractYouTubeId(url) : source?.youtubeVideoId ?? null;

  const change = (patch: Partial<ClipFieldValues>) => {
    setValues((v) => ({ ...v, ...patch }));
    setCreated(null);
  };

  const submit = async () => {
    setFormError(null);
    const local = validateClipDraft(values, { videoDurationSeconds: source?.durationSeconds });
    const errs: Record<string, string> = local.ok ? {} : { ...local.errors };
    if (sourceId === NEW && !extractYouTubeId(url)) errs.url = "Paste a valid YouTube URL.";
    setErrors(errs);
    if (Object.keys(errs).length) return;

    setBusy(true);
    try {
      if (editClip) {
        const res = await api<{ clip: ClipView }>(`/api/clips/${editClip.id}`, { method: "PATCH", body: values });
        clearFeedCache();
        toast("Clip updated");
        router.push(`/watch/${res.clip.id}`);
        return;
      }
      let sid = sourceId;
      if (sid === NEW) {
        const res = await api<{ source: { id: string } }>("/api/sources", { body: { url, title: videoTitle, channel } });
        sid = res.source.id;
      }
      const res = await api<{ clip: ClipView }>("/api/clips", { body: { sourceId: sid, ...values } });
      clearFeedCache();
      setCreated({ id: res.clip.id, title: res.clip.title });
      toast("Clip saved");
      if (sourceId === NEW) {
        setSourceId(sid);
        router.refresh(); // pick up the new source in the dropdown
      }
      // Keep topic/tags for the next clip from the same video; clear the rest.
      setValues((v) => ({ ...EMPTY, topic: v.topic, tags: v.tags, start: v.end }));
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(err.fields);
        if (!Object.keys(err.fields).length) setFormError(err.message);
      } else setFormError("Couldn't save the clip.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!editClip || !window.confirm("Delete this clip? Its history and saved state go with it.")) return;
    try {
      await api(`/api/clips/${editClip.id}`, { method: "DELETE" });
      clearFeedCache();
      toast("Clip deleted");
      router.push("/library");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't delete");
    }
  };

  const s = parseTimestamp(values.start);
  const e = parseTimestamp(values.end);
  const canPreview = !!videoId && s !== null && e !== null && e > s;

  return (
    <form
      className="space-y-4"
      noValidate
      onSubmit={(ev) => {
        ev.preventDefault();
        void submit();
      }}
    >
      {formError && <ErrorPanel message={formError} />}

      {!editClip ? (
        <div className="space-y-3 rounded-2xl bg-panel p-4">
          <label htmlFor="man-source" className="block text-xs font-medium text-white/60">
            Video
          </label>
          <select id="man-source" className="field" value={sourceId} onChange={(ev) => setSourceId(ev.target.value)}>
            {sources.map((src) => (
              <option key={src.id} value={src.id}>
                {src.title}
                {src.channel ? `, ${src.channel}` : ""}
              </option>
            ))}
            <option value={NEW}>＋ New YouTube video…</option>
          </select>
          {sourceId === NEW && (
            <>
              <div>
                <input
                  id="man-url"
                  aria-label="YouTube URL"
                  className="field"
                  value={url}
                  onChange={(ev) => setUrl(ev.target.value)}
                  placeholder="https://youtu.be/…"
                  aria-invalid={!!errors.url || lookup.state === "invalid"}
                  inputMode="url"
                />
                {errors.url ? <p className="mt-1 text-xs text-red-300">{errors.url}</p> : <VideoLookupHint lookup={lookup} />}
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <input aria-label="Video title" className="field" value={videoTitle} onChange={(ev) => setVideoTitle(ev.target.value)} placeholder="Video title (optional)" />
                <input aria-label="Channel" className="field" value={channel} onChange={(ev) => setChannel(ev.target.value)} placeholder="Channel (optional)" />
              </div>
            </>
          )}
        </div>
      ) : (
        <p className="text-sm text-white/55">
          From “{editClip.source.title}”{editClip.source.channel ? `, ${editClip.source.channel}` : ""}
        </p>
      )}

      {preview && videoId && <PreviewPlayer videoId={videoId} start={preview.start} end={preview.end} onClose={() => setPreview(null)} />}

      <ClipFields idPrefix="man" values={values} errors={errors} onChange={change} topics={topics} />

      <div className="flex flex-wrap gap-2">
        <button type="submit" className="btn btn-primary flex-1" disabled={busy}>
          <CheckIcon size={18} /> {busy ? "Saving…" : editClip ? "Save changes" : "Save clip"}
        </button>
        <button type="button" className="btn btn-ghost" disabled={!canPreview} onClick={() => s !== null && e !== null && setPreview({ start: s, end: e })}>
          <PlayIcon size={16} /> Preview
        </button>
        {editClip && (
          <button type="button" className="btn btn-danger" onClick={() => void remove()}>
            <TrashIcon size={16} /> Delete
          </button>
        )}
      </div>

      {created && (
        <div className="fade-up rounded-2xl bg-emerald-400/10 p-4 text-sm" data-testid="manual-success">
          <p className="font-semibold text-emerald-200">Saved “{created.title}”</p>
          <p className="mt-1 text-white/60">The form is ready for another clip from the same video.</p>
          <div className="mt-3 flex gap-2">
            <Link className="btn btn-ghost" href={`/watch/${created.id}`}>
              Watch it
            </Link>
            <Link className="btn btn-ghost" href="/">
              Feed
            </Link>
          </div>
        </div>
      )}
    </form>
  );
}
