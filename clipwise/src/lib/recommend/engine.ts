/**
 * Local recommendation engine: deterministic, dependency-free math.
 *
 * 1. PROFILE (derived, never stored)
 *    Each interaction contributes `ACTION_WEIGHTS[action] × decay(age)` to the clip's
 *    topic and (× TAG_SHARE) to each of its tags. decay = 0.5^(ageDays / HALF_LIFE_DAYS).
 *    Raw sums are squashed with tanh(raw / SATURATION) into affinities in (-1, 1), so
 *    no single topic can grow without bound.
 *
 * 2. SCORE (per clip)
 *      score = 1.0 × quality                       editorial prior, 0..1
 *            + 1.2 × topicAffinity                 -1..1
 *            + 0.8 × mean(tagAffinity)             -1..1
 *            + 0.6 × relatedness to recent clips   0..1 (explicit link = 1, else tag overlap)
 *            + 0.25 × novelty                      1 if never shown
 *            − watched penalty                     1.5 completed / 0.6 opened (decays)
 *            − 0.15 × recent impressions (72h, max 6)   repetition
 *            − 2.0 if you said "less like this" to this exact clip
 *            − 0.3 if already saved (it lives in Saved)
 *            + jitter × 0.15                       seeded, so refreshes vary slightly
 *
 * 3. FEED = exploit + explore
 *    A share `explorationRate` (default 25%) of slots is filled from an exploration
 *    pool of clips whose topic you have NOT shown affinity for (affinity ≤ 0.15), ranked
 *    by quality, novelty and randomness. The rest follow the score. Consecutive runs of
 *    one topic are broken up when a near-equal alternative exists.
 */
import type { InteractionAction, KnowledgeClip, UserInteraction } from "../types";

export const ACTION_WEIGHTS: Record<InteractionAction, number> = {
  impression: 0,
  opened: 0.5,
  completed: 1.5, // × completion ratio when known
  continued_original: 1.5,
  saved: 2.5,
  unsaved: -1,
  more_like_this: 3,
  less_like_this: -3.5,
  skipped: -1,
};

export const HALF_LIFE_DAYS = 21;
export const TAG_SHARE = 0.6;
export const SATURATION = 3;
export const EXPLORE_AFFINITY_CEILING = 0.15;

export const SCORE_WEIGHTS = {
  quality: 1.0,
  topic: 1.2,
  tag: 0.8,
  related: 0.6,
  novelty: 0.25,
  completedPenalty: 1.5,
  openedPenalty: 0.6,
  repetitionPerImpression: 0.15,
  repetitionCap: 6,
  lessLikeThisClip: 2.0,
  alreadySaved: 0.3,
  jitter: 0.15,
} as const;

const DAY_MS = 86_400_000;
const REPETITION_WINDOW_MS = 3 * DAY_MS;

export type ClipLike = Pick<KnowledgeClip, "id" | "topic" | "tags" | "qualityScore" | "relatedClipIds">;

export interface ClipStats {
  impressions: number;
  recentImpressions: number;
  opened: number;
  completed: number;
  lastWatchedAt: number | null;
  lessLike: boolean;
  moreLike: boolean;
}

export interface PreferenceProfile {
  topicAffinity: Map<string, number>;
  tagAffinity: Map<string, number>;
  clipStats: Map<string, ClipStats>;
  /** Most recent first, deduplicated, clips you opened or finished. */
  recentClipIds: string[];
  interactionCount: number;
}

export const topicKey = (t: string) => t.trim().toLowerCase();
export const tagKey = (t: string) => t.trim().toLowerCase();

function decay(ageMs: number, halfLifeDays = HALF_LIFE_DAYS): number {
  return Math.pow(0.5, Math.max(0, ageMs) / (halfLifeDays * DAY_MS));
}

function emptyStats(): ClipStats {
  return { impressions: 0, recentImpressions: 0, opened: 0, completed: 0, lastWatchedAt: null, lessLike: false, moreLike: false };
}

