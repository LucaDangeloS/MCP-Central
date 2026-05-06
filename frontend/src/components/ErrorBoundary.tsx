import { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  override render() {
    if (this.state.hasError) {
      return this.props.fallback ?? (
        <div className="p-6 rounded-xl border border-red-800 bg-red-950/40 text-red-300">
          <h2 className="font-semibold text-red-200 mb-2">Something went wrong</h2>
          <pre className="text-xs whitespace-pre-wrap font-mono text-red-400">
            {this.state.error?.message}
          </pre>
        </div>
      )
    }
    return this.props.children
  }
}
