import { HttpError, json, readJson, route } from "@/lib/server/api";
import { z } from "zod";
import { validateClipDraft, type ClipDraftInput } from "@/lib/domain/validation";
import { deleteClip, getClipView, updateClip } from "@/lib/repo/clips";
import { getSource, InputError } from "@/lib/repo/sources";

type Ctx = { params: Promise<{ id: string }> };

export const GET = route<Ctx>(async (_req, { db, params }) => {
  const clip = getClipView(db, (await params).id);
  if (!clip) throw new HttpError(404, "Clip not found.");
  return json({ clip });
});

export const PATCH = route<Ctx>(async (req, { db, params }) => {
  const id = (await params).id;
  const existing = getClipView(db, id);
  if (!existing) throw new HttpError(404, "Clip not found.");
  const source = getSource(db, existing.sourceVideoId);
  const body = z.object({}).passthrough().parse(await readJson(req)) as ClipDraftInput;
  const result = validateClipDraft(body, { videoDurationSeconds: source?.durationSeconds });
  if (!result.ok) throw new InputError("Please fix the highlighted fields.", result.errors);
  return json({ clip: updateClip(db, id, result.value) });
});

export const DELETE = route<Ctx>(async (_req, { db, params }) => {
  if (!deleteClip(db, (await params).id)) throw new HttpError(404, "Clip not found.");
  return json({ ok: true });
});
