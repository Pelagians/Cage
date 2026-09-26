import { describe, expect, it } from "vitest";
import { buildFeed, buildProfile, relatedClips, scoreClip, trendOf, type ClipLike } from "@/lib/recommend/engine";
import type { InteractionAction, UserInteraction } from "@/lib/types";

const NOW = Date.parse("2026-09-01T12:00:00Z");

const clip = (id: string, topic: string, tags: string[], quality = 0.7, related: string[] = []): ClipLike => ({
  id,
  topic,
  tags,
  qualityScore: quality,
  relatedClipIds: related,
});

const CLIPS: ClipLike[] = [
  clip("rome-1", "Ancient Rome", ["rome", "money", "inflation"]),
  clip("rome-2", "Ancient Rome", ["rome", "army"]),
  clip("rome-3", "Ancient Rome", ["rome", "emperors"]),
  clip("econ-1", "Economics", ["money", "credit", "inflation"]),
  clip("econ-2", "Economics", ["debt", "credit"]),
  clip("phys-1", "Physics", ["entropy", "energy"], 0.8),
  clip("phys-2", "Physics", ["relativity", "time"], 0.8),
  clip("phil-1", "Philosophy", ["meaning", "ethics"], 0.8),
  clip("bio-1", "Biology", ["cells", "evolution"], 0.8),
  clip("ml-1", "Machine Learning", ["neural networks"], 0.8),
];
const byId = new Map(CLIPS.map((c) => [c.id, c]));

let nextId = 1;
function ev(clipId: string, action: InteractionAction, minutesAgo = 5, completionRatio: number | null = null): UserInteraction {
  return {
    id: nextId++,
    clipId,
    action,
    watchSeconds: null,
    completionRatio,
    createdAt: new Date(NOW - minutesAgo * 60_000).toISOString(),
  };
}

const score = (id: string, interactions: UserInteraction[]) =>
  scoreClip(byId.get(id)!, buildProfile(CLIPS, interactions, NOW), { byId, now: NOW }).total;

describe("preference profile", () => {
  it("More Like This raises topic and tag affinity", () => {
    const before = buildProfile(CLIPS, [], NOW);
    const after = buildProfile(CLIPS, [ev("rome-1", "more_like_this")], NOW);
    expect(before.topicAffinity.get("ancient rome") ?? 0).toBe(0);
    expect(after.topicAffinity.get("ancient rome")!).toBeGreaterThan(0.5);
    expect(after.tagAffinity.get("money")!).toBeGreaterThan(0);
    expect(after.tagAffinity.get("inflation")!).toBeGreaterThan(0);
  });

  it("More Like This raises the score of related, unseen clips", () => {
    const base = score("rome-2", []);
    const boosted = score("rome-2", [ev("rome-1", "more_like_this")]);
    expect(boosted).toBeGreaterThan(base + 0.5);
    // A clip sharing only a tag (econ-1: money, inflation) also rises.
    expect(score("econ-1", [ev("rome-1", "more_like_this")])).toBeGreaterThan(score("econ-1", []));
    // Unrelated topics are untouched.
    expect(score("phys-2", [ev("rome-1", "more_like_this")])).toBeCloseTo(score("phys-2", []), 5);
  });

  it("Less Like This lowers topic affinity and scores", () => {
    const p = buildProfile(CLIPS, [ev("phys-1", "less_like_this")], NOW);
    expect(p.topicAffinity.get("physics")!).toBeLessThan(-0.5);
    expect(score("phys-2", [ev("phys-1", "less_like_this")])).toBeLessThan(score("phys-2", []) - 0.5);
  });

  it("repeated skips lower affinity; repeated completions raise it", () => {
    const skips = [ev("bio-1", "skipped"), ev("bio-1", "skipped", 10), ev("bio-1", "skipped", 20)];
    expect(buildProfile(CLIPS, skips, NOW).topicAffinity.get("biology")!).toBeLessThan(0);
    const done = [ev("econ-1", "completed", 5, 1), ev("econ-2", "completed", 10, 1)];
    expect(buildProfile(CLIPS, done, NOW).topicAffinity.get("economics")!).toBeGreaterThan(0.5);
  });

  it("old interactions decay", () => {
    const fresh = buildProfile(CLIPS, [ev("rome-1", "more_like_this", 1)], NOW).topicAffinity.get("ancient rome")!;
    const stale = buildProfile(CLIPS, [ev("rome-1", "more_like_this", 60 * 24 * 60)], NOW).topicAffinity.get("ancient rome")!;
    expect(stale).toBeLessThan(fresh / 2);
  });

  it("affinities are bounded", () => {
    const spam = Array.from({ length: 200 }, (_, i) => ev("rome-1", "more_like_this", i));
    const a = buildProfile(CLIPS, spam, NOW).topicAffinity.get("ancient rome")!;
    expect(a).toBeLessThanOrEqual(1);
    expect(trendOf(a)).toBe("strong-up");
  });
});

