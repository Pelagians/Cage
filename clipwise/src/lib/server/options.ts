import type { DB } from "../db/client";
import { listSources } from "../repo/sources";
import type { SourceOption } from "@/components/ingest/ManualClipForm";

export function sourceOptions(db: DB): SourceOption[] {
  return listSources(db).map((s) => ({
    id: s.id,
    title: s.title,
    channel: s.channel,
    youtubeVideoId: s.youtubeVideoId,
    durationSeconds: s.durationSeconds,
  }));
}

export function topicOptions(db: DB): string[] {
  return (db.prepare("SELECT DISTINCT topic FROM knowledge_clips ORDER BY topic").all() as { topic: string }[]).map((r) => r.topic);
}
