/**
 * YouTube URL helpers. We never download or modify videos; we only need the ID
 * to drive the official embedded player.
 */

const ID_RE = /^[A-Za-z0-9_-]{11}$/;

export function isValidYouTubeId(id: string | null | undefined): id is string {
  return typeof id === "string" && ID_RE.test(id);
}

const YT_HOSTS = new Set([
  "youtube.com",
  "www.youtube.com",
  "m.youtube.com",
  "music.youtube.com",
  "youtube-nocookie.com",
  "www.youtube-nocookie.com",
  "youtu.be",
  "www.youtu.be",
]);

/**
 * Extract an 11-character video ID from common YouTube URL shapes:
 *   youtube.com/watch?v=ID, youtu.be/ID, youtube.com/embed/ID, youtube.com/shorts/ID,
 *   youtube.com/live/ID, youtube.com/v/ID, m.youtube.com/..., youtube-nocookie.com/embed/ID,
 *   or a bare ID.
 */
export function extractYouTubeId(input: string | null | undefined): string | null {
  if (!input) return null;
  const raw = input.trim();
  if (isValidYouTubeId(raw)) return raw;

  let url: URL;
  try {
    url = new URL(/^https?:\/\//i.test(raw) ? raw : `https://${raw}`);
  } catch {
    return null;
  }
  const host = url.hostname.toLowerCase();
  if (!YT_HOSTS.has(host)) return null;

  if (host.endsWith("youtu.be")) {
    const id = url.pathname.split("/").filter(Boolean)[0];
    return isValidYouTubeId(id) ? id : null;
  }

  const v = url.searchParams.get("v");
  if (url.pathname === "/watch" || url.pathname === "/watch/") {
    return isValidYouTubeId(v) ? v : null;
  }

  const parts = url.pathname.split("/").filter(Boolean);
  if (parts.length >= 2 && ["embed", "shorts", "live", "v", "e"].includes(parts[0]!)) {
    return isValidYouTubeId(parts[1]) ? parts[1]! : null;
  }
  return isValidYouTubeId(v) ? v : null;
}

/** Start time embedded in a URL (?t=90, ?t=1m30s, ?start=90), if any. */
export function extractStartFromUrl(input: string): number | null {
  try {
    const url = new URL(/^https?:\/\//i.test(input.trim()) ? input.trim() : `https://${input.trim()}`);
    const t = url.searchParams.get("t") ?? url.searchParams.get("start");
    if (!t) return null;
    if (/^\d+$/.test(t)) return Number(t);
    const m = /^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/.exec(t);
    if (!m || !(m[1] || m[2] || m[3])) return null;
    return Number(m[1] ?? 0) * 3600 + Number(m[2] ?? 0) * 60 + Number(m[3] ?? 0);
  } catch {
    return null;
  }
}

export function youTubeWatchUrl(id: string, startSeconds?: number): string {
  const t = startSeconds && startSeconds > 0 ? `&t=${Math.floor(startSeconds)}s` : "";
  return `https://www.youtube.com/watch?v=${id}${t}`;
}

export function youTubeThumbnailUrl(id: string): string {
  return `https://i.ytimg.com/vi/${id}/hqdefault.jpg`;
}

/** Human-readable explanation of IFrame API error codes. */
export function describePlayerError(code: number): string {
  switch (code) {
    case 2:
      return "YouTube rejected the video ID or start parameters.";
    case 5:
      return "This video can't be played in the embedded HTML5 player.";
    case 100:
      return "This video was removed or made private.";
    case 101:
    case 150:
    case 153:
      return "The owner doesn't allow this video to be embedded in other apps.";
    default:
      return "YouTube couldn't play this video.";
  }
}
