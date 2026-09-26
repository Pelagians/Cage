import { idList, json, route } from "@/lib/server/api";
import { getNextClip } from "@/lib/recommend/service";

export const dynamic = "force-dynamic";

export const GET = route<{ params: Promise<{ id: string }> }>(async (req, { db, params }) => {
  const clip = getNextClip(db, (await params).id, idList(req.nextUrl.searchParams.get("exclude")));
  return json({ clip });
});
