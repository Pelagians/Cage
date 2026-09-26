import { FeedView } from "@/components/feed/FeedView";
import { ErrorPanel } from "@/components/States";
import { getFeed } from "@/lib/recommend/service";
import { load } from "@/lib/server/load";

export const dynamic = "force-dynamic";

export default function FeedPage() {
  const result = load((db) => getFeed(db));
  if (!result.ok) {
    return (
      <div className="page">
        <ErrorPanel title="Couldn't load your feed" message={result.error} />
      </div>
    );
  }
  return <FeedView initialClips={result.data} />;
}
