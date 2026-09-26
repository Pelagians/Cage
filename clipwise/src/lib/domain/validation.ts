/**
 * Clip validation shared by manual creation, ingest review and the API.
 * Returns friendly, field-level messages instead of throwing.
 */
import { parseTimestamp } from "./time";

export const CLIP_MIN_SECONDS = 5;
export const CLIP_MAX_SECONDS = 60 * 60;

export interface ClipDraftInput {
  title?: unknown;
  hook?: unknown;
  summary?: unknown;
  topic?: unknown;
  tags?: unknown;
  start?: unknown; // number of seconds or timestamp string
  end?: unknown;
}

export interface ValidClip {
  title: string;
  hook: string;
  summary: string;
  topic: string;
  tags: string[];
  startSeconds: number;
  endSeconds: number;
}

export type ValidationResult<T> =
  | { ok: true; value: T }
  | { ok: false; errors: Record<string, string> };

export function toSeconds(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) && value >= 0 ? value : null;
  if (typeof value === "string") return parseTimestamp(value);
  return null;
}

export function normalizeTags(value: unknown): string[] {
  const list = Array.isArray(value)
    ? value
    : typeof value === "string"
      ? value.split(/[,#\n]/)
      : [];
  const out: string[] = [];
  for (const item of list) {
    if (typeof item !== "string") continue;
    const tag = item.trim().toLowerCase().replace(/\s+/g, " ").slice(0, 40);
    if (tag && !out.includes(tag)) out.push(tag);
    if (out.length >= 12) break;
  }
  return out;
}

function str(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

export function validateClipDraft(
  input: ClipDraftInput,
  opts: { videoDurationSeconds?: number | null } = {},
): ValidationResult<ValidClip> {
  const errors: Record<string, string> = {};

  const title = str(input.title);
  if (!title) errors.title = "Title is required.";
  else if (title.length > 140) errors.title = "Title must be 140 characters or fewer.";

  const hook = str(input.hook);
  if (hook.length > 400) errors.hook = "Hook must be 400 characters or fewer.";

  const summary = str(input.summary);
  if (summary.length > 4000) errors.summary = "Summary is too long (max 4000 characters).";

  const topic = str(input.topic) || "General";
  if (topic.length > 60) errors.topic = "Topic must be 60 characters or fewer.";

  const rawStart = input.start;
  const rawEnd = input.end;
  const start = toSeconds(rawStart);
  const end = toSeconds(rawEnd);

  if (rawStart === undefined || rawStart === null || rawStart === "") errors.start = "Start time is required.";
  else if (typeof rawStart === "number" && rawStart < 0) errors.start = "Start time can't be negative.";
  else if (start === null) errors.start = "Start time isn't a valid timestamp (try 1:25 or 1:02:11).";

  if (rawEnd === undefined || rawEnd === null || rawEnd === "") errors.end = "End time is required.";
  else if (typeof rawEnd === "number" && rawEnd < 0) errors.end = "End time can't be negative.";
  else if (end === null) errors.end = "End time isn't a valid timestamp (try 3:40).";

  if (start !== null && end !== null && !errors.start && !errors.end) {
    if (end <= start) errors.end = "End time must be after the start time.";
    else if (end - start < CLIP_MIN_SECONDS) errors.end = `Clips must be at least ${CLIP_MIN_SECONDS} seconds long.`;
    else if (end - start > CLIP_MAX_SECONDS) errors.end = "Clips can't be longer than 60 minutes.";
    else if (opts.videoDurationSeconds && end > opts.videoDurationSeconds + 1) {
      errors.end = "End time is past the end of the video.";
    }
  }

  if (Object.keys(errors).length > 0) return { ok: false, errors };
  return {
    ok: true,
    value: {
      title,
      hook,
      summary,
      topic,
      tags: normalizeTags(input.tags),
      startSeconds: Math.round(start! * 10) / 10,
      endSeconds: Math.round(end! * 10) / 10,
    },
  };
}

/** Title-case a topic label so "economic history" and "Economic History" merge. */
export function normalizeTopic(topic: string): string {
  const t = topic.trim().replace(/\s+/g, " ");
  if (!t) return "General";
  const small = new Set(["and", "of", "the", "in", "on", "for", "to", "a", "vs"]);
  return t
    .split(" ")
    .map((w, i) => {
      if (w.length > 1 && w === w.toUpperCase()) return w; // keep acronyms like AI, GPS
      const lower = w.toLowerCase();
      if (i > 0 && small.has(lower)) return lower;
      return lower[0]!.toUpperCase() + lower.slice(1);
    })
    .join(" ");
}
