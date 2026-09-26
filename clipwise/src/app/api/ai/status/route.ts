import { json, route } from "@/lib/server/api";
import { getSettings } from "@/lib/repo/settings";
import { createLlmClient } from "@/lib/ingest/providers/llm";

export const dynamic = "force-dynamic";

export const GET = route(async (_req, { db }) => {
  const settings = getSettings(db);
  const client = createLlmClient(settings.ai);
  if (!client) return json({ enabled: false, reachable: false, label: "Heuristics only" });
  return json({ enabled: true, reachable: await client.ping(2500), label: client.label });
});
