// Hardware-aware safe-zone map (frontend/src/lib/hardwareMap.js) evaluated in Node; JSON for tests/test_verdict_rules.py.
// Usage: node tests/js_hardware.mjs <sitesData.json>
import { readFileSync } from 'node:fs'
import { evaluateAllSites, countClasses } from '../frontend/src/lib/hardwareMap.js'
import { OPTIMAL_MAX_SLOPE_DEG } from '../frontend/src/lib/physics.js'

const sites = JSON.parse(readFileSync(process.argv[2], 'utf8'))
const base = { tilt: 80, area: 10, batteryKwh: 1e6, loadW: 150, startISO: '2026-11-13T00:00:00Z', durationHours: 1440, mode: 'balanced', maxSlope: 15 }
const run = (o) => evaluateAllSites(sites, { ...base, ...o })
const out = { optimalMaxSlope: OPTIMAL_MAX_SLOPE_DEG, tower: {}, battery: {}, towerSites: {}, slopes: Object.fromEntries(sites.map((s) => [s.id, s.slope])) }
for (const t of [1, 5, 20, 50, 100, 150]) { const e = run({ tower: t }); out.tower[t] = countClasses(e); out.towerSites[t] = Object.fromEntries(Object.entries(e).map(([k, v]) => [k, v.displayClass])) }
for (const b of [1, 5, 20, 50, 100, 200, 500, 1000]) out.battery[b] = countClasses(run({ tower: 5, batteryKwh: b, loadW: 150 }))
const lowBat = run({ tower: 5, batteryKwh: 5 })
out.lowBatteryReasons = [...new Set(Object.values(lowBat).map((v) => v.reason))]
const full = run({ tower: 5 }), tiny = run({ tower: 5, batteryKwh: 1 })
out.batteryNeverUpgrades = Object.keys(full).every((k) => ({ Hazardous: 0, Acceptable: 1, Optimal: 2 })[tiny[k].displayClass] <= ({ Hazardous: 0, Acceptable: 1, Optimal: 2 })[full[k].displayClass])
console.log(JSON.stringify(out))
