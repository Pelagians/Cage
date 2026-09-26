import type { DB } from "../db/client";
import { DEFAULT_SETTINGS, type AppSettings } from "../types";

export function getSettings(db: DB): AppSettings {
  const rows = db.prepare("SELECT key, value FROM settings").all() as { key: string; value: string }[];
  const stored: Record<string, unknown> = {};
  for (const r of rows) {
    try {
      stored[r.key] = JSON.parse(r.value);
    } catch {
      // ignore corrupt values; defaults apply
    }
  }
  const ai = { ...DEFAULT_SETTINGS.ai, ...((stored.ai as object | undefined) ?? {}) };
  const rate = typeof stored.explorationRate === "number" ? stored.explorationRate : DEFAULT_SETTINGS.explorationRate;
  return {
    explorationRate: Math.min(0.5, Math.max(0, rate)),
    autoplayOnWatch:
      typeof stored.autoplayOnWatch === "boolean" ? stored.autoplayOnWatch : DEFAULT_SETTINGS.autoplayOnWatch,
    preferencesResetAt: typeof stored.preferencesResetAt === "string" ? stored.preferencesResetAt : null,
    ai,
  };
}

export function updateSettings(db: DB, patch: Partial<AppSettings>): AppSettings {
  const upsert = db.prepare("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value");
  db.transaction(() => {
    for (const [key, value] of Object.entries(patch)) {
      if (value === undefined) continue;
      upsert.run(key, JSON.stringify(value));
    }
  })();
  return getSettings(db);
}
