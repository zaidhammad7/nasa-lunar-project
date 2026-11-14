import { Component } from 'react'

/**
 * Catches rendering errors (for example from an unexpected data shape) and shows a readable message with a retry button instead of a
 * blank page. `scope` names the part of the dashboard that failed; `onReset` lets the parent clear the bad data.
 */
export default class ErrorBoundary extends Component {
  state = { error: null }

  static getDerivedStateFromError(error) { return { error } }

  componentDidCatch(error, info) { console.error(`[${this.props.scope || 'app'}]`, error, info?.componentStack) }

  reset = () => { this.setState({ error: null }); this.props.onReset?.() }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div role="alert" className="m-3 rounded-xl border border-nogo/50 bg-nogo/10 p-4 text-[12px] leading-snug text-ink">
        <div className="mb-1 text-[13px] font-semibold text-nogo">This part of the dashboard could not be displayed</div>
        <p className="text-mute">The data for {this.props.scope || 'this view'} was incomplete or in an unexpected format. Nothing else is affected.</p>
        <p className="num mt-2 break-words text-[11px] text-mute">{String(this.state.error?.message || this.state.error)}</p>
        <button onClick={this.reset} className="mt-3 rounded-md border border-line px-3 py-1 text-[11px] font-semibold hover:bg-panel2">Try again</button>
      </div>
    )
  }
}
