import { describe, expect, it } from "vitest";
import { openDatabase, resetDatabase } from "@/lib/db/client";
import { SEED_CLIPS, SEED_VIDEOS } from "@/lib/db/seed-data";
import { createClip, deleteClip, getClipView, listClipViews, listSavedClipViews, updateClip } from "@/lib/repo/clips";
import { InputError, upsertYouTubeSource } from "@/lib/repo/sources";
import { listInteractions, logInteraction, logInteractions, setSaved } from "@/lib/repo/interactions";
import { getSettings, updateSettings } from "@/lib/repo/settings";
import { getDeeperClips, getFeed, getNextClip, getProfileSummary } from "@/lib/recommend/service";
import { validateClipDraft } from "@/lib/domain/validation";

const fresh = () => openDatabase(":memory:");

function valid(input: Parameters<typeof validateClipDraft>[0]) {
  const r = validateClipDraft(input);
  if (!r.ok) throw new Error(JSON.stringify(r.errors));
  return r.value;
}

describe("database", () => {
  it("migrates and seeds demo data on first open", () => {
    const db = fresh();
    expect(listClipViews(db)).toHaveLength(SEED_CLIPS.length);
    const sources = db.prepare("SELECT COUNT(*) AS n FROM source_videos").get() as { n: number };
    expect(sources.n).toBe(SEED_VIDEOS.length);
    expect(SEED_CLIPS.length).toBeGreaterThanOrEqual(10);
    expect(SEED_CLIPS.length).toBeLessThanOrEqual(20);
  });

  it("seed relationships point at real clips", () => {
    const ids = new Set(SEED_CLIPS.map((c) => c.id));
    for (const c of SEED_CLIPS) for (const r of c.related) expect(ids.has(r), `${c.id} → ${r}`).toBe(true);
  });

  it("creates sources idempotently by YouTube ID", () => {
    const db = fresh();
    const a = upsertYouTubeSource(db, { url: "https://youtu.be/abcdefghijk", title: "T" });
    const b = upsertYouTubeSource(db, { url: "https://www.youtube.com/watch?v=abcdefghijk", channel: "Chan" });
    expect(a.id).toBe(b.id);
    expect(b.channel).toBe("Chan");
    expect(() => upsertYouTubeSource(db, { url: "https://example.com/video" })).toThrow(InputError);
  });

  it("creates, updates and deletes clips; rejects clips past the video end", () => {
    const db = fresh();
    const src = upsertYouTubeSource(db, { url: "https://youtu.be/abcdefghijk", title: "T", durationSeconds: 600 });
    const c = createClip(db, src.id, valid({ title: "A", topic: "physics", start: "0:10", end: "1:10", tags: "x,y" }));
    expect(c.durationSeconds).toBe(60);
    expect(c.topic).toBe("Physics");
    expect(() => createClip(db, src.id, valid({ title: "B", start: "9:00", end: "11:00" }))).toThrow(/past the end/);
    const u = updateClip(db, c.id, valid({ title: "A2", start: "0:20", end: "1:00" }))!;
    expect(u.title).toBe("A2");
    expect(u.durationSeconds).toBe(40);
    expect(deleteClip(db, c.id)).toBe(true);
    expect(getClipView(db, c.id)).toBeNull();
  });

  it("enforces end > start at the database level too", () => {
    const db = fresh();
    expect(() =>
      db
        .prepare(
          "INSERT INTO knowledge_clips (id, source_video_id, title, start_seconds, end_seconds, duration_seconds, created_at, updated_at) VALUES ('x', 'seed-video-dalio', 't', 10, 5, -5, 'now', 'now')",
        )
        .run(),
    ).toThrow();
  });

  it("saves clips and logs interactions", () => {
    const db = fresh();
    setSaved(db, "seed-nn-edges", true);
    setSaved(db, "seed-nn-edges", true);
    expect(listSavedClipViews(db).map((c) => c.id)).toEqual(["seed-nn-edges"]);
    expect(getClipView(db, "seed-nn-edges")!.saved).toBe(true);
    setSaved(db, "seed-nn-edges", false);
    expect(listSavedClipViews(db)).toHaveLength(0);

    expect(logInteractions(db, [
      { clipId: "seed-nn-edges", action: "impression" },
      { clipId: "does-not-exist", action: "impression" },
    ])).toBe(1);
  });

  it("feed reacts to More Like This end-to-end", () => {
    const db = fresh();
    const rankOf = (id: string) => getFeed(db, { seed: 5 }).findIndex((c) => c.id === id);
    const topicRank = (topic: string) => {
      const feed = getFeed(db, { seed: 5 });
      return feed.findIndex((c) => c.topic === topic);
    };
    const before = topicRank("Philosophy");
    logInteraction(db, { clipId: "seed-nihilism-dread", action: "more_like_this" });
    logInteraction(db, { clipId: "seed-nihilism-dread", action: "completed", completionRatio: 1 });
    expect(rankOf("seed-nihilism-freedom")).toBeLessThanOrEqual(1);
    expect(topicRank("Philosophy")).toBeLessThanOrEqual(before);
    const summary = getProfileSummary(db);
    expect(summary.topics[0]!.topic).toBe("Philosophy");
    expect(summary.topics[0]!.trend).toMatch(/up/);
  });

  it("preference reset ignores older interactions", () => {
    const db = fresh();
    logInteraction(db, { clipId: "seed-nihilism-dread", action: "more_like_this", at: "2020-01-01T00:00:00.000Z" });
    expect(getProfileSummary(db).topics[0]!.topic).toBe("Philosophy");
    updateSettings(db, { preferencesResetAt: "2021-01-01T00:00:00.000Z" });
    expect(getProfileSummary(db).topics.every((t) => t.affinity === 0)).toBe(true);
    expect(listInteractions(db)).toHaveLength(1);
  });

  it("next and deeper return sensible clips", () => {
    const db = fresh();
    const next = getNextClip(db, "seed-rome-debasement", ["seed-dalio-credit"]);
    expect(next).not.toBeNull();
    expect(next!.id).not.toBe("seed-rome-debasement");
    const deeper = getDeeperClips(db, "seed-rome-debasement");
    expect(deeper[0]!.id).toBe("seed-rome-inflation");
    const deeper2 = getDeeperClips(db, "seed-rome-debasement", ["seed-rome-inflation"]);
    expect(deeper2[0]!.id).not.toBe("seed-rome-inflation");
  });

  it("settings round-trip with clamping", () => {
    const db = fresh();
    expect(getSettings(db).explorationRate).toBe(0.25);
    expect(updateSettings(db, { explorationRate: 0.9 }).explorationRate).toBe(0.5);
    expect(updateSettings(db, { autoplayOnWatch: false }).autoplayOnWatch).toBe(false);
  });

  it("reset restores the demo database", () => {
    const db = fresh();
    setSaved(db, "seed-nn-edges", true);
    deleteClip(db, "seed-nn-matrix");
    resetDatabase(db);
    expect(listClipViews(db)).toHaveLength(SEED_CLIPS.length);
    expect(listSavedClipViews(db)).toHaveLength(0);
  });
});
