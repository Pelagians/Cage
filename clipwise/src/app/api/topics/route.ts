import { json, route } from "@/lib/server/api";
import { getProfileSummary } from "@/lib/recommend/service";

export const dynamic = "force-dynamic";

export const GET = route(async (_req, { db }) => json(getProfileSummary(db)));
