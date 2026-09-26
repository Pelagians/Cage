import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { parseTranscript, TranscriptParseError, withEndTimes } from "@/lib/ingest/transcript";
import { segmentTranscript } from "@/lib/ingest/segment";
import { proposeClips } from "@/lib/ingest/pipeline";
import type { LlmClient } from "@/lib/ingest/providers/llm";

const fixture = fs.readFileSync(path.join(__dirname, "../fixtures/rome-transcript.txt"), "utf8");

describe("parseTranscript", () => {
  it("parses timestamp-first lines", () => {
    const cues = parseTranscript("00:00 Introduction\n00:32 The Roman monetary system\n01:14 Debasement accelerated when\n02:41 Military expenses");
    expect(cues.map((c) => c.start)).toEqual([0, 32, 74, 161]);
    expect(cues[1]!.text).toBe("The Roman monetary system");
  });

  it("handles brackets, dashes and hours", () => {
    const cues = parseTranscript("[0:05] one\n(1:02:11) two\n3:00 - three\n4:00 | four");
    expect(cues.map((c) => [c.start, c.text])).toEqual([
      [5, "one"],
      [180, "three"],
      [240, "four"],
      [3731, "two"],
    ]);
  });

  it("handles YouTube's timestamp-on-its-own-line format", () => {
    const cues = parseTranscript("0:00\nhello there\n0:04\ngeneral\nkenobi\n0:09\nend");
    expect(cues).toEqual([
      { start: 0, text: "hello there" },
      { start: 4, text: "general kenobi" },
      { start: 9, text: "end" },
    ]);
  });

  it("handles SRT and WebVTT", () => {
    const srt = "1\n00:00:01,000 --> 00:00:04,000\nFirst line\n\n2\n00:00:05,500 --> 00:00:08,000\nSecond <i>line</i>\n";
    expect(parseTranscript(srt)).toEqual([
      { start: 1, text: "First line" },
      { start: 5.5, text: "Second line" },
    ]);
    const vtt = "WEBVTT\n\n00:00:02.000 --> 00:00:04.000\nHi\n\n00:01:02.000 --> 00:01:04.000\nThere";
    expect(parseTranscript(vtt).map((c) => c.start)).toEqual([2, 62]);
  });

  it("throws understandable errors", () => {
    expect(() => parseTranscript("")).toThrow(TranscriptParseError);
    expect(() => parseTranscript("just some words\nwith no times")).toThrow(/No timestamps/);
  });

  it("gives every cue an end time", () => {
    const timed = withEndTimes(parseTranscript("0:00 a b c\n0:10 d e f g h i j k l m n o"));
    expect(timed[0]!.end).toBe(10);
    expect(timed[1]!.end).toBeGreaterThan(10);
  });
});

describe("segmentTranscript", () => {
  const cues = withEndTimes(parseTranscript(fixture));
  const segments = segmentTranscript(cues);

  it("produces several segments covering the transcript in order", () => {
    expect(segments.length).toBeGreaterThanOrEqual(3);
    expect(segments.length).toBeLessThanOrEqual(8);
    expect(segments[0]!.start).toBe(0);
    expect(segments.at(-1)!.end).toBe(cues.at(-1)!.end);
    for (let i = 1; i < segments.length; i++) {
      expect(segments[i]!.start).toBe(segments[i - 1]!.end);
    }
  });

  it("respects min/max lengths", () => {
    for (const s of segments.slice(0, -1)) {
      expect(s.end - s.start).toBeGreaterThanOrEqual(30);
      expect(s.end - s.start).toBeLessThanOrEqual(300);
    }
    for (const s of segments) expect(s.end).toBeGreaterThan(s.start);
  });

  it("keeps a coherent section together", () => {
    const army = segments.find((s) => s.start === 240)!;
    expect(army.end).toBe(348);
  });

  it("splits at the section headings rather than fixed intervals", () => {
    const starts = segments.map((s) => s.start);
    // Heading lines: 0:38, 2:15, 4:00, 5:48, 7:24
    for (const heading of [38, 135, 240, 348, 444]) expect(starts).toContain(heading);
    expect(segments.filter((s) => s.heading).length).toBeGreaterThanOrEqual(4);
  });

  it("does not create tiny fragments without headings", () => {
    const plain = withEndTimes(
      parseTranscript(
        Array.from({ length: 60 }, (_, i) => `${Math.floor((i * 8) / 60)}:${String((i * 8) % 60).padStart(2, "0")} The economy keeps growing because credit expands and spending rises across markets.`).join("\n"),
      ),
    );
    const segs = segmentTranscript(plain);
    for (const s of segs.slice(0, -1)) expect(s.end - s.start).toBeGreaterThanOrEqual(30);
    expect(segs.length).toBeLessThan(10);
  });

  it("allows custom lengths", () => {
    const segs = segmentTranscript(cues, { minSeconds: 60, maxSeconds: 200, targetSeconds: 120 });
    for (const s of segs.slice(0, -1)) {
      expect(s.end - s.start).toBeGreaterThanOrEqual(60);
      expect(s.end - s.start).toBeLessThanOrEqual(200);
    }
  });
});

