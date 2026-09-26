"use client";

import Link from "next/link";
import { useState } from "react";
import type { AiSettings, AppSettings } from "@/lib/types";
import { api, ApiError } from "@/lib/client/api";
import { sessionStore } from "@/lib/client/session";
import { useToast } from "../Toast";
import { PageHeader } from "../States";
import { LibraryIcon } from "../icons";

export function SettingsView({ initial, dbPath }: { initial: AppSettings; dbPath: string }) {
  const toast = useToast();
  const [settings, setSettings] = useState(initial);
  const [ai, setAi] = useState<AiSettings>(initial.ai);
  const [aiStatus, setAiStatus] = useState<string | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);

  const save = async (patch: Partial<AppSettings>, message = "Saved") => {
    try {
      const res = await api<{ settings: AppSettings }>("/api/settings", { method: "PUT", body: patch });
      setSettings(res.settings);
      toast(message);
      return true;
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't save settings");
      return false;
    }
  };

  const clearFeedCache = () => sessionStore.write("clipwise.feed", null);

  const danger = async (path: string, confirmText: string, done: string) => {
    if (!window.confirm(confirmText)) return;
    try {
      await api(path, { body: {} });
      clearFeedCache();
      toast(done);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Something went wrong");
    }
  };

  const saveAi = async () => {
    setAiError(null);
    try {
      const res = await api<{ settings: AppSettings }>("/api/settings", { method: "PUT", body: { ai } });
      setSettings(res.settings);
      const status = await api<{ enabled: boolean; reachable: boolean; label: string }>("/api/ai/status");
      setAiStatus(!status.enabled ? "AI off: using built-in heuristics." : status.reachable ? `Connected: ${status.label}` : `${status.label} isn't reachable. Heuristics will be used.`);
    } catch (err) {
      if (err instanceof ApiError && Object.keys(err.fields).length) setAiError(Object.values(err.fields)[0]!);
      else setAiError(err instanceof ApiError ? err.message : "Couldn't save");
    }
  };

  const pct = Math.round(settings.explorationRate * 100);

  return (
    <>
      <PageHeader title="Settings" subtitle="Everything stays on this computer." />

      <Section title="Feed">
        <label className="block">
          <div className="flex items-baseline justify-between">
            <span className="font-medium">Exploration</span>
            <span className="text-sm tabular-nums text-white/60">{pct}% of the feed</span>
          </div>
          <input
            type="range"
            min={0}
            max={50}
            step={5}
            value={pct}
            onChange={(e) => setSettings((s) => ({ ...s, explorationRate: Number(e.target.value) / 100 }))}
            onPointerUp={() => void save({ explorationRate: settings.explorationRate }, "Exploration updated")}
            onKeyUp={() => void save({ explorationRate: settings.explorationRate }, "Exploration updated")}
            className="mt-3 w-full accent-[var(--color-accent)]"
            aria-label="Exploration percentage"
          />
          <p className="mt-1 text-xs text-white/45">Share of slots reserved for topics outside your preferences, so the feed never becomes a bubble.</p>
        </label>
        <Toggle
          label="Autoplay on Watch"
          description="Start the segment as soon as Watch opens. Some mobile browsers block this; tap the video if so."
          checked={settings.autoplayOnWatch}
          onChange={(v) => void save({ autoplayOnWatch: v })}
        />
      </Section>

      <Section title="Library">
        <Link href="/library" className="flex items-center justify-between rounded-xl bg-white/5 px-4 py-3 hover:bg-white/8">
          <span className="flex items-center gap-2 font-medium">
            <LibraryIcon size={18} /> Videos & clips
          </span>
          <span className="text-white/40">›</span>
        </Link>
        <p className="text-xs text-white/40">
          Database: <code className="break-all text-white/60">{dbPath}</code>
        </p>
      </Section>

      <Section title="Optional AI enrichment">
        <p className="text-sm text-white/55">
          Improves titles, hooks and summaries during transcript ingest. Optional: without it, built-in heuristics are used. Works with a local{" "}
          <a className="underline" href="https://ollama.com" target="_blank" rel="noreferrer">
            Ollama
          </a>{" "}
          or any OpenAI-compatible endpoint (an API key, if one is needed, goes in the <code>CLIPWISE_AI_API_KEY</code> environment variable).
        </p>
        <Toggle label="Use AI during ingest" checked={ai.enabled} onChange={(v) => setAi((a) => ({ ...a, enabled: v }))} />
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="mb-1 block text-white/60">Provider</span>
            <select className="field" value={ai.provider} onChange={(e) => setAi((a) => ({ ...a, provider: e.target.value as AiSettings["provider"] }))}>
              <option value="ollama">Ollama</option>
              <option value="openai-compatible">OpenAI-compatible</option>
            </select>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-white/60">Model</span>
            <input className="field" value={ai.model} onChange={(e) => setAi((a) => ({ ...a, model: e.target.value }))} placeholder="llama3.1:8b" />
          </label>
        </div>
        <label className="block text-sm">
          <span className="mb-1 block text-white/60">Endpoint</span>
          <input
            className="field"
            value={ai.endpoint}
            aria-invalid={!!aiError}
            onChange={(e) => setAi((a) => ({ ...a, endpoint: e.target.value }))}
            placeholder={ai.provider === "ollama" ? "http://127.0.0.1:11434" : "http://127.0.0.1:1234/v1"}
          />
        </label>
        {aiError && <p className="text-sm text-red-300">{aiError}</p>}
        {aiStatus && <p className="text-sm text-white/60">{aiStatus}</p>}
        <button type="button" className="btn btn-ghost" onClick={() => void saveAi()}>
          Save & test connection
        </button>
      </Section>

      <Section title="Data">
        <div className="flex flex-col gap-2">
          <button
            type="button"
            className="btn btn-ghost justify-start"
            onClick={() => void danger("/api/preferences/reset", "Reset learned preferences? History and saved clips are kept.", "Preferences reset")}
          >
            Reset recommendations
          </button>
          <button
            type="button"
            className="btn btn-ghost justify-start"
            onClick={() => void danger("/api/admin/clear-history", "Delete all watch history, impressions and More/Less feedback? Saved clips are kept.", "History cleared")}
          >
            Clear history
          </button>
          <button
            type="button"
            className="btn btn-danger justify-start"
            onClick={() =>
              void danger(
                "/api/admin/reset-demo",
                "Reset the whole database to the demo content? This deletes your own videos, clips, saves and history.",
                "Database reset to demo content",
              )
            }
          >
            Reset demo database
          </button>
        </div>
      </Section>
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-5 space-y-4 rounded-2xl bg-panel p-4">
      <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-white/45">{title}</h2>
      {children}
    </section>
  );
}

function Toggle({ label, description, checked, onChange }: { label: string; description?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-4">
      <span>
        <span className="block font-medium">{label}</span>
        {description && <span className="mt-0.5 block text-xs text-white/45">{description}</span>}
      </span>
      <input type="checkbox" role="switch" className="peer sr-only" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span
        aria-hidden
        className="relative mt-0.5 h-7 w-12 shrink-0 rounded-full bg-white/15 transition peer-checked:bg-accent peer-focus-visible:ring-2 peer-focus-visible:ring-white/60 after:absolute after:left-1 after:top-1 after:h-5 after:w-5 after:rounded-full after:bg-white after:transition peer-checked:after:translate-x-5"
      />
    </label>
  );
}
