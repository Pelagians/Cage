import Link from "next/link";
import { TranscriptIngest } from "@/components/ingest/TranscriptIngest";
import { ManualClipForm } from "@/components/ingest/ManualClipForm";
import { ErrorPanel, PageHeader } from "@/components/States";
import { LibraryIcon } from "@/components/icons";
import { load } from "@/lib/server/load";
import { sourceOptions, topicOptions } from "@/lib/server/options";

export const dynamic = "force-dynamic";
export const metadata = { title: "Add" };

export default async function IngestPage({ searchParams }: { searchParams: Promise<{ tab?: string; source?: string }> }) {
  const { tab, source } = await searchParams;
  const manual = tab === "manual";
  const result = load((db) => ({ sources: sourceOptions(db), topics: topicOptions(db) }));

  return (
    <div className="page">
      <PageHeader
        title="Add clips"
        subtitle="Turn sections of a YouTube video into clips."
        right={
          <Link href="/library" className="btn btn-ghost h-10 min-h-0 px-3 text-sm">
            <LibraryIcon size={16} /> Library
          </Link>
        }
      />
      <div role="tablist" className="mb-5 grid grid-cols-2 gap-1 rounded-full bg-panel p-1">
        <Link role="tab" aria-selected={!manual} href="/ingest" className={`rounded-full py-2 text-center text-sm font-semibold ${!manual ? "bg-white text-black" : "text-white/60"}`}>
          From transcript
        </Link>
        <Link role="tab" aria-selected={manual} href="/ingest?tab=manual" className={`rounded-full py-2 text-center text-sm font-semibold ${manual ? "bg-white text-black" : "text-white/60"}`}>
          Manual clip
        </Link>
      </div>
      {!result.ok ? (
        <ErrorPanel message={result.error} />
      ) : manual ? (
        <ManualClipForm sources={result.data.sources} topics={result.data.topics} defaultSourceId={source} />
      ) : (
        <TranscriptIngest topics={result.data.topics} />
      )}
    </div>
  );
}
