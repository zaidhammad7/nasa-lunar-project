import { cx } from '../../lib/format.js'

const VIEWS = [
  { kind: 'overview', label: 'South Pole View' },
  { kind: 'tower', label: 'Pin Close-Up' },
  { kind: 'sunearth', label: 'Earth–Sun Alignment' },
]

/** The only control floating over the 3-D scene: a compact camera-view switcher at the top centre. */
export default function CameraPill({ active, onPreset }) {
  return (
    <div className="glass absolute left-1/2 top-3 z-10 flex -translate-x-1/2 gap-0.5 rounded-full border border-line p-1 shadow-lg">
      {VIEWS.map((v) => (
        <button key={v.kind} onClick={() => onPreset(v.kind)}
          className={cx('whitespace-nowrap rounded-full px-3 py-1 text-[11.5px] font-medium transition-colors', active === v.kind ? 'bg-earth/20 text-earth' : 'text-mute hover:bg-panel2 hover:text-ink')}>
          {v.label}
        </button>
      ))}
    </div>
  )
}
