"use client";
/** Per-tab session memory (feed position, clips seen) via sessionStorage, failure-tolerant. */

function read<T>(key: string): T | null {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function write(key: string, value: unknown) {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // storage full or unavailable: not critical
  }
}

const SEEN = "clipwise.seen";
export const FEED_KEY = "clipwise.feed";

/** Forget the cached feed so the next visit re-ranks from the server. */
export function clearFeedCache() {
  write(FEED_KEY, null);
}

export function markSeen(id: string) {
  const seen = read<string[]>(SEEN) ?? [];
  if (!seen.includes(id)) write(SEEN, [...seen, id].slice(-200));
}

export function getSeen(): string[] {
  return read<string[]>(SEEN) ?? [];
}

export const sessionStore = { read, write };
