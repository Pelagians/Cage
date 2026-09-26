import { notFound } from "next/navigation";
import { WatchView } from "@/components/watch/WatchView";
import { ErrorPanel } from "@/components/States";
import { getClipView } from "@/lib/repo/clips";
import { getSettings } from "@/lib/repo/settings";
import { load } from "@/lib/server/load";

export const dynamic = "force-dynamic";

export default async function WatchPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const result = load((db) => ({ clip: getClipView(db, id), settings: getSettings(db) }));
  if (!result.ok) {
    return (
      <div className="page">
        <ErrorPanel title="Couldn't open this clip" message={result.error} />
      </div>
    );
  }
  if (!result.data.clip) notFound();
  return <WatchView initialClip={result.data.clip} autoplay={result.data.settings.autoplayOnWatch} />;
}
