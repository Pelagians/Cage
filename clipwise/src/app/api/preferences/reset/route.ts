import { json, route } from "@/lib/server/api";
import { updateSettings } from "@/lib/repo/settings";
import { getProfileSummary } from "@/lib/recommend/service";

/** Forget learned preferences without deleting history or saved clips. */
export const POST = route(async (_req, { db }) => {
  updateSettings(db, { preferencesResetAt: new Date().toISOString() });
  return json(getProfileSummary(db));
});
