import type { DB } from "../db/client";
import type { ClipOrigin, ClipView } from "../types";
import type { ValidClip } from "../domain/validation";
import { normalizeTopic } from "../domain/validation";
import { mapClipView, type ClipJoinRow } from "./rows";
import { getSource, InputError } from "./sources";

const SELECT_VIEW = `
  SELECT c.*,
         s.media_kind AS s_media_kind, s.youtube_video_id AS s_youtube_video_id, s.title AS s_title,
         s.channel AS s_channel, s.thumbnail_url AS s_thumbnail_url, s.source_url AS s_source_url,
         CASE WHEN sv.clip_id IS NULL THEN 0 ELSE 1 END AS saved
  FROM knowledge_clips c
  JOIN source_videos s ON s.id = c.source_video_id
  LEFT JOIN saved_clips sv ON sv.clip_id = c.id`;

export function listClipViews(db: DB): ClipView[] {
  return (db.prepare(`${SELECT_VIEW} ORDER BY c.created_at ASC, c.id ASC`).all() as ClipJoinRow[]).map(mapClipView);
}

export function listClipViewsForSource(db: DB, sourceId: string): ClipView[] {
  return (
    db.prepare(`${SELECT_VIEW} WHERE c.source_video_id = ? ORDER BY c.start_seconds ASC`).all(sourceId) as ClipJoinRow[]
  ).map(mapClipView);
}

export function getClipView(db: DB, id: string): ClipView | null {
  const row = db.prepare(`${SELECT_VIEW} WHERE c.id = ?`).get(id) as ClipJoinRow | undefined;
  return row ? mapClipView(row) : null;
}

export function listSavedClipViews(db: DB): ClipView[] {
  return (
    db.prepare(`${SELECT_VIEW} WHERE sv.clip_id IS NOT NULL ORDER BY sv.created_at DESC`).all() as ClipJoinRow[]
  ).map(mapClipView);
}

export interface CreateClipOptions {
  origin?: ClipOrigin;
  qualityScore?: number;
  relatedClipIds?: string[];
}

function checkAgainstSource(db: DB, sourceVideoId: string, clip: ValidClip) {
  const source = getSource(db, sourceVideoId);
  if (!source) throw new InputError("That source video no longer exists.");
  if (source.durationSeconds && clip.endSeconds > source.durationSeconds + 1) {
    throw new InputError("End time is past the end of the video.", { end: "End time is past the end of the video." });
  }
}

export function createClip(db: DB, sourceVideoId: string, clip: ValidClip, opts: CreateClipOptions = {}): ClipView {
  checkAgainstSource(db, sourceVideoId, clip);
  const id = crypto.randomUUID();
  const now = new Date().toISOString();
  const quality = Math.min(1, Math.max(0, opts.qualityScore ?? 0.6));
  db.prepare(
    `INSERT INTO knowledge_clips (id, source_video_id, title, hook, summary, topic, tags, start_seconds, end_seconds,
                                  duration_seconds, quality_score, related_clip_ids, origin, timestamps_verified,
                                  created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)`,
  ).run(
    id,
    sourceVideoId,
    clip.title,
    clip.hook,
    clip.summary,
    normalizeTopic(clip.topic),
    JSON.stringify(clip.tags),
    clip.startSeconds,
    clip.endSeconds,
    clip.endSeconds - clip.startSeconds,
    quality,
    JSON.stringify(opts.relatedClipIds ?? []),
    opts.origin ?? "manual",
    now,
    now,
  );
  return getClipView(db, id)!;
}

/** Replace a clip's editable fields. Editing timestamps marks them as verified by you. */
export function updateClip(db: DB, id: string, clip: ValidClip): ClipView | null {
  const existing = getClipView(db, id);
  if (!existing) return null;
  checkAgainstSource(db, existing.sourceVideoId, clip);
  db.prepare(
    `UPDATE knowledge_clips SET title = ?, hook = ?, summary = ?, topic = ?, tags = ?, start_seconds = ?,
       end_seconds = ?, duration_seconds = ?, timestamps_verified = 1, updated_at = ?
     WHERE id = ?`,
  ).run(
    clip.title,
    clip.hook,
    clip.summary,
    normalizeTopic(clip.topic),
    JSON.stringify(clip.tags),
    clip.startSeconds,
    clip.endSeconds,
    clip.endSeconds - clip.startSeconds,
    new Date().toISOString(),
    id,
  );
  return getClipView(db, id);
}

export function deleteClip(db: DB, id: string): boolean {
  return db.prepare("DELETE FROM knowledge_clips WHERE id = ?").run(id).changes > 0;
}
