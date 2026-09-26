import { json, route } from "@/lib/server/api";
import { resetDatabase } from "@/lib/db/client";

/** Wipe everything (including your own videos and clips) and restore the demo content. */
export const POST = route(async (_req, { db }) => {
  resetDatabase(db);
  return json({ ok: true });
});
