/**
 * Heuristic transcript segmentation.
 *
 * Every gap between two cues gets a "boundary strength" from several signals:
 *   + heading-like cue (short, no sentence punctuation)       strong
 *   + discourse markers ("Now,", "Next", "Let's", "Finally")   medium
 *   + lexical shift (TextTiling-style depth of cosine dip)     medium
 *   + unusually long pause relative to the words spoken        weak
 *   − previous cue ends mid-sentence                           penalty
 * Then dynamic programming picks the set of boundaries that maximises total strength,
 * subject to min/max clip length and a mild preference for ~2-minute clips. A fixed
 * per-clip cost stops weak boundaries from fragmenting the transcript.
 *
 * The segmentation strategy is a plain function, so an AI-based segmenter can replace it
 * later without touching the rest of the pipeline.
 */
import type { TimedCue } from "./transcript";
import { cosine, termFreq, tokenize, wordCount } from "./text";
import { estimateSpokenSeconds } from "./transcript";

export interface SegmentOptions {
  minSeconds: number;
  targetSeconds: number;
  maxSeconds: number;
}

export const DEFAULT_SEGMENT_OPTIONS: SegmentOptions = { minSeconds: 30, targetSeconds: 120, maxSeconds: 300 };

export interface Segment {
  start: number;
  end: number;
  cues: TimedCue[];
  /** Heading text if the segment opens on a heading-like cue. */
  heading: string | null;
  /** Strength of the boundary that opened this segment (0 for the first). */
  boundaryStrength: number;
}

