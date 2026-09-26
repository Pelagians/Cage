import Link from "next/link";

export default function NotFound() {
  return (
    <div className="page flex min-h-[70dvh] flex-col items-center justify-center gap-3 text-center">
      <p className="text-xl font-semibold">Not found</p>
      <p className="text-sm text-white/55">That clip or page doesn’t exist (it may have been deleted).</p>
      <Link href="/" className="btn btn-ghost">
        Back to feed
      </Link>
    </div>
  );
}
