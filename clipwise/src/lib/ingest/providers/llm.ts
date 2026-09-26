/**
 * Optional AI providers. Nothing here is required: when disabled or unreachable,
 * the heuristic pipeline is used instead.
 */
import type { AiSettings } from "../../types";

export interface LlmClient {
  readonly label: string;
  /** Ask for a JSON object. Throws on network/format errors. */
  completeJson(prompt: string, timeoutMs?: number): Promise<unknown>;
  /** Cheap reachability check. */
  ping(timeoutMs?: number): Promise<boolean>;
}

function withTimeout(ms: number): AbortSignal {
  return AbortSignal.timeout(ms);
}

function baseUrl(endpoint: string): string {
  const url = new URL(endpoint); // throws on garbage
  if (url.protocol !== "http:" && url.protocol !== "https:") throw new Error("AI endpoint must be http(s).");
  return url.toString().replace(/\/+$/, "");
}

function parseJsonText(text: string): unknown {
  const trimmed = text.trim().replace(/^```(?:json)?\s*/i, "").replace(/```$/, "");
  const start = trimmed.indexOf("{");
  const end = trimmed.lastIndexOf("}");
  if (start < 0 || end < start) throw new Error("Model did not return JSON.");
  return JSON.parse(trimmed.slice(start, end + 1));
}

export class OllamaClient implements LlmClient {
  readonly label: string;
  private readonly base: string;
  constructor(endpoint: string, private readonly model: string) {
    this.base = baseUrl(endpoint);
    this.label = `Ollama (${model})`;
  }
  async completeJson(prompt: string, timeoutMs = 45_000): Promise<unknown> {
    const res = await fetch(`${this.base}/api/generate`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ model: this.model, prompt, stream: false, format: "json", options: { temperature: 0.2 } }),
      signal: withTimeout(timeoutMs),
    });
    if (!res.ok) throw new Error(`Ollama responded ${res.status}`);
    const data = (await res.json()) as { response?: string };
    return parseJsonText(data.response ?? "");
  }
  async ping(timeoutMs = 1500): Promise<boolean> {
    try {
      const res = await fetch(`${this.base}/api/tags`, { signal: withTimeout(timeoutMs) });
      return res.ok;
    } catch {
      return false;
    }
  }
}

export class OpenAICompatibleClient implements LlmClient {
  readonly label: string;
  private readonly base: string;
  constructor(endpoint: string, private readonly model: string, private readonly apiKey?: string) {
    this.base = baseUrl(endpoint);
    this.label = `OpenAI-compatible (${model})`;
  }
  private headers() {
    const h: Record<string, string> = { "content-type": "application/json" };
    if (this.apiKey) h.authorization = `Bearer ${this.apiKey}`;
    return h;
  }
  async completeJson(prompt: string, timeoutMs = 45_000): Promise<unknown> {
    const res = await fetch(`${this.base}/chat/completions`, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify({
        model: this.model,
        temperature: 0.2,
        response_format: { type: "json_object" },
        messages: [
          { role: "system", content: "You reply with a single JSON object and nothing else." },
          { role: "user", content: prompt },
        ],
      }),
      signal: withTimeout(timeoutMs),
    });
    if (!res.ok) throw new Error(`AI endpoint responded ${res.status}`);
    const data = (await res.json()) as { choices?: { message?: { content?: string } }[] };
    return parseJsonText(data.choices?.[0]?.message?.content ?? "");
  }
  async ping(timeoutMs = 1500): Promise<boolean> {
    try {
      const res = await fetch(`${this.base}/models`, { headers: this.headers(), signal: withTimeout(timeoutMs) });
      return res.ok;
    } catch {
      return false;
    }
  }
}

/** Build a client from settings, or null when AI is disabled/misconfigured. */
export function createLlmClient(ai: AiSettings | null | undefined): LlmClient | null {
  if (!ai?.enabled || !ai.endpoint || !ai.model) return null;
  try {
    return ai.provider === "openai-compatible"
      ? new OpenAICompatibleClient(ai.endpoint, ai.model, process.env.CLIPWISE_AI_API_KEY)
      : new OllamaClient(ai.endpoint, ai.model);
  } catch {
    return null;
  }
}
