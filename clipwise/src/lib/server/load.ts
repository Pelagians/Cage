import { DatabaseInitError, getDb, type DB } from "../db/client";

/** Run a server-component data loader, turning failures into a friendly message. */
export function load<T>(fn: (db: DB) => T): { ok: true; data: T } | { ok: false; error: string } {
  try {
    return { ok: true, data: fn(getDb()) };
  } catch (err) {
    if (err instanceof DatabaseInitError) return { ok: false, error: err.message };
    console.error("[clipwise] page data failed", err);
    return { ok: false, error: "The local database couldn't be read. Check the terminal running the app for details." };
  }
}
