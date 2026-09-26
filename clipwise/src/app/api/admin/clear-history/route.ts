import { json, route } from "@/lib/server/api";
import { clearInteractions } from "@/lib/repo/interactions";

/** Delete every interaction (impressions, watches, likes). Saved clips are kept. */
export const POST = route(async (_req, { db }) => {
  clearInteractions(db);
  return json({ ok: true });
});
