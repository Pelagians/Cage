/** Shared domain types (safe to import from client components). */

export const INTERACTION_ACTIONS = [
  "impression",
  "opened",
  "completed",
  "skipped",
  "saved",
  "unsaved",
  "more_like_this",
  "less_like_this",
  "continued_original",
] as const;
export type InteractionAction = (typeof INTERACTION_ACTIONS)[number];

/** "youtube" plays through the embedded player; "local" is a seam for future user-owned media. */
export type MediaKind = "youtube" | "local";
export type ClipOrigin = "seed" | "manual" | "ingest";

export interface SourceVideo {
  id: string;
  mediaKind: MediaKind;
  youtubeVideoId: string | null;
  title: string;
  channel: string;
  sourceUrl: string;
  thumbnailUrl: string | null;
  durationSeconds: number | null;
  description: string;
  isDemo: boolean;
  createdAt: string;
}

export interface KnowledgeClip {
  id: string;
  sourceVideoId: string;
  title: string;
  hook: string;
  summary: string;
  topic: string;
  tags: string[];
  startSeconds: number;
  endSeconds: number;
  durationSeconds: number;
  /** 0..1 editorial quality prior. */
  qualityScore: number;
  relatedClipIds: string[];
  origin: ClipOrigin;
  /** False for demo clips whose timestamps were estimated rather than checked against the video. */
  timestampsVerified: boolean;
  createdAt: string;
}

export interface ClipSourceSummary {
  id: string;
  mediaKind: MediaKind;
  youtubeVideoId: string | null;
  title: string;
  channel: string;
  thumbnailUrl: string | null;
  sourceUrl: string;
}

/** What the UI renders: a clip plus the bits of its source it needs. */
export interface ClipView extends KnowledgeClip {
  source: ClipSourceSummary;
  saved: boolean;
}

export interface UserInteraction {
  id: number;
  clipId: string;
  action: InteractionAction;
  watchSeconds: number | null;
  completionRatio: number | null;
  createdAt: string;
}

export interface AiSettings {
  enabled: boolean;
  provider: "ollama" | "openai-compatible";
  endpoint: string;
  model: string;
}

export interface AppSettings {
  /** Share of feed slots reserved for exploration, 0..0.5. */
  explorationRate: number;
  autoplayOnWatch: boolean;
  /** ISO time; interactions before this are ignored by the preference profile. */
  preferencesResetAt: string | null;
  ai: AiSettings;
}

export const DEFAULT_SETTINGS: AppSettings = {
  explorationRate: 0.25,
  autoplayOnWatch: true,
  preferencesResetAt: null,
  ai: {
    enabled: false,
    provider: "ollama",
    endpoint: "http://127.0.0.1:11434",
    model: "llama3.1:8b",
  },
};
