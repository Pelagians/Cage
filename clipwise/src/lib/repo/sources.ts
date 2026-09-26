import type { DB } from "../db/client";
import type { SourceVideo } from "../types";
import { extractYouTubeId, youTubeThumbnailUrl, youTubeWatchUrl } from "../domain/youtube";
import { mapSource, type SourceRow } from "./rows";

export class InputError extends Error {
  constructor(message: string, public readonly fields: Record<string, string> = {}) {
    super(message);
    this.name = "InputError";
  }
}

export function listSources(db: DB): (SourceVideo & { clipCount: number })[] {
  const rows = db
    .prepare(
      `SELECT s.*, (SELECT COUNT(*) FROM knowledge_clips c WHERE c.source_video_id = s.id) AS clip_count
       FROM source_videos s ORDER BY s.created_at DESC, s.title ASC`,
    )
    .all() as (SourceRow & { clip_count: number })[];
  return rows.map((r) => ({ ...mapSource(r), clipCount: r.clip_count }));
}

export function getSource(db: DB, id: string): SourceVideo | null {
  const row = db.prepare("SELECT * FROM source_videos WHERE id = ?").get(id) as SourceRow | undefined;
  return row ? mapSource(row) : null;
}

export function getSourceByYouTubeId(db: DB, youtubeVideoId: string): SourceVideo | null {
  const row = db.prepare("SELECT * FROM source_videos WHERE youtube_video_id = ?").get(youtubeVideoId) as
    | SourceRow
    | undefined;
  return row ? mapSource(row) : null;
}

export interface YouTubeSourceInput {
  url: string;
  title?: string;
  channel?: string;
  description?: string;
  durationSeconds?: number | null;
}

/**
 * Find the SourceVideo for a YouTube URL, creating it if needed. Blank metadata on an
 * existing row is filled in from the input; existing non-blank values are kept.
 */
export function upsertYouTubeSource(db: DB, input: YouTubeSourceInput): SourceVideo {
  const youtubeVideoId = extractYouTubeId(input.url);
  if (!youtubeVideoId) {
    throw new InputError("That doesn't look like a YouTube video URL.", {
      url: "Paste a link like https://www.youtube.com/watch?v=… or https://youtu.be/…",
    });
  }
  const title = input.title?.trim() ?? "";
  const channel = input.channel?.trim() ?? "";
  const duration =
    input.durationSeconds && Number.isFinite(input.durationSeconds) && input.durationSeconds > 0
      ? input.durationSeconds
      : null;

  const existing = getSourceByYouTubeId(db, youtubeVideoId);
  if (existing) {
    db.prepare(
      `UPDATE source_videos SET
         title = CASE WHEN @title != '' AND (title = '' OR title LIKE 'YouTube video %') THEN @title ELSE title END,
         channel = CASE WHEN channel = '' THEN @channel ELSE channel END,
         duration_seconds = COALESCE(duration_seconds, @duration),
         description = CASE WHEN description = '' THEN @description ELSE description END
       WHERE id = @id`,
    ).run({ id: existing.id, title, channel, duration, description: input.description?.trim() ?? "" });
    return getSource(db, existing.id)!;
  }

  const id = crypto.randomUUID();
  db.prepare(
    `INSERT INTO source_videos (id, media_kind, youtube_video_id, title, channel, source_url, thumbnail_url,
                                duration_seconds, description, is_demo, created_at)
     VALUES (?, 'youtube', ?, ?, ?, ?, ?, ?, ?, 0, ?)`,
  ).run(
    id,
    youtubeVideoId,
    title || `YouTube video ${youtubeVideoId}`,
    channel,
    youTubeWatchUrl(youtubeVideoId),
    youTubeThumbnailUrl(youtubeVideoId),
    duration,
    input.description?.trim() ?? "",
    new Date().toISOString(),
  );
  return getSource(db, id)!;
}

export function updateSourceMetadata(
  db: DB,
  id: string,
  patch: { title?: string; channel?: string; durationSeconds?: number | null },
): SourceVideo | null {
  const current = getSource(db, id);
  if (!current) return null;
  db.prepare("UPDATE source_videos SET title = ?, channel = ?, duration_seconds = ? WHERE id = ?").run(
    patch.title?.trim() || current.title,
    patch.channel?.trim() ?? current.channel,
    patch.durationSeconds === undefined ? current.durationSeconds : patch.durationSeconds,
    id,
  );
  return getSource(db, id);
}

export function deleteSource(db: DB, id: string): boolean {
  return db.prepare("DELETE FROM source_videos WHERE id = ?").run(id).changes > 0;
}
