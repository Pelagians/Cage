/** Best-effort metadata lookup via YouTube's public oEmbed endpoint (no API key). */
import { youTubeWatchUrl } from "../domain/youtube";

export interface VideoMeta {
  title: string;
  channel: string;
  thumbnailUrl: string | null;
}

export type MetaResult = { ok: true; meta: VideoMeta } | { ok: false; reason: "not_found" | "not_embeddable" | "unreachable" };

export async function fetchYouTubeMeta(videoId: string, timeoutMs = 4000): Promise<MetaResult> {
  const url = `https://www.youtube.com/oembed?format=json&url=${encodeURIComponent(youTubeWatchUrl(videoId))}`;
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(timeoutMs), cache: "no-store" });
    if (res.status === 401 || res.status === 403) return { ok: false, reason: "not_embeddable" };
    if (!res.ok) return { ok: false, reason: res.status === 404 || res.status === 400 ? "not_found" : "unreachable" };
    const data = (await res.json()) as { title?: string; author_name?: string; thumbnail_url?: string };
    return {
      ok: true,
      meta: { title: data.title ?? "", channel: data.author_name ?? "", thumbnailUrl: data.thumbnail_url ?? null },
    };
  } catch {
    return { ok: false, reason: "unreachable" };
  }
}