const STRONG_MARKERS =
  /^(now|next|so now|moving on|let's (talk|look|move|turn|start|begin|go)|another|finally|in the end|first(ly)?|second(ly)?|third(ly)?|the (first|second|third|next|last|final) (thing|reason|point|step|problem|question|part)|chapter|part \w+|step \w+|but here's|here's the|which brings us|that brings us|to understand|the question is|ok(ay)?,? so)\b/i;
const WEAK_MARKERS = /^(so|but|however|meanwhile|then|and so|in fact|instead)\b/i;

export function isHeadingCue(text: string): boolean {
  const t = text.trim();
  if (!t) return false;
  const words = wordCount(t);
  if (/^(chapter|part|section)\s+\w+/i.test(t) && words <= 12) return true;
  if (words > 9) return false;
  if (/[.!?,;]$/.test(t)) return false;
  // A short fragment is a heading when it's capitalised like a title or all caps.
  return /^[A-Z0-9"“]/.test(t) || t === t.toUpperCase();
}

function endsSentence(text: string): boolean {
  return /[.!?]["'”)]?$/.test(text.trim());
}

export function boundaryStrengths(cues: TimedCue[]): number[] {
  const n = cues.length;
  const tf = cues.map((c) => termFreq(tokenize(c.text)));
  const window = 3;

  const blockSim: number[] = new Array(n).fill(0);
  for (let i = 1; i < n; i++) {
    const left = new Map<string, number>();
    const right = new Map<string, number>();
    for (let k = Math.max(0, i - window); k < i; k++) for (const [w, c] of tf[k]!) left.set(w, (left.get(w) ?? 0) + c);
    for (let k = i; k < Math.min(n, i + window); k++) for (const [w, c] of tf[k]!) right.set(w, (right.get(w) ?? 0) + c);
    blockSim[i] = cosine(left, right);
  }

  const strengths: number[] = new Array(n).fill(0);
  for (let i = 1; i < n; i++) {
    const prev = cues[i - 1]!;
    const cur = cues[i]!;
    let s = 0;
    const heading = isHeadingCue(cur.text);
    if (heading) s += 2.5;
    if (STRONG_MARKERS.test(cur.text)) s += 0.8;
    else if (WEAK_MARKERS.test(cur.text)) s += 0.2;

    // Lexical depth: how far similarity dips here relative to nearby peaks.
    const lo = Math.max(1, i - 2);
    const hi = Math.min(n - 1, i + 2);
    let leftPeak = blockSim[i]!;
    let rightPeak = blockSim[i]!;
    for (let k = lo; k <= i; k++) leftPeak = Math.max(leftPeak, blockSim[k]!);
    for (let k = i; k <= hi; k++) rightPeak = Math.max(rightPeak, blockSim[k]!);
    s += 1.0 * (leftPeak - blockSim[i]! + (rightPeak - blockSim[i]!));
    s += 0.4 * (1 - blockSim[i]!);

    // Long silence relative to the words spoken in the previous cue.
    const spoken = estimateSpokenSeconds(prev.text);
    if (cur.start - prev.start - spoken > 6 && !isHeadingCue(prev.text)) s += 0.5;

    if (!heading) s += endsSentence(prev.text) ? 0.3 : -0.6;
    strengths[i] = s;
  }
  return strengths;
}

const SEGMENT_COST = 1.4;

function lengthScore(duration: number, opts: SegmentOptions): number {
  const x = (duration - opts.targetSeconds) / opts.targetSeconds;
  return -0.5 * x * x;
}

export function segmentTranscript(cues: TimedCue[], options: Partial<SegmentOptions> = {}): Segment[] {
  const opts = { ...DEFAULT_SEGMENT_OPTIONS, ...options };
  const n = cues.length;
  if (n === 0) return [];
  const strengths = boundaryStrengths(cues);
  const dur = (i: number, j: number) => cues[j - 1]!.end - cues[i]!.start;
  const total = dur(0, n);

  // A transcript shorter than the minimum becomes a single clip.
  if (total < opts.minSeconds) return [makeSegment(cues, 0, n, 0)];

  const best: number[] = new Array(n + 1).fill(-Infinity);
  const prev: number[] = new Array(n + 1).fill(-1);
  best[0] = 0;
  for (let j = 1; j <= n; j++) {
    for (let i = j - 1; i >= 0; i--) {
      if (best[i] === -Infinity) continue;
      const d = dur(i, j);
      const single = j - i === 1; // a single long cue can't be split further
      const tooShort = d < opts.minSeconds && !(j === n && i > 0 && d >= opts.minSeconds / 2);
      if (tooShort && !(single && j === n && i === 0)) continue;
      if (d > opts.maxSeconds && !single) break; // durations only grow as i decreases
      const v = best[i]! + (i > 0 ? strengths[i]! : 0) + lengthScore(d, opts) - SEGMENT_COST;
      if (v > best[j]!) {
        best[j] = v;
        prev[j] = i;
      }
    }
  }

  if (best[n] === -Infinity) return greedyFallback(cues, strengths, opts);

  const bounds: number[] = [];
  for (let j = n; j > 0; j = prev[j]!) bounds.unshift(j);
  const segments: Segment[] = [];
  let i = 0;
  for (const j of bounds) {
    segments.push(makeSegment(cues, i, j, i > 0 ? strengths[i]! : 0));
    i = j;
  }
  return segments;
}

function makeSegment(cues: TimedCue[], i: number, j: number, strength: number): Segment {
  const slice = cues.slice(i, j);
  const first = slice[0]!;
  return {
    start: first.start,
    end: slice[slice.length - 1]!.end,
    cues: slice,
    heading: isHeadingCue(first.text) ? first.text.trim() : null,
    boundaryStrength: strength,
  };
}

/** Used only if constraints are unsatisfiable: accumulate cues up to the target length. */
function greedyFallback(cues: TimedCue[], strengths: number[], opts: SegmentOptions): Segment[] {
  const out: Segment[] = [];
  let i = 0;
  for (let j = 1; j <= cues.length; j++) {
    const d = cues[j - 1]!.end - cues[i]!.start;
    if (j === cues.length || (d >= opts.minSeconds && (d >= opts.targetSeconds || strengths[j]! > 2))) {
      out.push(makeSegment(cues, i, j, i > 0 ? strengths[i]! : 0));
      i = j;
    }
  }
  return out;
}
