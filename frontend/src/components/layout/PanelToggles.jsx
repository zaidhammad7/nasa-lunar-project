import { cx } from '../../lib/format.js'

function Toggle({ on, onClick, title, children }) {
  return (
    <button onClick={onClick} title={`${on ? 'Hide' : 'Show'} ${title}`} aria-pressed={on} aria-label={`${on ? 'Hide' : 'Show'} ${title}`}
      className={cx('glass grid h-8 w-8 place-items-center rounded-lg border text-sm transition-colors', on ? 'border-line text-mute hover:text-ink' : 'border-earth/60 text-earth')}>
      {children}
    </button>
  )
}

/** Tiny corner buttons that hide / show the top bar, the left inputs and the right results (always visible, so nothing gets lost). */
export default function PanelToggles({ panels, onToggle }) {
  return (
    <>
      <div className="absolute left-3 top-3 z-10 flex gap-1.5">
        <Toggle on={panels.left} onClick={() => onToggle('left')} title="inputs panel">◧</Toggle>
        <Toggle on={panels.header} onClick={() => onToggle('header')} title="top bar">⬒</Toggle>
      </div>
      <div className="absolute right-3 top-3 z-10"><Toggle on={panels.right} onClick={() => onToggle('right')} title="results panel">◨</Toggle></div>
    </>
  )
}
