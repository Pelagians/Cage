import { z } from "zod";
import { HttpError, json, readJson, route } from "@/lib/server/api";
import { validateClipDraft, type ClipDraftInput } from "@/lib/domain/validation";
import { createClip } from "@/lib/repo/clips";
import { getSource, InputError } from "@/lib/repo/sources";

const Body = z.object({ sourceId: z.string().min(1) }).passthrough();

/** Manual clip creation for an existing SourceVideo. */
export const POST = route(async (req, { db }) => {
  const body = Body.parse(await readJson(req));
  const source = getSource(db, body.sourceId);
  if (!source) throw new HttpError(404, "That video isn't in your library any more.");
  const result = validateClipDraft(body as ClipDraftInput, { videoDurationSeconds: source.durationSeconds });
  if (!result.ok) throw new InputError("Please fix the highlighted fields.", result.errors);
  const clip = createClip(db, source.id, result.value, { origin: "manual", qualityScore: 0.7 });
  return json({ clip }, 201);
});