export function buildProfile(
  clips: ClipLike[],
  interactions: UserInteraction[],
  now: number = Date.now(),
): PreferenceProfile {
  const byId = new Map(clips.map((c) => [c.id, c]));
  const rawTopic = new Map<string, number>();
  const rawTag = new Map<string, number>();
  const clipStats = new Map<string, ClipStats>();
  const recent: { id: string; at: number }[] = [];

  for (const it of interactions) {
    const clip = byId.get(it.clipId);
    if (!clip) continue;
    const at = Date.parse(it.createdAt);
    const age = Number.isFinite(at) ? now - at : 0;
    const stats = clipStats.get(clip.id) ?? emptyStats();
    clipStats.set(clip.id, stats);

    switch (it.action) {
      case "impression":
        stats.impressions++;
        if (age <= REPETITION_WINDOW_MS) stats.recentImpressions++;
        break;
      case "opened":
        stats.opened++;
        stats.lastWatchedAt = Math.max(stats.lastWatchedAt ?? 0, at);
        recent.push({ id: clip.id, at });
        break;
      case "completed":
        stats.completed++;
        stats.lastWatchedAt = Math.max(stats.lastWatchedAt ?? 0, at);
        recent.push({ id: clip.id, at });
        break;
      case "less_like_this":
        stats.lessLike = true;
        break;
      case "more_like_this":
        stats.moreLike = true;
        break;
    }

    let weight = ACTION_WEIGHTS[it.action] ?? 0;
    if (it.action === "completed" && it.completionRatio != null) weight *= Math.max(0.25, it.completionRatio);
    if (weight === 0) continue;
    const w = weight * decay(age);
    const tk = topicKey(clip.topic);
    rawTopic.set(tk, (rawTopic.get(tk) ?? 0) + w);
    for (const tag of clip.tags) {
      const k = tagKey(tag);
      rawTag.set(k, (rawTag.get(k) ?? 0) + w * TAG_SHARE);
    }
  }

  const squash = (m: Map<string, number>) => new Map([...m].map(([k, v]) => [k, Math.tanh(v / SATURATION)]));
  recent.sort((a, b) => b.at - a.at);
  const recentClipIds: string[] = [];
  for (const r of recent) {
    if (!recentClipIds.includes(r.id)) recentClipIds.push(r.id);
    if (recentClipIds.length >= 10) break;
  }

  return {
    topicAffinity: squash(rawTopic),
    tagAffinity: squash(rawTag),
    clipStats,
    recentClipIds,
    interactionCount: interactions.length,
  };
}

export function jaccard(a: string[], b: string[]): number {
  if (a.length === 0 || b.length === 0) return 0;
  const A = new Set(a.map(tagKey));
  const B = new Set(b.map(tagKey));
  let inter = 0;
  for (const x of A) if (B.has(x)) inter++;
  return inter / (A.size + B.size - inter);
}

export interface ScoreBreakdown {
  total: number;
  quality: number;
  topic: number;
  tag: number;
  related: number;
  novelty: number;
  penalties: number;
}

export function relatednessToRecent(clip: ClipLike, profile: PreferenceProfile, byId: Map<string, ClipLike>): number {
  let best = 0;
  for (const rid of profile.recentClipIds.slice(0, 5)) {
    if (rid === clip.id) continue;
    const r = byId.get(rid);
    if (!r) continue;
    if (r.relatedClipIds.includes(clip.id) || clip.relatedClipIds.includes(rid)) return 1;
    best = Math.max(best, jaccard(r.tags, clip.tags) * 1.5);
  }
  return Math.min(1, best);
}

export function scoreClip(
  clip: ClipLike,
  profile: PreferenceProfile,
  ctx: { byId: Map<string, ClipLike>; savedIds?: Set<string>; now?: number; jitter?: number },
): ScoreBreakdown {
  const W = SCORE_WEIGHTS;
  const now = ctx.now ?? Date.now();
  const stats = profile.clipStats.get(clip.id) ?? emptyStats();

  const quality = W.quality * clip.qualityScore;
  const topic = W.topic * (profile.topicAffinity.get(topicKey(clip.topic)) ?? 0);
  const tagVals = clip.tags.map((t) => profile.tagAffinity.get(tagKey(t)) ?? 0);
  const tag = W.tag * (tagVals.length ? tagVals.reduce((a, b) => a + b, 0) / tagVals.length : 0);
  const related = W.related * relatednessToRecent(clip, profile, ctx.byId);
  const novelty = stats.impressions === 0 && stats.opened === 0 ? W.novelty : 0;

  let penalties = 0;
  const watchedDecay = stats.lastWatchedAt ? decay(now - stats.lastWatchedAt, 30) : 1;
  if (stats.completed > 0) penalties += W.completedPenalty * watchedDecay;
  else if (stats.opened > 0) penalties += W.openedPenalty * watchedDecay;
  penalties += W.repetitionPerImpression * Math.min(stats.recentImpressions, W.repetitionCap);
  if (stats.lessLike) penalties += W.lessLikeThisClip;
  if (ctx.savedIds?.has(clip.id)) penalties += W.alreadySaved;

  const jitter = (ctx.jitter ?? 0) * W.jitter;
  const total = quality + topic + tag + related + novelty - penalties + jitter;
  return { total, quality, topic, tag, related, novelty, penalties };
}

