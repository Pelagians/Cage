import type { ClipView, KnowledgeClip, SourceVideo } from "../types";

export interface SourceRow {
  id: string;
  media_kind: string;
  youtube_video_id: string | null;
  title: string;
  channel: string;
  source_url: string;
  thumbnail_url: string | null;
  duration_seconds: number | null;
  description: string;
  is_demo: number;
  created_at: string;
}

export interface ClipRow {
  id: string;
  source_video_id: string;
  title: string;
  hook: string;
  summary: string;
  topic: string;
  tags: string;
  start_seconds: number;
  end_seconds: number;
  duration_seconds: number;
  quality_score: number;
  related_clip_ids: string;
  origin: string;
  timestamps_verified: number;
  created_at: string;
}

export interface ClipJoinRow extends ClipRow {
  s_media_kind: string;
  s_youtube_video_id: string | null;
  s_title: string;
  s_channel: string;
  s_thumbnail_url: string | null;
  s_source_url: string;
  saved: number;
}

function parseJsonArray(value: string): string[] {
  try {
    const parsed: unknown = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

export function mapSource(r: SourceRow): SourceVideo {
  return {
    id: r.id,
    mediaKind: r.media_kind === "local" ? "local" : "youtube",
    youtubeVideoId: r.youtube_video_id,
    title: r.title,
    channel: r.channel,
    sourceUrl: r.source_url,
    thumbnailUrl: r.thumbnail_url,
    durationSeconds: r.duration_seconds,
    description: r.description,
    isDemo: r.is_demo === 1,
    createdAt: r.created_at,
  };
}

export function mapClip(r: ClipRow): KnowledgeClip {
  return {
    id: r.id,
    sourceVideoId: r.source_video_id,
    title: r.title,
    hook: r.hook,
    summary: r.summary,
    topic: r.topic,
    tags: parseJsonArray(r.tags),
    startSeconds: r.start_seconds,
    endSeconds: r.end_seconds,
    durationSeconds: r.duration_seconds,
    qualityScore: r.quality_score,
    relatedClipIds: parseJsonArray(r.related_clip_ids),
    origin: r.origin === "seed" || r.origin === "ingest" ? r.origin : "manual",
    timestampsVerified: r.timestamps_verified === 1,
    createdAt: r.created_at,
  };
}

export function mapClipView(r: ClipJoinRow): ClipView {
  return {
    ...mapClip(r),
    saved: r.saved === 1,
    source: {
      id: r.source_video_id,
      mediaKind: r.s_media_kind === "local" ? "local" : "youtube",
      youtubeVideoId: r.s_youtube_video_id,
      title: r.s_title,
      channel: r.s_channel,
      thumbnailUrl: r.s_thumbnail_url,
      sourceUrl: r.s_source_url,
    },
  };
}
