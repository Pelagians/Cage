import { z } from "zod";
import { json, readJson, route } from "@/lib/server/api";
import { validateClipDraft } from "@/lib/domain/validation";
import { createClip } from "@/lib/repo/clips";
import { InputError, upsertYouTubeSource } from "@/lib/repo/sources";

const Body = z.object({
  url: z.string().trim().min(1).max(500),
  title: z.string().max(300).optional(),
  channel: z.string().max(200).optional(),
  durationSeconds: z.number().positive().max(86_400).nullish(),
  clips: z
    .array(
      z.object({
        candidateId: z.string().optional(),
        title: z.unknown(),
        hook: z.unknown(),
        summary: z.unknown(),
        topic: z.unknown(),
        tags: z.unknown(),
        start: z.unknown(),
        end: z.unknown(),
        qualityScore: z.number().min(0).max(1).optional(),
      }),
    )
    .min(1, "Approve at least one clip first.")
    .max(200),
});

/** Save approved clips (all-or-nothing) and the SourceVideo they belong to. */
export const POST = route(async (req, { db }) => {
  const body = Body.parse(await readJson(req));
  const validated = body.clips.map((c) => ({ c, r: validateClipDraft(c, { videoDurationSeconds: body.durationSeconds }) }));
  const bad = validated.filter((v) => !v.r.ok);
  if (bad.length) {
    const fields: Record<string, string> = {};
    for (const { c, r } of bad) if (!r.ok) for (const [k, msg] of Object.entries(r.errors)) fields[`${c.candidateId ?? "clip"}.${k}`] = msg;
    throw new InputError(`${bad.length} approved clip(s) have problems. Fix them and try again.`, fields);
  }
  const created = db.transaction(() => {
    const source = upsertYouTubeSource(db, body);
    return validated.map(({ c, r }) =>
      createClip(db, source.id, (r as Extract<typeof r, { ok: true }>).value, { origin: "ingest", qualityScore: c.qualityScore }),
    );
  })();
  return json({ clips: created, sourceId: created[0]?.sourceVideoId }, 201);
});
