import { idList, json, route } from "@/lib/server/api";
import { getFeed } from "@/lib/recommend/service";

export const dynamic = "force-dynamic";

export const GET = route(async (req, { db }) => {
  const p = req.nextUrl.searchParams;
  const seed = Number(p.get("seed"));
  const limit = Math.min(100, Math.max(1, Number(p.get("limit")) || 50));
  const clips = getFeed(db, { excludeIds: idList(p.get("exclude")), seed: Number.isFinite(seed) && seed > 0 ? seed : undefined, limit });
  return json({ clips });
});
