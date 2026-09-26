import { z } from "zod";
import { HttpError, json, readJson, route } from "@/lib/server/api";
import { getClipView } from "@/lib/repo/clips";
import { logInteraction, setSaved } from "@/lib/repo/interactions";

const Body = z.object({ saved: z.boolean() });

export const POST = route<{ params: Promise<{ id: string }> }>(async (req, { db, params }) => {
  const id = (await params).id;
  const { saved } = Body.parse(await readJson(req));
  const clip = getClipView(db, id);
  if (!clip) throw new HttpError(404, "Clip not found.");
  if (clip.saved !== saved) {
    db.transaction(() => {
      setSaved(db, id, saved);
      logInteraction(db, { clipId: id, action: saved ? "saved" : "unsaved" });
    })();
  }
  return json({ saved });
});
