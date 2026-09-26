/**
 * Timestamp parsing/formatting. Pure functions, shared by client and server.
 */

const COLON_RE = /^(\d{1,3}):(\d{1,2})(?::(\d{1,2}))?(?:[.,](\d{1,3}))?$/;
const UNIT_RE = /^(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+(?:\.\d+)?)s?)?$/i;

/**
 * Parse a human timestamp into seconds.
 *
 * Accepts: "1:25", "01:25", "1:02:11", "00:01:25,500", "00:01:25.5", "85", "85s",
 * "1m25s", "1h2m11s". Returns null for anything malformed or negative.
 */
export function parseTimestamp(input: string | null | undefined): number | null {
  if (input == null) return null;
  const raw = String(input).trim();
  if (!raw) return null;

  const colon = COLON_RE.exec(raw);
  if (colon) {
    const [, a, b, c, frac] = colon;
    let h = 0;
    let m: number;
    let s: number;
    if (c !== undefined) {
      h = Number(a);
      m = Number(b);
      s = Number(c);
      if (m >= 60) return null;
    } else {
      m = Number(a);
      s = Number(b);
    }
    if (s >= 60) return null;
    const fraction = frac ? Number(`0.${frac}`) : 0;
    return h * 3600 + m * 60 + s + fraction;
  }

  if (/^\d+(?:\.\d+)?$/.test(raw)) return Number(raw);

  const unit = UNIT_RE.exec(raw);
  if (unit && (unit[1] || unit[2] || unit[3]) && /[hms]/i.test(raw)) {
    const h = Number(unit[1] ?? 0);
    const m = Number(unit[2] ?? 0);
    const s = Number(unit[3] ?? 0);
    return h * 3600 + m * 60 + s;
  }
  return null;
}

/** 85 -> "1:25", 3731 -> "1:02:11". Fractions are floored. */
export function formatTimestamp(totalSeconds: number): string {
  const t = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = t % 60;
  const ss = String(s).padStart(2, "0");
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${ss}`;
  return `${m}:${ss}`;
}

/** 134 -> "2m 14s", 45 -> "45s", 3720 -> "1h 2m". */
export function formatDuration(totalSeconds: number): string {
  const t = Math.max(0, Math.round(totalSeconds));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = t % 60;
  if (h > 0) return m > 0 ? `${h}h ${m}m` : `${h}h`;
  if (m > 0) return s > 0 ? `${m}m ${s}s` : `${m}m`;
  return `${s}s`;
}
