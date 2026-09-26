import { z } from "zod";
import { json, readJson, route } from "@/lib/server/api";
import { extractYouTubeId } from "@/lib/domain/youtube";
import { proposeClips } from "@/lib/ingest/pipeline";
import { getSettings } from "@/lib/repo/settings";
import { getSourceByYouTubeId, InputError } from "@/lib/repo/sources";

const Body = z.object({
  url: z.string().trim().max(500),
  title: z.string().max(300).optional(),
  transcript: z.string().max(500_000, "Transcript is too long (max ~500k characters)."),
  durationSeconds: z.number().positive().max(86_400).nullish(),
});

/** Transcript → proposed clips. Nothing is saved until /api/ingest/commit. */
export const POST = route(async (req, { db }) => {
  const body = Body.parse(await readJson(req));
  const fields: Record<string, string> = {};
  const videoId = extractYouTubeId(body.url);
  if (!body.url) fields.url = "Paste the YouTube URL for this transcript.";
  else if (!videoId) fields.url = "That doesn't look like a YouTube video URL.";
  if (!body.transcript.trim()) fields.transcript = "Paste a timestamped transcript (or use Manual clip instead).";
  if (Object.keys(fields).length) throw new InputError("Please fix the highlighted fields.", fields);

  const existing = getSourceByYouTubeId(db, videoId!);
  const proposal = await proposeClips(
    {
      transcript: body.transcript,
      videoTitle: body.title || existing?.title,
      videoDurationSeconds: body.durationSeconds ?? existing?.durationSeconds ?? null,
    },
    { ai: getSettings(db).ai },
  );
  return json({ videoId, existingSourceId: existing?.id ?? null, ...proposal });
});
