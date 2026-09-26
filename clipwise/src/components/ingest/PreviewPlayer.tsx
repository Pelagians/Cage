"use client";

import { useState } from "react";
import { formatTimestamp } from "@/lib/domain/time";
import { YouTubePlayer } from "../player/YouTubePlayer";
import { CloseIcon } from "../icons";

/** One inline player for checking timestamps while reviewing/creating clips. */
export function PreviewPlayer({
  videoId,
  start,
  end,
  onClose,
}: {
  videoId: string;
  start: number;
  end: number;
  onClose: () => void;
}) {
  const [status, setStatus] = useState<"loading" | "playing" | "done" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-black" data-testid="preview-player">
      <div className="relative aspect-video">
        <YouTubePlayer
          key={videoId}
          videoId={videoId}
          startSeconds={start}
          endSeconds={end}
          boundaryActive
          autoplay
          onPlayingChange={(p) => p && setStatus("playing")}
          onSegmentEnd={() => setStatus("done")}
          onError={(msg) => {
            setStatus("error");
            setError(msg);
          }}
          className="absolute inset-0 [&_iframe]:h-full [&_iframe]:w-full"
        />
        {error && <div className="absolute inset-0 flex items-center justify-center bg-black/90 p-4 text-center text-sm text-white/70">{error}</div>}
      </div>
      <div className="flex items-center justify-between px-3 py-2 text-xs text-white/55">
        <span className="tabular-nums">
          Preview {formatTimestamp(start)}–{formatTimestamp(end)}
          {status === "done" ? " · reached end" : ""}
        </span>
        <button type="button" onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-full hover:bg-white/10" aria-label="Close preview">
          <CloseIcon size={16} />
        </button>
      </div>
    </div>
  );
}
