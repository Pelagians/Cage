import { z } from "zod";
import { HttpError, json, readJson, route } from "@/lib/server/api";
import { getSource } from "@/lib/repo/sources";
import { fetchYouTubeMeta } from "@/lib/server/oembed";

const Body = z.object({ durationSeconds: z.number().positive().max(86_400).nullish() });

/**
 * Fill in missing metadata: duration reported by the player, and title/channel from
 * YouTube oEmbed. Existing values are only replaced when blank or placeholder.
 */
export const POST = route<{ params: Promise<{ id: string }> }>(async (req, { db, params }) => {
  const id = (await params).id;
  const { durationSeconds } = Body.parse(await readJson(req));
  const source = getSource(db, id);
  if (!source) throw new HttpError(404, "Video not found.");

  if (durationSeconds && !source.durationSeconds) {
    db.prepare("UPDATE source_videos SET duration_seconds = ? WHERE id = ?").run(Math.round(durationSeconds), id);
  }
  let metaStatus = "skipped";
  const placeholderTitle = source.title.startsWith("YouTube video ");
  if (source.youtubeVideoId && (!source.channel || placeholderTitle)) {
    const res = await fetchYouTubeMeta(source.youtubeVideoId);
    metaStatus = res.ok ? "updated" : res.reason;
    if (res.ok) {
      db.prepare(
        "UPDATE source_videos SET channel = CASE WHEN channel = '' THEN ? ELSE channel END, title = CASE WHEN title LIKE 'YouTube video %' AND ? != '' THEN ? ELSE title END WHERE id = ?",
      ).run(res.meta.channel, res.meta.title, res.meta.title, id);
    }
  }
  return json({ source: getSource(db, id), metaStatus });
});