describe("penalties", () => {
  it("already watched material is penalized", () => {
    const fresh = score("phil-1", []);
    const opened = score("phil-1", [ev("phil-1", "opened", 1)]);
    const completed = score("phil-1", [ev("phil-1", "completed", 1, 1)]);
    // Completing still adds a small positive topic signal but the watched penalty dominates.
    expect(completed).toBeLessThan(fresh - 0.5);
    expect(opened).toBeLessThan(fresh);
  });

  it("repeated impressions reduce the score", () => {
    const shown = [ev("ml-1", "impression", 1), ev("ml-1", "impression", 2), ev("ml-1", "impression", 3)];
    expect(score("ml-1", shown)).toBeLessThan(score("ml-1", []) - 0.4);
  });

  it("Less Like This on a specific clip buries it", () => {
    const s = score("ml-1", [ev("ml-1", "less_like_this")]);
    expect(s).toBeLessThan(0);
  });
});

describe("feed", () => {
  const romeFan = [
    ev("rome-1", "more_like_this", 1),
    ev("rome-1", "completed", 2, 1),
    ev("econ-1", "more_like_this", 3),
    ev("econ-1", "completed", 4, 1),
  ];

  it("is deterministic for a given seed and contains every clip once", () => {
    const profile = buildProfile(CLIPS, [], NOW);
    const a = buildFeed(CLIPS, profile, { explorationRate: 0.25, seed: 42, now: NOW });
    const b = buildFeed(CLIPS, profile, { explorationRate: 0.25, seed: 42, now: NOW });
    expect(a).toEqual(b);
    expect(new Set(a.map((e) => e.clipId)).size).toBe(CLIPS.length);
  });

  it("ranks preferred topics higher after interactions", () => {
    const profile = buildProfile(CLIPS, romeFan, NOW);
    const feed = buildFeed(CLIPS, profile, { explorationRate: 0, seed: 7, now: NOW });
    const top3 = feed.slice(0, 3).map((e) => e.clipId);
    expect(top3.filter((id) => id.startsWith("rome") || id.startsWith("econ")).length).toBeGreaterThanOrEqual(2);
    // Completed clips are not at the top.
    expect(top3).not.toContain("rome-1");
    expect(top3).not.toContain("econ-1");
  });

  it("exploration still surfaces unrelated content near the top", () => {
    const heavy = [...romeFan, ...Array.from({ length: 20 }, (_, i) => ev(i % 2 ? "rome-2" : "econ-2", "more_like_this", 10 + i))];
    const profile = buildProfile(CLIPS, heavy, NOW);
    for (const seed of [1, 2, 3, 4, 5]) {
      const feed = buildFeed(CLIPS, profile, { explorationRate: 0.25, seed, now: NOW });
      const first4 = feed.slice(0, 4);
      const unrelated = first4.filter((e) => !/^(rome|econ)/.test(e.clipId));
      expect(unrelated.length).toBeGreaterThanOrEqual(1);
      expect(first4.some((e) => e.slot === "explore")).toBe(true);
    }
  });

  it("with exploration at 0 the feed is purely preference-ranked", () => {
    const profile = buildProfile(CLIPS, romeFan, NOW);
    const feed = buildFeed(CLIPS, profile, { explorationRate: 0, seed: 3, now: NOW });
    expect(feed.every((e) => e.slot === "personal")).toBe(true);
  });

  it("breaks up long runs of one topic", () => {
    const profile = buildProfile(CLIPS, [ev("rome-1", "more_like_this", 1)], NOW);
    const feed = buildFeed(CLIPS, profile, { explorationRate: 0, seed: 9, now: NOW });
    const topics = feed.map((e) => byId.get(e.clipId)!.topic);
    for (let i = 2; i < topics.length; i++) {
      const run = topics[i] === topics[i - 1] && topics[i] === topics[i - 2];
      if (run) expect(new Set(topics.slice(i)).size).toBe(1); // only allowed when nothing else is left
    }
  });

  it("respects excludes and limits", () => {
    const profile = buildProfile(CLIPS, [], NOW);
    const feed = buildFeed(CLIPS, profile, { explorationRate: 0.25, seed: 1, excludeIds: ["rome-1"], limit: 4, now: NOW });
    expect(feed).toHaveLength(4);
    expect(feed.map((e) => e.clipId)).not.toContain("rome-1");
  });
});

describe("relatedClips (Go Deeper)", () => {
  it("prefers explicit relationships, then shared tags", () => {
    const withLinks = CLIPS.map((c) => (c.id === "rome-1" ? { ...c, relatedClipIds: ["phil-1"] } : c));
    const rel = relatedClips(withLinks.find((c) => c.id === "rome-1")!, withLinks);
    expect(rel[0]!.id).toBe("phil-1");
    expect(rel.map((c) => c.id)).toContain("econ-1");
    expect(rel.map((c) => c.id)).not.toContain("rome-1");
  });
});
