import type Database from "better-sqlite3";
import { SEED_CLIPS, SEED_VIDEOS } from "./seed-data";
import { parseTimestamp } from "../domain/time";
import { youTubeThumbnailUrl, youTubeWatchUrl } from "../domain/youtube";

/** Insert the demo videos and clips. Assumes empty content tables. */
export function seedDemoData(db: Database.Database): void {
  const now = new Date().toISOString();
  const insertVideo = db.prepare(`
    INSERT INTO source_videos (id, media_kind, youtube_video_id, title, channel, source_url, thumbnail_url,
                               duration_seconds, description, is_demo, created_at)
    VALUES (@id, 'youtube', @youtubeVideoId, @title, @channel, @sourceUrl, @thumbnailUrl,
            @durationSeconds, @description, 1, @createdAt)`);
  const insertClip = db.prepare(`
    INSERT INTO knowledge_clips (id, source_video_id, title, hook, summary, topic, tags, start_seconds, end_seconds,
                                 duration_seconds, quality_score, related_clip_ids, origin, timestamps_verified,
                                 created_at, updated_at)
    VALUES (@id, @sourceVideoId, @title, @hook, @summary, @topic, @tags, @start, @end, @duration, @quality,
            @related, 'seed', @verified, @createdAt, @createdAt)`);

  const videoIds = new Map<string, string>();
  for (const v of SEED_VIDEOS) {
    const id = `seed-video-${v.key}`;
    videoIds.set(v.key, id);
    insertVideo.run({
      id,
      youtubeVideoId: v.youtubeVideoId,
      title: v.title,
      channel: v.channel,
      sourceUrl: youTubeWatchUrl(v.youtubeVideoId),
      thumbnailUrl: youTubeThumbnailUrl(v.youtubeVideoId),
      durationSeconds: v.durationSeconds,
      description: v.description,
      createdAt: now,
    });
  }

  for (const c of SEED_CLIPS) {
    const start = parseTimestamp(c.start);
    const end = parseTimestamp(c.end);
    const sourceVideoId = videoIds.get(c.video);
    if (start === null || end === null || end <= start || !sourceVideoId) {
      throw new Error(`Invalid seed clip ${c.id}`);
    }
    insertClip.run({
      id: c.id,
      sourceVideoId,
      title: c.title,
      hook: c.hook,
      summary: c.summary,
      topic: c.topic,
      tags: JSON.stringify(c.tags),
      start,
      end,
      duration: end - start,
      quality: c.quality,
      related: JSON.stringify(c.related),
      verified: c.verified ? 1 : 0,
      createdAt: now,
    });
  }
}
