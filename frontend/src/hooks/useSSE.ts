import { useEffect, useRef, useCallback } from 'react'
import { getToken } from '@/lib/api'

interface UseSSEOptions {
  onMessage: (data: unknown) => void
  onError?: (error: Event) => void
}

/**
 * Custom hook to manage an SSE (Server-Sent Events) connection.
 * Automatically cleans up the EventSource on unmount.
 */
export function useSSE(url: string | null, options: UseSSEOptions) {
  const esRef = useRef<EventSource | null>(null)
  const onMessageRef = useRef(options.onMessage)
  const onErrorRef = useRef(options.onError)

  onMessageRef.current = options.onMessage
  onErrorRef.current = options.onError

  const connect = useCallback(() => {
    if (!url) return
    const token = getToken()
    const separator = url.includes('?') ? '&' : '?'
    const fullUrl = token ? `${url}${separator}token=${encodeURIComponent(token)}` : url
    const es = new EventSource(fullUrl)
    esRef.current = es

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        onMessageRef.current(data)
      } catch {
        onMessageRef.current(event.data)
      }
    }

    es.onerror = (event) => {
      onErrorRef.current?.(event)
    }
  }, [url])

  useEffect(() => {
    connect()
    return () => {
      esRef.current?.close()
      esRef.current = null
    }
  }, [connect])
}
