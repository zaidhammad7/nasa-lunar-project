import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { installProbe } from './lib/perf.js'
import ErrorBoundary from './components/ui/ErrorBoundary.jsx'

installProbe() // no-op unless the URL has ?perf=probe

createRoot(document.getElementById('root')).render(
  // StrictMode stays off: it double-runs the heavy procedural-Moon effects in development
  <ErrorBoundary scope="the dashboard"><App /></ErrorBoundary>,
)
