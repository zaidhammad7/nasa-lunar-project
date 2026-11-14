import { cx } from '../../lib/format.js'

const STYLE = {
  input: 'border-nogo/50 bg-nogo/10 text-nogo',
  offline: 'border-solar/50 bg-solar/10 text-solar',
  incomplete: 'border-solar/50 bg-solar/10 text-solar',
  unexpected: 'border-nogo/50 bg-nogo/10 text-nogo',
}

/**
 * One clear message for a problem the user can act on: an input outside its allowed range, an unreachable backend, or telemetry
 * that arrived incomplete (lists which fields are missing). `problem` = {kind, title, detail, advice, missing?}.
 */
export default function TelemetryAlert({ problem, onRetry }) {
  if (!problem) return null
  return (
    <div role="alert" className={cx('rounded-xl border p-3 text-[12px] leading-snug', STYLE[problem.kind] || STYLE.unexpected)}>
      <div className="mb-0.5 text-[12.5px] font-semibold">{problem.title}</div>
      {problem.detail && <p className="num break-words text-[11px] text-ink/90">{problem.detail}</p>}
      {problem.missing?.length > 0 && (
        <ul className="num mt-1.5 list-disc pl-4 text-[10.5px] text-mute">{problem.missing.map((m) => <li key={m}>{m}</li>)}</ul>
      )}
      {problem.advice && <p className="mt-1.5 text-[11.5px] text-mute">{problem.advice}</p>}
      {onRetry && <button onClick={onRetry} className="mt-2 rounded-md border border-line px-2.5 py-1 text-[11px] font-semibold text-ink hover:bg-panel2">Retry</button>}
    </div>
  )
}
