/**
 * Calm 3-zone layout: LEFT inputs (340 px) | CENTER 3-D scene + bottom timeline | RIGHT results (370 px).
 * The header and both sidebars can each be hidden (see PanelToggles); the 3-D scene then takes the freed space.
 * Below 1024 px the zones stack and the page scrolls.
 */
export default function DashboardShell({ header, left, right, viewport, timeline, panels }) {
  return (
    <div className="flex h-full flex-col bg-bg">
      {panels.header && header}
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto lg:flex-row lg:overflow-hidden">
        {panels.left && (
          <aside className="max-h-[55vh] w-full shrink-0 space-y-3 overflow-y-auto border-b border-line bg-panel/60 p-3 lg:max-h-none lg:w-[340px] lg:border-b-0 lg:border-r" aria-label="Inputs">
            {left}
          </aside>
        )}
        <main className="flex min-w-0 flex-1 flex-col lg:min-h-0">
          <div className="relative min-h-[380px] flex-1 lg:min-h-0">{viewport}</div>
          {timeline}
        </main>
        {panels.right && (
          <aside className="max-h-[70vh] w-full shrink-0 border-t border-line bg-panel/60 lg:max-h-none lg:w-[370px] lg:border-l lg:border-t-0" aria-label="Results">
            {right}
          </aside>
        )}
      </div>
    </div>
  )
}
