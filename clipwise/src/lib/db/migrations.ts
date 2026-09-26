/**
 * Versioned schema migrations, applied in order using SQLite's PRAGMA user_version.
 * To change the schema, append a new entry — never edit an applied one.
 */
export const MIGRATIONS: { version: number; sql: string }[] = [
  {
    version: 1,
    sql: `
      CREATE TABLE source_videos (
        id               TEXT PRIMARY KEY,
        media_kind       TEXT NOT NULL DEFAULT 'youtube' CHECK (media_kind IN ('youtube', 'local')),
        youtube_video_id TEXT,
        title            TEXT NOT NULL,
        channel          TEXT NOT NULL DEFAULT '',
        source_url       TEXT NOT NULL,
        thumbnail_url    TEXT,
        duration_seconds REAL,
        description      TEXT NOT NULL DEFAULT '',
        is_demo          INTEGER NOT NULL DEFAULT 0,
        created_at       TEXT NOT NULL
      );
      CREATE UNIQUE INDEX ux_source_videos_youtube ON source_videos(youtube_video_id)
        WHERE youtube_video_id IS NOT NULL;

      CREATE TABLE knowledge_clips (
        id                  TEXT PRIMARY KEY,
        source_video_id     TEXT NOT NULL REFERENCES source_videos(id) ON DELETE CASCADE,
        title               TEXT NOT NULL,
        hook                TEXT NOT NULL DEFAULT '',
        summary             TEXT NOT NULL DEFAULT '',
        topic               TEXT NOT NULL DEFAULT 'General',
        tags                TEXT NOT NULL DEFAULT '[]',
        start_seconds       REAL NOT NULL CHECK (start_seconds >= 0),
        end_seconds         REAL NOT NULL,
        duration_seconds    REAL NOT NULL,
        quality_score       REAL NOT NULL DEFAULT 0.6,
        related_clip_ids    TEXT NOT NULL DEFAULT '[]',
        origin              TEXT NOT NULL DEFAULT 'manual' CHECK (origin IN ('seed', 'manual', 'ingest')),
        timestamps_verified INTEGER NOT NULL DEFAULT 1,
        created_at          TEXT NOT NULL,
        updated_at          TEXT NOT NULL,
        CHECK (end_seconds > start_seconds)
      );
      CREATE INDEX ix_clips_source ON knowledge_clips(source_video_id);
      CREATE INDEX ix_clips_topic ON knowledge_clips(topic);

      CREATE TABLE user_interactions (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        clip_id          TEXT NOT NULL REFERENCES knowledge_clips(id) ON DELETE CASCADE,
        action           TEXT NOT NULL,
        watch_seconds    REAL,
        completion_ratio REAL,
        created_at       TEXT NOT NULL
      );
      CREATE INDEX ix_interactions_clip ON user_interactions(clip_id);
      CREATE INDEX ix_interactions_created ON user_interactions(created_at);

      CREATE TABLE saved_clips (
        clip_id    TEXT PRIMARY KEY REFERENCES knowledge_clips(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL
      );

      CREATE TABLE settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
      );

      CREATE TABLE meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
      );
    `,
  },
];
