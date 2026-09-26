import Link from "next/link";

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body?: string;
  action?: { href: string; label: string };
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-line px-6 py-12 text-center">
      <p className="text-lg font-semibold">{title}</p>
      {body && <p className="max-w-sm text-sm text-white/55">{body}</p>}
      {action && (
        <Link href={action.href} className="btn btn-ghost mt-2">
          {action.label}
        </Link>
      )}
    </div>
  );
}

export function ErrorPanel({ title = "Something went wrong", message }: { title?: string; message: string }) {
  return (
    <div role="alert" className="rounded-2xl border border-red-400/25 bg-red-500/10 px-5 py-4">
      <p className="font-semibold text-red-200">{title}</p>
      <p className="mt-1 text-sm text-red-100/75">{message}</p>
    </div>
  );
}

export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: string; right?: React.ReactNode }) {
  return (
    <header className="mb-5 flex items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-white/50">{subtitle}</p>}
      </div>
      {right}
    </header>
  );
}
