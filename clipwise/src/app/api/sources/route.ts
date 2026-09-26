import { z } from "zod";
import { json, readJson, route } from "@/lib/server/api";
import { listSources, upsertYouTubeSource } from "@/lib/repo/sources";

export const dynamic = "force-dynamic";

const Body = z.object({
  url: z.string().trim().min(1, "Paste a YouTube URL.").max(500),
  title: z.string().max(300).optional(),
  channel: z.string().max(200).optional(),
  durationSeconds: z.number().positive().max(86_400).nullish(),
});

export const GET = route(async (_req, { db }) => json({ sources: listSources(db) }));

export const POST = route(async (req, { db }) => {
  const body = Body.parse(await readJson(req));
  return json({ source: upsertYouTubeSource(db, body) }, 201);
});
