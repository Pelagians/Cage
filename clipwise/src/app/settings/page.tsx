import { SettingsView } from "@/components/settings/SettingsView";
import { ErrorPanel } from "@/components/States";
import { getSettings } from "@/lib/repo/settings";
import { load } from "@/lib/server/load";
import { resolveDbPath } from "@/lib/db/client";

export const dynamic = "force-dynamic";
export const metadata = { title: "Settings" };

export default function SettingsPage() {
  const result = load((db) => getSettings(db));
  return (
    <div className="page">
      {result.ok ? <SettingsView initial={result.data} dbPath={resolveDbPath()} /> : <ErrorPanel message={result.error} />}
    </div>
  );
}
