import { SavedView } from "@/components/saved/SavedView";
import { ErrorPanel } from "@/components/States";
import { listSavedClipViews } from "@/lib/repo/clips";
import { load } from "@/lib/server/load";

export const dynamic = "force-dynamic";
export const metadata = { title: "Saved" };

export default function SavedPage() {
  const result = load((db) => listSavedClipViews(db));
  return (
    <div className="page">
      {result.ok ? <SavedView initialClips={result.data} /> : <ErrorPanel message={result.error} />}
    </div>
  );
}
