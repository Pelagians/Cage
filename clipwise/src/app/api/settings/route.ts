import { z } from "zod";
import { json, readJson, route } from "@/lib/server/api";
import { getSettings, updateSettings } from "@/lib/repo/settings";

export const dynamic = "force-dynamic";

const Patch = z.object({
  explorationRate: z.number().min(0).max(0.5).optional(),
  autoplayOnWatch: z.boolean().optional(),
  ai: z
    .object({
      enabled: z.boolean(),
      provider: z.enum(["ollama", "openai-compatible"]),
      endpoint: z.string().trim().max(300).refine((v) => v === "" || /^https?:\/\/[^\s]+$/i.test(v), "Endpoint must start with http:// or https://"),
      model: z.string().trim().max(120),
    })
    .optional(),
});

export const GET = route(async (_req, { db }) => json({ settings: getSettings(db) }));

export const PUT = route(async (req, { db }) => {
  const patch = Patch.parse(await readJson(req));
  return json({ settings: updateSettings(db, patch) });
});
