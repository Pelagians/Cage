import { z } from "zod";
import { HttpError, json, readJson, route } from "@/lib/server/api";
import { deleteSource, getSource, updateSourceMetadata } from "@/lib/repo/sources";
import { listClipViewsForSource } from "@/lib/repo/clips";

type Ctx = { params: Promise<{ id: string }> };

const Patch = z.object({
  title: z.string().max(300).optional(),
  channel: z.string().max(200).optional(),
  durationSeconds: z.number().positive().max(86_400).nullish(),
});

export const GET = route<Ctx>(async (_req, { db, params }) => {
  const id = (await params).id;
  const source = getSource(db, id);
  if (!source) throw new HttpError(404, "Video not found.");
  return json({ source, clips: listClipViewsForSource(db, id) });
});

export const PATCH = route<Ctx>(async (req, { db, params }) => {
  const source = updateSourceMetadata(db, (await params).id, Patch.parse(await readJson(req)));
  if (!source) throw new HttpError(404, "Video not found.");
  return json({ source });
});

export const DELETE = route<Ctx>(async (_req, { db, params }) => {
  if (!deleteSource(db, (await params).id)) throw new HttpError(404, "Video not found.");
  return json({ ok: true });
});
