import Database from "better-sqlite3";
import fs from "node:fs";
import path from "node:path";
import { MIGRATIONS } from "./migrations";
import { seedDemoData } from "./seed";

export type DB = Database.Database;

export class DatabaseInitError extends Error {
  constructor(message: string, public readonly cause?: unknown) {
    super(message);
    this.name = "DatabaseInitError";
  }
}

export function resolveDbPath(): string {
  const configured = process.env.CLIPWISE_DB_PATH;
  if (configured?.trim() === ":memory:") return ":memory:";
  return path.resolve(process.cwd(), configured && configured.trim() ? configured : "data/clipwise.db");
}

export function migrate(db: DB): void {
  const current = db.pragma("user_version", { simple: true }) as number;
  for (const m of MIGRATIONS) {
    if (m.version <= current) continue;
    db.transaction(() => {
      db.exec(m.sql);
      db.pragma(`user_version = ${m.version}`);
    })();
  }
}

/** Open a database, apply migrations and seed demo content on first run. */
export function openDatabase(file: string, opts: { seed?: boolean } = {}): DB {
  if (file !== ":memory:") fs.mkdirSync(path.dirname(file), { recursive: true });
  const db = new Database(file);
  db.pragma("journal_mode = WAL");
  db.pragma("foreign_keys = ON");
  db.pragma("busy_timeout = 5000");
  migrate(db);
  if (opts.seed !== false) {
    const seeded = db.prepare("SELECT value FROM meta WHERE key = 'seeded'").get();
    if (!seeded) {
      db.transaction(() => {
        seedDemoData(db);
        db.prepare("INSERT OR REPLACE INTO meta (key, value) VALUES ('seeded', ?)").run(new Date().toISOString());
      })();
    }
  }
  return db;
}

// Survive Next.js dev hot reloads without leaking connections.
const globalForDb = globalThis as unknown as { __clipwiseDb?: DB };

export function getDb(): DB {
  if (globalForDb.__clipwiseDb) return globalForDb.__clipwiseDb;
  const file = resolveDbPath();
  try {
    globalForDb.__clipwiseDb = openDatabase(file);
  } catch (err) {
    console.error("[clipwise] database initialisation failed", err);
    throw new DatabaseInitError(
      `Couldn't open the local database at ${file}. Check that the folder is writable, or run "npm run db:reset".`,
      err,
    );
  }
  return globalForDb.__clipwiseDb;
}

/** Close and forget the cached connection (used by reset). */
export function closeDb(): void {
  globalForDb.__clipwiseDb?.close();
  globalForDb.__clipwiseDb = undefined;
}

/** Wipe every table and re-seed the demo content. Keeps the file in place. */
export function resetDatabase(db: DB = getDb()): void {
  db.transaction(() => {
    db.exec(`
      DELETE FROM user_interactions;
      DELETE FROM saved_clips;
      DELETE FROM knowledge_clips;
      DELETE FROM source_videos;
      DELETE FROM settings;
      DELETE FROM meta;
    `);
    seedDemoData(db);
    db.prepare("INSERT OR REPLACE INTO meta (key, value) VALUES ('seeded', ?)").run(new Date().toISOString());
  })();
}
