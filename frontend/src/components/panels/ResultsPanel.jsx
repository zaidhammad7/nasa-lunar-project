import { useState } from 'react'
import DecisionBanner from './DecisionBanner.jsx'
import CoreMetrics from './CoreMetrics.jsx'
import CountdownCards from './CountdownCards.jsx'
import AssessmentSummary from './AssessmentSummary.jsx'
import EvidenceChecks from './EvidenceChecks.jsx'
import SurvivalCard from './SurvivalCard.jsx'
import BackupSites from './BackupSites.jsx'
import SmartWindowList from '../telemetry/SmartWindowList.jsx'
import { cx } from '../../lib/format.js'
import ErrorBoundary from '../ui/ErrorBoundary.jsx'
import TelemetryAlert from './TelemetryAlert.jsx'
import { checkTelemetry, describeError } from '../../lib/validation.js'

const TABS = [{ id: 'telemetry', label: '📊 Site Analysis' }, { id: 'windows', label: '🪟 Best Landing Times & Backup Sites' }]

/** Right sidebar: results for the selected point in two tidy tabs. */
export default function ResultsPanel({ result, calc, scn, mode, liveScore, ranking, onJump, onSelectSite, onPatch, error, issues = [] }) {
  const [tab, setTab] = useState('telemetry')
  const tele = result ? checkTelemetry(result) : null
  const problem = issues.length ? { kind: 'input', title: 'Input outside the allowed range', detail: issues.map((i) => i.message).join(' '), advice: 'Fix the highlighted value; results below are for the last valid input.' }
    : error ? describeError(error) : tele && !tele.ok ? { kind: 'incomplete', title: 'Telemetry incomplete', detail: 'Some expected data was missing from the response, so this site cannot be analysed.', missing: tele.missing, advice: 'Try another site or retry; the rest of the dashboard is unaffected.' } : null
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="grid shrink-0 grid-cols-2 gap-1 border-b border-line p-2" role="tablist">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
            className={cx('rounded-lg px-2 py-2 text-[12px] font-semibold transition-colors', tab === t.id ? 'bg-panel2 text-ink shadow-inner' : 'text-mute hover:text-ink')}>{t.label}</button>
        ))}
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        <TelemetryAlert problem={problem} />
        <ErrorBoundary scope="the results panel" key={result?.scenario?.timestamp_utc}>
        {!result || !calc || (tele && !tele.ok)
          ? <div className="space-y-3">{[130, 190, 110].map((h, i) => <div key={i} className="animate-pulse rounded-xl border border-line bg-panel/60" style={{ height: h }} />)}</div>
          : tab === 'telemetry'
            ? <><DecisionBanner result={result} liveScore={liveScore} scn={scn} /><SurvivalCard calc={calc} scn={scn} onPatch={onPatch} /><CoreMetrics result={result} calc={calc} /><CountdownCards calc={calc} /><AssessmentSummary result={result} mode={mode} /><EvidenceChecks result={result} /></>
            : <><SmartWindowList result={result} onJump={onJump} /><BackupSites ranking={ranking} mode={mode} scn={scn} onSelect={onSelectSite} onPatch={onPatch} /></>}
        </ErrorBoundary>
      </div>
    </div>
  )
}
