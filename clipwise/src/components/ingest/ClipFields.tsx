"use client";

import { formatDuration, parseTimestamp } from "@/lib/domain/time";

export interface ClipFieldValues {
  title: string;
  hook: string;
  summary: string;
  topic: string;
  tags: string;
  start: string;
  end: string;
}

interface Props {
  values: ClipFieldValues;
  errors?: Record<string, string>;
  onChange: (patch: Partial<ClipFieldValues>) => void;
  topics?: string[];
  idPrefix: string;
  compact?: boolean;
}

/** The editable fields of a clip, shared by ingest review, manual creation and edit. */
export function ClipFields({ values, errors = {}, onChange, topics = [], idPrefix, compact }: Props) {
  const start = parseTimestamp(values.start);
  const end = parseTimestamp(values.end);
  const duration = start !== null && end !== null && end > start ? end - start : null;
  const listId = `${idPrefix}-topics`;

  return (
    <div className="space-y-3">
      <Field label="Title" error={errors.title} htmlFor={`${idPrefix}-title`}>
        <input
          id={`${idPrefix}-title`}
          className="field font-semibold"
          value={values.title}
          maxLength={140}
          aria-invalid={!!errors.title}
          onChange={(e) => onChange({ title: e.target.value })}
          placeholder="What's the idea?"
        />
      </Field>
      <Field label="Hook" error={errors.hook} htmlFor={`${idPrefix}-hook`}>
        <textarea
          id={`${idPrefix}-hook`}
          rows={3}
          className="field min-h-[4.5rem] resize-y"
          value={values.hook}
          maxLength={400}
          onChange={(e) => onChange({ hook: e.target.value })}
          placeholder="One or two sentences that make you want to watch."
        />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Start" error={errors.start} htmlFor={`${idPrefix}-start`}>
          <input
            id={`${idPrefix}-start`}
            className="field tabular-nums"
            inputMode="text"
            value={values.start}
            aria-invalid={!!errors.start}
            onChange={(e) => onChange({ start: e.target.value })}
            placeholder="m:ss"
          />
        </Field>
        <Field
          label="End"
          error={errors.end}
          htmlFor={`${idPrefix}-end`}
          hint={duration !== null ? formatDuration(duration) : undefined}
        >
          <input
            id={`${idPrefix}-end`}
            className="field tabular-nums"
            inputMode="text"
            value={values.end}
            aria-invalid={!!errors.end}
            onChange={(e) => onChange({ end: e.target.value })}
            placeholder="m:ss"
          />
        </Field>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Topic" error={errors.topic} htmlFor={`${idPrefix}-topic`}>
          <input
            id={`${idPrefix}-topic`}
            className="field"
            list={listId}
            value={values.topic}
            onChange={(e) => onChange({ topic: e.target.value })}
            placeholder="e.g. Economics"
          />
          <datalist id={listId}>
            {topics.map((t) => (
              <option key={t} value={t} />
            ))}
          </datalist>
        </Field>
        <Field label="Tags" hint="comma separated" htmlFor={`${idPrefix}-tags`}>
          <input
            id={`${idPrefix}-tags`}
            className="field"
            value={values.tags}
            onChange={(e) => onChange({ tags: e.target.value })}
            placeholder="rome, inflation, money"
          />
        </Field>
      </div>
      {!compact || values.summary ? (
        <Field label="Summary" error={errors.summary} htmlFor={`${idPrefix}-summary`}>
          <textarea
            id={`${idPrefix}-summary`}
            className="field min-h-[5rem] resize-y text-sm"
            value={values.summary}
            onChange={(e) => onChange({ summary: e.target.value })}
            placeholder="Optional: what this section covers."
          />
        </Field>
      ) : null}
    </div>
  );
}

function Field({
  label,
  error,
  hint,
  htmlFor,
  children,
}: {
  label: string;
  error?: string;
  hint?: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-xs">
        <label htmlFor={htmlFor} className="font-medium text-white/60">
          {label}
        </label>
        {hint && <span className="text-white/40">{hint}</span>}
      </div>
      {children}
      {error && (
        <p className="mt-1 text-xs text-red-300" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
