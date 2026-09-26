/** Glue between the pure engine and the database. */
import type { DB } from "../db/client";
import type { ClipView } from "../types";
import { listClipViews } from "../repo/clips";
import { listInteractions, listSavedIds } from "../repo/interactions";
import { getSettings } from "../repo/settings";
import { buildFeed, buildProfile, relatedClips, tagKey, topicKey, trendOf, type Trend } from "./engine";

export interface FeedClip extends ClipView {
  slot: "personal" | "explore";
}

function loadProfile(db: DB) {
  const settings = getSettings(db);
  const clips = listClipViews(db);
  const interactions = listInteractions(db, { since: settings.preferencesResetAt });
  const profile = buildProfile(clips, interactions);
  return { settings, clips, profile };
}

export function getFeed(db: DB, opts: { seed?: number; excludeIds?: string[]; limit?: number } = {}): FeedClip[] {
  const { settings, clips, profile } = loadProfile(db);
  const byId = new Map(clips.map((c) => [c.id, c]));
  const savedIds = listSavedIds(db);
  const entries = buildFeed(clips, profile, {
    explorationRate: settings.explorationRate,
    seed: opts.seed ?? Math.floor(Math.random() * 2 ** 31),
    excludeIds: opts.excludeIds,
    limit: opts.limit ?? 50,
    savedIds,
  });
  return entries.map((e) => ({ ...byId.get(e.clipId)!, slot: e.slot }));
}

/** Best next clip after `currentId`, skipping anything already seen this session. */
export function getNextClip(db: DB, currentId: string, excludeIds: string[] = []): ClipView | null {
  const exclude = new Set([currentId, ...excludeIds]);
  const feed = getFeed(db, { excludeIds: [...exclude], limit: 1 });
  if (feed[0]) return feed[0];
  // Everything seen: fall back to anything but the current clip.
  return getFeed(db, { excludeIds: [currentId], limit: 1 })[0] ?? null;
}

export function getDeeperClips(db: DB, clipId: string, excludeIds: string[] = []): ClipView[] {
  const clips = listClipViews(db);
  const clip = clips.find((c) => c.id === clipId);
  if (!clip) return [];
  const exclude = new Set(excludeIds);
  const related = relatedClips(clip, clips, 10);
  const fresh = related.filter((c) => !exclude.has(c.id));
  return (fresh.length ? fresh : related) as ClipView[];
}

export interface TopicSummary {
  topic: string;
  clipCount: number;
  affinity: number;
  trend: Trend;
}

export interface ProfileSummary {
  topics: TopicSummary[];
  likedTags: string[];
  dislikedTags: string[];
  interactionCount: number;
  preferencesResetAt: string | null;
}

export function getProfileSummary(db: DB): ProfileSummary {
  const { settings, clips, profile } = loadProfile(db);
  const topics = new Map<string, TopicSummary>();
  for (const c of clips) {
    const k = topicKey(c.topic);
    const existing = topics.get(k);
    if (existing) existing.clipCount++;
    else {
      const affinity = profile.topicAffinity.get(k) ?? 0;
      topics.set(k, { topic: c.topic, clipCount: 1, affinity, trend: trendOf(affinity) });
    }
  }
  const tags = [...profile.tagAffinity].sort((a, b) => b[1] - a[1]);
  const clipTags = new Set(clips.flatMap((c) => c.tags.map(tagKey)));
  return {
    topics: [...topics.values()].sort((a, b) => b.affinity - a.affinity || b.clipCount - a.clipCount || a.topic.localeCompare(b.topic)),
    likedTags: tags.filter(([t, v]) => v > 0.15 && clipTags.has(t)).slice(0, 8).map(([t]) => t),
    dislikedTags: tags.filter(([t, v]) => v < -0.15 && clipTags.has(t)).reverse().slice(0, 8).map(([t]) => t),
    interactionCount: profile.interactionCount,
    preferencesResetAt: settings.preferencesResetAt,
  };
}
