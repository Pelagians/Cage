/**
 * Ingest pipeline:  transcript text → cues → segments → enrichment → clip candidates.
 *
 * Nothing is written to the database here; candidates go to the review screen first.
 * Stages are plain functions so each can be swapped (e.g. automatic transcript
 * retrieval, Whisper transcription or an AI segmenter) without touching the others.
 */
import type { AiSettings } from "../types";
import { parseTranscript, TranscriptParseError, withEndTimes } from "./transcript";
import { segmentTranscript, type Segment, type SegmentOptions } from "./segment";
import { classifyTopic, enrichSegmentHeuristically, LOW_VALUE, makeIdf, type Enrichment } from "./enrich";
import { tokenize, truncateAtWord } from "./text";
import { createLlmClient, type LlmClient } from "./providers/llm";
import { normalizeTags } from "../domain/validation";

/** Upper bound on total AI time per ingest so a slow model can't hang the request. */
const AI_BUDGET_MS = 120_000;

export interface ClipCandidate extends Enrichment {
  candidateId: string;
  startSeconds: number;
  endSeconds: number;
  enrichedBy: "heuristic" | "ai";
}

export interface IngestProposal {
  candidates: ClipCandidate[];
  cueCount: number;
  warnings: string[];
  enrichment: string;
}

export interface ProposeInput {
  transcript: string;
  videoTitle?: string;
  videoDurationSeconds?: number | null;
}

export async function proposeClips(
  input: ProposeInput,
  opts: { ai?: AiSettings | null; llm?: LlmClient | null; segment?: Partial<SegmentOptions> } = {},
): Promise<IngestProposal> {
  const warnings: string[] = [];
  const parsed = parseTranscript(input.transcript);
  const duration = input.videoDurationSeconds && input.videoDurationSeconds > 0 ? input.videoDurationSeconds : null;
  const inRange = duration ? parsed.filter((c) => c.start < duration) : parsed;
  if (duration && inRange.length < parsed.length) {
    warnings.push(`${parsed.length - inRange.length} transcript line(s) start after the video's end and were ignored.`);
  }
  if (inRange.length === 0) throw new TranscriptParseError("No transcript lines fall inside the video's duration.");
  const usable = withEndTimes(inRange, duration);

  const segments = segmentTranscript(usable, opts.segment).map(trimPromoEdges);
  const segTokens = segments.map((s) => tokenize(s.cues.map((c) => c.text).join(" ")));
  const idf = makeIdf(segTokens);
  const videoTopic = classifyTopic(tokenize(`${input.videoTitle ?? ""} ${usable.map((c) => c.text).join(" ")}`));

  const candidates: ClipCandidate[] = segments.map((seg, i) => ({
    candidateId: `c${i + 1}`,
    startSeconds: Math.round(seg.start * 10) / 10,
    endSeconds: Math.round(seg.end * 10) / 10,
    enrichedBy: "heuristic",
    ...enrichSegmentHeuristically(seg, { idf, videoTopic }),
  }));

  if (usable.length < 3) warnings.push("Very few timestamps were found, so clip boundaries are coarse. Review them carefully.");

  let enrichment = "Heuristic (no AI)";
  const llm = opts.llm !== undefined ? opts.llm : createLlmClient(opts.ai);
  if (llm) {
    if (await llm.ping()) {
      let improved = 0;
      const deadline = Date.now() + AI_BUDGET_MS;
      for (let i = 0; i < segments.length; i++) {
        if (Date.now() > deadline) {
          warnings.push("AI enrichment hit its time budget; remaining clips use heuristics.");
          break;
        }
        const better = await enrichWithLlm(llm, segments[i]!, input.videoTitle).catch(() => null);
        if (better) {
          Object.assign(candidates[i]!, better, { enrichedBy: "ai" as const });
          improved++;
        }
      }
      enrichment = improved ? `${llm.label}: improved ${improved}/${segments.length} clips` : `${llm.label} failed; used heuristics`;
      if (improved < segments.length) warnings.push(`AI enrichment failed for ${segments.length - improved} clip(s); heuristics used there.`);
    } else {
      warnings.push(`${llm.label} isn't reachable, so heuristic titles and summaries were used.`);
      enrichment = "Heuristic (AI unreachable)";
    }
  }

  return { candidates, cueCount: usable.length, warnings, enrichment };
}

async function enrichWithLlm(
  llm: LlmClient,
  seg: Segment,
  videoTitle?: string,
): Promise<Partial<Pick<Enrichment, "title" | "hook" | "summary" | "topic" | "tags">> | null> {
  const text = truncateAtWord(seg.cues.map((c) => c.text).join(" "), 6000);
  const prompt = `You are helping turn a section of an educational video into a short "knowledge clip" card.
Video: ${videoTitle || "unknown"}
Section transcript:
"""
${text}
"""
Return JSON with keys:
  "title": a specific, curiosity-provoking title (max 70 chars, no clickbait, no quotes),
  "hook": one or two sentences (max 200 chars) stating the core insight,
  "summary": 2-3 sentence factual summary (max 320 chars),
  "topic": a broad subject label of 1-3 words (e.g. "Economics", "Physics", "Ancient Rome"),
  "tags": 3-5 lowercase keyword tags.`;
  const raw = (await llm.completeJson(prompt)) as Record<string, unknown>;
  const s = (v: unknown, max: number) => (typeof v === "string" && v.trim() ? truncateAtWord(v.trim(), max) : undefined);
  const out = {
    title: s(raw.title, 90),
    hook: s(raw.hook, 240),
    summary: s(raw.summary, 400),
    topic: s(raw.topic, 40),
    tags: Array.isArray(raw.tags) ? normalizeTags(raw.tags).slice(0, 5) : undefined,
  };
  if (!out.title && !out.hook) return null;
  return Object.fromEntries(Object.entries(out).filter(([, v]) => v !== undefined));
}

/** Drop "subscribe / sponsor" lines at the very start or end of a segment. */
function trimPromoEdges(seg: Segment): Segment {
  const promo = seg.cues.filter((c) => LOW_VALUE.test(c.text)).length;
  if (promo / seg.cues.length >= 0.4) return seg; // mostly promo: keep it whole and flag it instead
  const cues = [...seg.cues];
  while (cues.length > 1 && LOW_VALUE.test(cues[cues.length - 1]!.text)) cues.pop();
  while (cues.length > 1 && LOW_VALUE.test(cues[0]!.text)) cues.shift();
  if (cues.length === seg.cues.length) return seg;
  return { ...seg, cues, start: cues[0]!.start, end: cues[cues.length - 1]!.end };
}
