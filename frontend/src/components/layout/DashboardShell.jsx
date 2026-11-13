/**
 * Responsive layout. >= 1024 px: header on top, LEFT mission-control sidebar, then KPI ribbon + 3-D viewport + bottom
 * timeline (everything fits the screen). Below that the page stacks and scrolls, and the 3-D viewport keeps a usable height.
 */
export default function DashboardShell({ header, sidebar, ribbon, viewport, timeline, overlay }) {
  return (
    <div className="flex h-full flex-col bg-bg">
      {header}
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto lg:flex-row lg:overflow-hidden">
        <aside className="max-h-[55vh] w-full shrink-0 space-y-2.5 overflow-y-auto border-b border-line bg-panel/60 p-3 lg:max-h-none lg:w-[420px] lg:border-b-0 lg:border-r xl:w-[430px]" aria-label="Mission control dashboard">
          {sidebar}
        </aside>
        <main className="flex min-w-0 flex-1 flex-col lg:min-h-0">
          {ribbon}
          <div className="relative min-h-[360px] flex-1 lg:min-h-0">
            {viewport}
            {overlay}
          </div>
          {timeline}
        </main>
      </div>
    </div>
  )
}
