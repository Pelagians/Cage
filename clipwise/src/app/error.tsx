"use client";

export default function GlobalError({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="page">
      <div role="alert" className="rounded-2xl border border-red-400/25 bg-red-500/10 px-5 py-4">
        <p className="font-semibold text-red-200">Something went wrong</p>
        <p className="mt-1 text-sm text-red-100/75">
          This screen hit an unexpected error. Details are in the terminal running the app.
        </p>
        <button type="button" onClick={reset} className="btn btn-ghost mt-3">
          Try again
        </button>
      </div>
    </div>
  );
}
