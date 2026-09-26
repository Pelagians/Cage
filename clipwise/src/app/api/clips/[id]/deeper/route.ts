import { idList, json, route } from "@/lib/server/api";
import { getDeeperClips } from "@/lib/recommend/service";

export const dynamic = "force-dynamic";

export const GET = route<{ params: Promise<{ id: string }> }>(async (req, { db, params }) => {
  const clips = getDeeperClips(db, (await params).id, idList(req.nextUrl.searchParams.get("exclude")));
  return json({ clips: clips.slice(0, 5) });
});
