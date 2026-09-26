import { TopicsView } from "@/components/topics/TopicsView";
import { ErrorPanel } from "@/components/States";
import { getProfileSummary } from "@/lib/recommend/service";
import { load } from "@/lib/server/load";

export const dynamic = "force-dynamic";
export const metadata = { title: "Topics" };

export default function TopicsPage() {
  const result = load((db) => getProfileSummary(db));
  return <div className="page">{result.ok ? <TopicsView initial={result.data} /> : <ErrorPanel message={result.error} />}</div>;
}
