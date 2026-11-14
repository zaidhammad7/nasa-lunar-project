import { useId } from 'react'

/**
 * Small "i" marker that explains a metric in plain language. Opens on hover and on keyboard focus (tab to it), and the text is
 * also exposed to screen readers through aria-describedby.
 */
export default function InfoTip({ text, className = '' }) {
  const id = useId()
  return (
    <span className={`group relative inline-flex align-middle ${className}`}>
      <button type="button" aria-describedby={id} aria-label="What does this mean?"
        className="grid h-3.5 w-3.5 cursor-help place-items-center rounded-full border border-mute/60 text-[9px] font-bold leading-none text-mute transition-colors hover:border-earth hover:text-earth focus:border-earth focus:text-earth focus:outline-none">i</button>
      <span id={id} role="tooltip"
        className="pointer-events-none invisible absolute bottom-full left-1/2 z-50 mb-1.5 w-60 -translate-x-1/2 rounded-lg border border-line bg-panel2 px-2.5 py-2 text-left text-[11px] font-normal normal-case leading-snug tracking-normal text-ink opacity-0 shadow-xl transition-opacity group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100">
        {text}
      </span>
    </span>
  )
}
