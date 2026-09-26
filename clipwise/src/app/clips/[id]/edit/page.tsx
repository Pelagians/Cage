import { notFound } from "next/navigation";
import { ManualClipForm } from "@/components/ingest/ManualClipForm";
import { ErrorPanel, PageHeader } from "@/components/States";
import { getClipView } from "@/lib/repo/clips";
import { load } from "@/lib/server/load";
import { sourceOptions, topicOptions } from "@/lib/server/options";

export const dynamic = "force-dynamic";
export const metadata = { title: "Edit clip" };

export default async function EditClipPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const result = load((db) => ({ clip: getClipView(db, id), sources: sourceOptions(db), topics: topicOptions(db) }));
  if (result.ok && !result.data.clip) notFound();
  return (
    <div className="page">
      <PageHeader title="Edit clip" subtitle="Adjust the timestamps with Preview until the clip starts and ends cleanly." />
      {result.ok ? (
        <ManualClipForm sources={result.data.sources} topics={result.data.topics} editClip={result.data.clip!} />
      ) : (
        <ErrorPanel message={result.error} />
      )}
    </div>
  );
}
