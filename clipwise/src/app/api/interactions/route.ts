import { z } from "zod";
import { json, readJson, route } from "@/lib/server/api";
import { logInteractions } from "@/lib/repo/interactions";
import { INTERACTION_ACTIONS } from "@/lib/types";

const Event = z.object({
  clipId: z.string().min(1).max(100),
  action: z.enum(INTERACTION_ACTIONS),
  watchSeconds: z.number().finite().min(0).max(86_400).nullish(),
  completionRatio: z.number().finite().min(0).max(1).nullish(),
});
const Body = z.union([z.object({ events: z.array(Event).max(200) }), Event]);

export const POST = route(async (req, { db }) => {
  const body = Body.parse(await readJson(req));
  const events = "events" in body ? body.events : [body];
  const logged = logInteractions(db, events);
  return json({ logged });
});
