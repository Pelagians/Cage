import { LibraryView } from "@/components/library/LibraryView";
import { ErrorPanel, PageHeader } from "@/components/States";
import { listSources } from "@/lib/repo/sources";
import { listClipViews } from "@/lib/repo/clips";
import { load } from "@/lib/server/load";

export const dynamic = "force-dynamic";
export const metadata = { title: "Library" };

export default function LibraryPage() {
  const result = load((db) => ({ sources: listSources(db), clips: listClipViews(db) }));
  return (
    <div className="page">
      <PageHeader title="Library" subtitle="Your source videos and the clips cut from them." />
      {result.ok ? <LibraryView sources={result.data.sources} clips={result.data.clips} /> : <ErrorPanel message={result.error} />}
    </div>
  );
}
