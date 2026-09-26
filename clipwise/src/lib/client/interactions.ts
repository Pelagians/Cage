"use client";
import type { InteractionAction } from "../types";
import { api } from "./api";

interface Pending {
  clipId: string;
  action: InteractionAction;
  watchSeconds?: number | null;
  completionRatio?: number | null;
}

let queue: Pending[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;

/** Send one interaction now. */
export function track(event: Pending): Promise<unknown> {
  return api("/api/interactions", { body: event }).catch(() => undefined);
}

/** Queue low-priority events (impressions) and send them in batches. */
export function trackLater(event: Pending) {
  queue.push(event);
  if (!timer) timer = setTimeout(flush, 2500);
}

export function flush() {
  if (timer) clearTimeout(timer);
  timer = null;
  if (!queue.length) return;
  const events = queue;
  queue = [];
  void api("/api/interactions", { body: { events }, keepalive: true }).catch(() => undefined);
}

if (typeof window !== "undefined") {
  window.addEventListener("pagehide", flush);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush();
  });
}
