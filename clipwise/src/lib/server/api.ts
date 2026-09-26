/** Route-handler helpers: consistent JSON errors, no stack traces leaked to the UI. */
import { NextResponse, type NextRequest } from "next/server";
import { ZodError } from "zod";
import { DatabaseInitError, getDb, type DB } from "../db/client";
import { InputError } from "../repo/sources";
import { TranscriptParseError } from "../ingest/transcript";

export class HttpError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
  }
}

export function json<T>(data: T, status = 200) {
  return NextResponse.json(data, { status, headers: { "cache-control": "no-store" } });
}

/**
 * Reject cross-site mutations. The app has no accounts, so this is what stops an
 * arbitrary web page from POSTing to localhost:3000 (e.g. to wipe your data).
 */
function assertSameOrigin(req: NextRequest) {
  if (req.method === "GET" || req.method === "HEAD") return;
  const origin = req.headers.get("origin");
  const host = req.headers.get("x-forwarded-host") ?? req.headers.get("host");
  if (origin) {
    let originHost: string;
    try {
      originHost = new URL(origin).host;
    } catch {
      throw new HttpError(403, "Cross-site request blocked.");
    }
    if (originHost !== host) throw new HttpError(403, "Cross-site request blocked.");
  }
  const type = req.headers.get("content-type") ?? "";
  if (req.headers.get("content-length") !== "0" && !type.includes("application/json")) {
    throw new HttpError(415, "Requests must be JSON.");
  }
}

type Handler<C> = (req: NextRequest, ctx: C & { db: DB }) => Promise<Response> | Response;

export function route<C = object>(handler: Handler<C>) {
  return async (req: NextRequest, ctx: C) => {
    try {
      assertSameOrigin(req);
      const db = getDb();
      return await handler(req, { ...ctx, db });
    } catch (err) {
      return errorResponse(err);
    }
  };
}

export function errorResponse(err: unknown) {
  if (err instanceof HttpError) return json({ error: err.message }, err.status);
  if (err instanceof InputError) return json({ error: err.message, fields: err.fields }, 400);
  if (err instanceof TranscriptParseError) return json({ error: err.message, fields: { transcript: err.message } }, 422);
  if (err instanceof ZodError) {
    const fields: Record<string, string> = {};
    for (const issue of err.issues) fields[issue.path.join(".") || "body"] = issue.message;
    return json({ error: "Some fields are invalid.", fields }, 400);
  }
  if (err instanceof DatabaseInitError) return json({ error: err.message }, 503);
  if (err instanceof SyntaxError) return json({ error: "Request body isn't valid JSON." }, 400);
  console.error("[clipwise] unexpected API error", err);
  return json({ error: "Something went wrong on the local server. Check the terminal for details." }, 500);
}

export async function readJson(req: NextRequest): Promise<unknown> {
  const text = await req.text();
  if (!text) return {};
  return JSON.parse(text);
}

export function idList(value: string | null): string[] {
  return value ? value.split(",").map((s) => s.trim()).filter(Boolean).slice(0, 500) : [];
}