describe("proposeClips", () => {
  it("creates enriched candidates with valid boundaries", async () => {
    const proposal = await proposeClips({ transcript: fixture, videoTitle: "How inflation ruined Rome" }, { llm: null });
    expect(proposal.candidates.length).toBeGreaterThanOrEqual(3);
    for (const c of proposal.candidates) {
      expect(c.title.length).toBeGreaterThan(0);
      expect(c.endSeconds).toBeGreaterThan(c.startSeconds);
      expect(c.topic).toBeTruthy();
      expect(c.qualityScore).toBeGreaterThan(0);
      expect(c.qualityScore).toBeLessThanOrEqual(1);
    }
    const debasement = proposal.candidates.find((c) => c.startSeconds === 135)!;
    expect(debasement.title).toBe("Debasement");
    expect(debasement.hook.length).toBeGreaterThan(10);
    expect(debasement.topic).toMatch(/Rome|Economics/);
    expect(proposal.candidates.some((c) => c.title === "Diocletian's Response")).toBe(true);
    expect(proposal.enrichment).toMatch(/Heuristic/);
  });

  it("trims a trailing outro line instead of discarding the clip", async () => {
    const proposal = await proposeClips({ transcript: fixture }, { llm: null });
    const last = proposal.candidates.at(-1)!;
    expect(last.endSeconds).toBe(8 * 60 + 16);
    expect(last.lowValue).toBe(false);
  });

  it("flags sponsor segments as low value", async () => {
    const sponsor = [
      "0:00 This video is sponsored by Brilliant.",
      "0:12 Brilliant.org has interactive courses in math and science, sponsor of this channel.",
      "0:25 Go to brilliant.org to get started, the link in the description gives you a discount.",
      "0:38 Thanks to our sponsor for supporting the channel and please subscribe.",
      "0:50 Now back to the video.",
    ].join("\n");
    const proposal = await proposeClips({ transcript: sponsor }, { llm: null });
    expect(proposal.candidates.some((c) => c.lowValue)).toBe(true);
  });

  it("uses an AI provider when available and falls back per clip on failure", async () => {
    let calls = 0;
    const fake: LlmClient = {
      label: "Fake",
      ping: async () => true,
      completeJson: async () => {
        calls++;
        if (calls === 2) throw new Error("boom");
        return { title: "AI title", hook: "AI hook", summary: "AI summary", topic: "Economic History", tags: ["Money"] };
      },
    };
    const proposal = await proposeClips({ transcript: fixture }, { llm: fake });
    expect(proposal.candidates[0]!.title).toBe("AI title");
    expect(proposal.candidates[0]!.tags).toEqual(["money"]);
    expect(proposal.candidates[1]!.enrichedBy).toBe("heuristic");
    expect(proposal.warnings.join(" ")).toMatch(/failed for 1/);
  });

  it("falls back to heuristics when the AI provider is unreachable", async () => {
    const down: LlmClient = { label: "Down", ping: async () => false, completeJson: async () => ({}) };
    const proposal = await proposeClips({ transcript: fixture }, { llm: down });
    expect(proposal.candidates.every((c) => c.enrichedBy === "heuristic")).toBe(true);
    expect(proposal.warnings.join(" ")).toMatch(/isn't reachable/);
  });

  it("ignores lines past the known video duration", async () => {
    const proposal = await proposeClips({ transcript: fixture, videoDurationSeconds: 300 }, { llm: null });
    expect(proposal.candidates.at(-1)!.endSeconds).toBeLessThanOrEqual(300);
    expect(proposal.warnings.join(" ")).toMatch(/after the video's end/);
  });
});
