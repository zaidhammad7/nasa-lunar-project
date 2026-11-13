/** Left sidebar action row: open the Site A vs Site B comparison and export the full mission CSV. */
export default function ActionButtons({ onCompare, onExport, disabled }) {
  return (
    <div className="grid grid-cols-2 gap-2">
      <button onClick={onCompare}
        className="rounded-xl border border-scenb/60 bg-scenb/15 px-3 py-2.5 text-[12.5px] font-semibold text-scenb transition-colors hover:bg-scenb/25">⇄ Compare 2 Sites</button>
      <button onClick={onExport} disabled={disabled}
        className="rounded-xl border border-go/70 bg-gradient-to-r from-go/30 to-earth/25 px-3 py-2.5 text-[12.5px] font-bold text-ink shadow-lg shadow-go/10 transition-all enabled:hover:brightness-125 disabled:opacity-40">⬇ Export Full CSV</button>
    </div>
  )
}
