import { json, route } from "@/lib/server/api";
import { listSavedClipViews } from "@/lib/repo/clips";

export const dynamic = "force-dynamic";

export const GET = route(async (_req, { db }) => json({ clips: listSavedClipViews(db) }));