/** Small seeded PRNG (mulberry32) so feeds are reproducible in tests. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export interface FeedEntry {
  clipId: string;
  score: number;
  slot: "personal" | "explore";
}

export interface BuildFeedOptions {
  explorationRate: number;
  seed?: number;
  limit?: number;
  excludeIds?: Iterable<string>;
  savedIds?: Set<string>;
  now?: number;
}

export function buildFeed(clips: ClipLike[], profile: PreferenceProfile, opts: BuildFeedOptions): FeedEntry[] {
  const rng = mulberry32(opts.seed ?? 1);
  const byId = new Map(clips.map((c) => [c.id, c]));
  const exclude = new Set(opts.excludeIds ?? []);
  const rate = Math.min(0.5, Math.max(0, opts.explorationRate));
  const limit = opts.limit ?? 50;

  const candidates = clips.filter((c) => !exclude.has(c.id));
  const scored = candidates.map((c) => ({
    clip: c,
    score: scoreClip(c, profile, { byId, savedIds: opts.savedIds, now: opts.now, jitter: rng() }).total,
  }));
  const exploit = [...scored].sort((a, b) => b.score - a.score || a.clip.id.localeCompare(b.clip.id));

  const explore = scored
    .filter(({ clip }) => {
      const stats = profile.clipStats.get(clip.id);
      if (stats?.lessLike || (stats?.completed ?? 0) > 0) return false;
      return (profile.topicAffinity.get(topicKey(clip.topic)) ?? 0) <= EXPLORE_AFFINITY_CEILING;
    })
    .map(({ clip, score }) => {
      const stats = profile.clipStats.get(clip.id);
      const fresh = !stats || stats.impressions === 0 ? 0.3 : 0;
      return { clip, score, exploreScore: clip.qualityScore + fresh + rng() * 0.6 };
    })
    .sort((a, b) => b.exploreScore - a.exploreScore || a.clip.id.localeCompare(b.clip.id));

  const used = new Set<string>();
  const out: FeedEntry[] = [];
  let acc = 0.5; // puts the first exploration slot early (2nd position at 25%)

  const takeExploit = () => {
    const recentTopics = out.slice(-2).map((e) => topicKey(byId.get(e.clipId)!.topic));
    const streak = recentTopics.length === 2 && recentTopics[0] === recentTopics[1] ? recentTopics[0] : null;
    let pick: (typeof exploit)[number] | undefined;
    for (const cand of exploit) {
      if (used.has(cand.clip.id)) continue;
      if (!pick) pick = cand;
      if (!streak || topicKey(cand.clip.topic) !== streak) {
        // Break a 3-in-a-row topic streak only if the alternative is close in score.
        if (cand === pick || cand.score >= pick.score - 0.8) pick = cand;
        break;
      }
    }
    return pick;
  };

  while (out.length < Math.min(limit, candidates.length)) {
    acc += rate;
    let entry: FeedEntry | null = null;
    if (acc >= 1) {
      acc -= 1;
      const e = explore.find((x) => !used.has(x.clip.id));
      if (e) entry = { clipId: e.clip.id, score: e.score, slot: "explore" };
    }
    if (!entry) {
      const p = takeExploit();
      if (!p) break;
      entry = { clipId: p.clip.id, score: p.score, slot: "personal" };
    }
    used.add(entry.clipId);
    out.push(entry);
  }
  return out;
}

/** Clips that go "deeper" from `clip`: explicit links first, then tag/topic similarity. */
export function relatedClips(clip: ClipLike & { sourceVideoId?: string; startSeconds?: number }, clips: (ClipLike & { sourceVideoId?: string; startSeconds?: number })[], limit = 5) {
  const scored = clips
    .filter((c) => c.id !== clip.id)
    .map((c) => {
      let s = 0;
      if (clip.relatedClipIds.includes(c.id)) s += 3;
      if (c.relatedClipIds.includes(clip.id)) s += 1.5;
      s += jaccard(clip.tags, c.tags) * 2;
      if (topicKey(c.topic) === topicKey(clip.topic)) s += 0.75;
      // The next idea in the same video continues the thread.
      if (clip.sourceVideoId && c.sourceVideoId === clip.sourceVideoId && (c.startSeconds ?? 0) > (clip.startSeconds ?? 0)) s += 0.5;
      return { clip: c, score: s + c.qualityScore * 0.1 };
    })
    .filter((x) => x.score > 0.1 + x.clip.qualityScore * 0.1)
    .sort((a, b) => b.score - a.score || a.clip.id.localeCompare(b.clip.id));
  return scored.slice(0, limit).map((x) => x.clip);
}

export type Trend = "strong-up" | "up" | "neutral" | "down" | "strong-down";

export function trendOf(affinity: number): Trend {
  if (affinity > 0.45) return "strong-up";
  if (affinity > 0.15) return "up";
  if (affinity >= -0.15) return "neutral";
  if (affinity >= -0.45) return "down";
  return "strong-down";
}
