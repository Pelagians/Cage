import type { DB } from "../db/client";
import type { InteractionAction, UserInteraction } from "../types";

interface InteractionRow {
  id: number;
  clip_id: string;
  action: string;
  watch_seconds: number | null;
  completion_ratio: number | null;
  created_at: string;
}

export interface LogInteractionInput {
  clipId: string;
  action: InteractionAction;
  watchSeconds?: number | null;
  completionRatio?: number | null;
  at?: string;
}

function clampRatio(r: number | null | undefined): number | null {
  if (r === null || r === undefined || !Number.isFinite(r)) return null;
  return Math.min(1, Math.max(0, r));
}

export function logInteraction(db: DB, input: LogInteractionInput): void {
  db.prepare(
    `INSERT INTO user_interactions (clip_id, action, watch_seconds, completion_ratio, created_at)
     VALUES (?, ?, ?, ?, ?)`,
  ).run(
    input.clipId,
    input.action,
    input.watchSeconds != null && Number.isFinite(input.watchSeconds) ? Math.max(0, input.watchSeconds) : null,
    clampRatio(input.completionRatio),
    input.at ?? new Date().toISOString(),
  );
}

/** Log many interactions at once; unknown clip IDs are skipped instead of failing the batch. */
export function logInteractions(db: DB, inputs: LogInteractionInput[]): number {
  const exists = db.prepare("SELECT 1 FROM knowledge_clips WHERE id = ?");
  let n = 0;
  db.transaction(() => {
    for (const input of inputs) {
      if (!exists.get(input.clipId)) continue;
      logInteraction(db, input);
      n++;
    }
  })();
  return n;
}

export function listInteractions(db: DB, opts: { since?: string | null; limit?: number } = {}): UserInteraction[] {
  const rows = db
    .prepare(
      `SELECT * FROM user_interactions WHERE (? IS NULL OR created_at >= ?) ORDER BY created_at DESC, id DESC LIMIT ?`,
    )
    .all(opts.since ?? null, opts.since ?? null, opts.limit ?? 5000) as InteractionRow[];
  return rows.map((r) => ({
    id: r.id,
    clipId: r.clip_id,
    action: r.action as InteractionAction,
    watchSeconds: r.watch_seconds,
    completionRatio: r.completion_ratio,
    createdAt: r.created_at,
  }));
}

export function clearInteractions(db: DB): void {
  db.prepare("DELETE FROM user_interactions").run();
}

export function setSaved(db: DB, clipId: string, saved: boolean): void {
  if (saved) {
    db.prepare("INSERT OR IGNORE INTO saved_clips (clip_id, created_at) VALUES (?, ?)").run(
      clipId,
      new Date().toISOString(),
    );
  } else {
    db.prepare("DELETE FROM saved_clips WHERE clip_id = ?").run(clipId);
  }
}

export function listSavedIds(db: DB): Set<string> {
  return new Set((db.prepare("SELECT clip_id FROM saved_clips").all() as { clip_id: string }[]).map((r) => r.clip_id));
}
