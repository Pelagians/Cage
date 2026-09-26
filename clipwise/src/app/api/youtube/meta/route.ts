import { HttpError, json, route } from "@/lib/server/api";
import { extractStartFromUrl, extractYouTubeId } from "@/lib/domain/youtube";
import { fetchYouTubeMeta } from "@/lib/server/oembed";
import { getSourceByYouTubeId } from "@/lib/repo/sources";

export const dynamic = "force-dynamic";

/** Validate a pasted URL and look up title/channel. Works offline too (returns just the ID). */
export const GET = route(async (req, { db }) => {
  const url = req.nextUrl.searchParams.get("url") ?? "";
  const videoId = extractYouTubeId(url);
  if (!videoId) throw new HttpError(400, "That doesn't look like a YouTube video URL.");
  const existing = getSourceByYouTubeId(db, videoId);
  const res = await fetchYouTubeMeta(videoId);
  return json({
    videoId,
    startSeconds: extractStartFromUrl(url),
    existingSourceId: existing?.id ?? null,
    meta: res.ok ? res.meta : null,
    status: res.ok ? "ok" : res.reason,
  });
});
