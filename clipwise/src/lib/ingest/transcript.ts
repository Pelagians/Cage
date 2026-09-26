/**
 * Transcript parsing: turn pasted text into timed cues.
 *
 * Supported shapes (mixed freely):
 *   00:32 The Roman monetary system…        timestamp then text
 *   [00:32] text / (0:32) text / 0:32 - text
 *   1:02:11 text                             hours
 *   0:32                                     YouTube "Show transcript" copy: timestamp on its
 *   The Roman monetary system…               own line, text on the following line(s)
 *   00:00:32,000 --> 00:00:35,500            SRT / WebVTT cue timings (+ optional index lines)
 * Lines without a timestamp are appended to the previous cue.
 */
import { parseTimestamp } from "../domain/time";

export interface Cue {
  start: number;
  text: string;
}

export class TranscriptParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TranscriptParseError";
  }
}

const TS = String.raw`\d{1,3}:\d{1,2}(?::\d{1,2})?(?:[.,]\d{1,3})?`;
const LEADING_TS = new RegExp(String.raw`^[\[(]?\s*(${TS})\s*[\])]?\s*(?:[-–—:|•]\s*)?(.*)$`);
const SRT_TIMING = new RegExp(String.raw`^(${TS})\s*-->\s*(${TS})`);

export function parseTranscript(raw: string): Cue[] {
  if (!raw || !raw.trim()) throw new TranscriptParseError("The transcript is empty.");

  const lines = raw.replace(/\r\n?/g, "\n").split("\n");
  const cues: Cue[] = [];
  let current: Cue | null = null;

  const push = () => {
    if (current && current.text.trim()) {
      current.text = current.text.replace(/\s+/g, " ").trim();
      cues.push(current);
    }
    current = null;
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!.trim();
    if (!line) continue;
    if (/^WEBVTT/i.test(line) || /^(NOTE|STYLE|Kind:|Language:)/.test(line)) continue;

    // SRT index line ("12") immediately followed by a timing line.
    if (/^\d+$/.test(line) && SRT_TIMING.test(lines[i + 1]?.trim() ?? "")) continue;

    const srt = SRT_TIMING.exec(line);
    if (srt) {
      push();
      const start = parseTimestamp(srt[1]!.replace(",", "."));
      if (start !== null) current = { start, text: "" };
      continue;
    }

    const lead = LEADING_TS.exec(line);
    if (lead) {
      const start = parseTimestamp(lead[1]!);
      if (start !== null) {
        push();
        current = { start, text: stripTags(lead[2] ?? "") };
        continue;
      }
    }

    if (current) {
      const c: Cue = current;
      c.text = c.text ? `${c.text} ${stripTags(line)}` : stripTags(line);
    }
    // Text before the first timestamp is ignored (usually a title).
  }
  push();

  if (cues.length === 0) {
    throw new TranscriptParseError(
      "No timestamps found. Each section needs a time like 0:32 or 01:02:11 at the start of a line.",
    );
  }

  // Keep chronological order; drop exact duplicates.
  cues.sort((a, b) => a.start - b.start);
  return cues.filter((c, i) => i === 0 || c.start !== cues[i - 1]!.start || c.text !== cues[i - 1]!.text);
}

function stripTags(s: string): string {
  return s.replace(/<[^>]+>/g, "").replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").trim();
}

/** Rough speaking-time estimate for the final cue, which has no following timestamp. */
export function estimateSpokenSeconds(text: string): number {
  const words = text.split(/\s+/).filter(Boolean).length;
  return Math.max(3, Math.round(words / 2.5));
}

export interface TimedCue extends Cue {
  end: number;
}

/** Give every cue an end time: the next cue's start, or an estimate for the last one. */
export function withEndTimes(cues: Cue[], videoDurationSeconds?: number | null): TimedCue[] {
  return cues.map((c, i) => {
    const next = cues[i + 1];
    let end = next ? next.start : c.start + estimateSpokenSeconds(c.text);
    if (!next && videoDurationSeconds && videoDurationSeconds > c.start) {
      // If the video length is known, a last "chapter" line extends to the end of the video
      // but only when that isn't implausibly long for a single line of speech.
      const tail = videoDurationSeconds - c.start;
      end = c.text.split(/\s+/).length <= 12 ? c.start + Math.min(tail, 300) : Math.min(end, videoDurationSeconds);
    }
    if (videoDurationSeconds && videoDurationSeconds > c.start) end = Math.min(end, videoDurationSeconds);
    return { ...c, end: Math.max(end, c.start + 1) };
  });
}
