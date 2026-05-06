import { useEffect, useRef, useState } from 'react'
import { logsApi, serversApi, type LogEntry, type Server } from '@/lib/api'
import { Select } from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { useSSE } from '@/hooks/useSSE'
import { cn } from '@/lib/utils'
import { ArrowUp, Wifi, WifiOff } from 'lucide-react'

// ─── Level design tokens ──────────────────────────────────────────────────────

const LEVELS = [
  { value: '', label: 'All levels' },
  { value: 'debug', label: 'Debug' },
  { value: 'info', label: 'Info' },
  { value: 'warning', label: 'Warning' },
  { value: 'error', label: 'Error' },
  { value: 'critical', label: 'Critical' },
] as const

/** Thin left-gutter line colour */
const levelGutter: Record<string, string> = {
  debug:    'border-l-zinc-300    dark:border-l-zinc-700',
  info:     'border-l-sky-400     dark:border-l-sky-500',
  warning:  'border-l-amber-400   dark:border-l-amber-400',
  error:    'border-l-rose-500    dark:border-l-rose-500',
  critical: 'border-l-fuchsia-500 dark:border-l-fuchsia-400',
}

/** Coloured level label — no pill, just vivid text */
const levelLabel: Record<string, string> = {
  debug:    'text-zinc-400        dark:text-zinc-600',
  info:     'text-sky-500         dark:text-sky-400',
  warning:  'text-amber-500       dark:text-amber-400',
  error:    'text-rose-500        dark:text-rose-400',
  critical: 'text-fuchsia-600     dark:text-fuchsia-400 font-bold',
}

/** Message body colour — readable but tinted per level */
const levelText: Record<string, string> = {
  debug:    'text-zinc-400  dark:text-zinc-600',
  info:     'text-zinc-700  dark:text-zinc-300',
  warning:  'text-amber-800 dark:text-amber-200',
  error:    'text-rose-700  dark:text-rose-300',
  critical: 'text-fuchsia-800 dark:text-fuchsia-200 font-semibold',
}

/** Subtle row hover tint per level */
const levelHover: Record<string, string> = {
  debug:    'hover:bg-zinc-50     dark:hover:bg-zinc-800/30',
  info:     'hover:bg-sky-50/60   dark:hover:bg-sky-900/10',
  warning:  'hover:bg-amber-50/60 dark:hover:bg-amber-900/10',
  error:    'hover:bg-rose-50/60  dark:hover:bg-rose-900/10',
  critical: 'hover:bg-fuchsia-50/60 dark:hover:bg-fuchsia-900/10',
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: 'short', day: '2-digit',
  })
}

function isLogEntry(value: unknown): value is LogEntry {
  if (typeof value !== 'object' || value === null) return false
  const e = value as Partial<LogEntry>
  return (
    typeof e.id === 'number' &&
    typeof e.server_name === 'string' &&
    typeof e.stream === 'string' &&
    typeof e.level === 'string' &&
    typeof e.message === 'string' &&
    typeof e.raw === 'string' &&
    typeof e.timestamp === 'string'
  )
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function Logs() {
  const [servers, setServers] = useState<Server[]>([])
  const [selectedServer, setSelectedServer] = useState<string>('')
  const [selectedLevel, setSelectedLevel] = useState<string>('')
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [connected, setConnected] = useState(true)
  const [newCount, setNewCount] = useState(0)
  const scrollRef = useRef<HTMLDivElement>(null)
  const isScrolledDown = useRef(false)

  useEffect(() => {
    serversApi
      .list({ page_size: 200 })
      .then((r) => { setServers(r.data); setLoading(false) })
      .catch(console.error)
  }, [])

  useEffect(() => {
    setLogs([])
    setNewCount(0)
    logsApi
      .query({ server_name: selectedServer, level: selectedLevel, page_size: 200 })
      .then((r) => setLogs(r.data))
      .catch(console.error)
  }, [selectedServer, selectedLevel])

  // Track whether user has scrolled away from the top
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const onScroll = () => { isScrolledDown.current = el.scrollTop > 80 }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [])

  useSSE(logsApi.streamUrl(selectedServer), {
    onMessage: (data) => {
      if (!isLogEntry(data)) return
      if (selectedLevel && data.level !== selectedLevel) return
      setConnected(true)
      setLogs((prev) => {
        if (prev.some((e) => e.id === data.id)) return prev
        return [data, ...prev].slice(0, 500)
      })
      if (isScrolledDown.current) setNewCount((n) => n + 1)
    },
    onError: () => setConnected(false),
  })

  const scrollToTop = () => {
    scrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
    setNewCount(0)
  }

  if (loading) return <div className="text-zinc-500 text-sm">Loading…</div>

  // Group rows by calendar day for day-separator rendering
  const rowsWithSeparators = buildRowGroups(logs)

  return (
    <div className="flex flex-col h-[calc(100vh-3rem)] -mx-6 -mt-6">

      {/* ── Toolbar ──────────────────────────────────────────────────────── */}
      <div className="shrink-0 flex items-center justify-between gap-3 flex-wrap px-6 pt-6 pb-3">
        <div>
          <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-100">Logs</h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-0.5">
            Real-time hub and MCP server log stream
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          {/* Live indicator */}
          <span
            aria-live="polite"
            className={cn(
              'inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full border transition-colors',
              connected
                ? 'text-emerald-700 bg-emerald-50 border-emerald-200 dark:text-emerald-400 dark:bg-emerald-950/40 dark:border-emerald-800/60'
                : 'text-rose-600 bg-rose-50 border-rose-200 dark:text-rose-400 dark:bg-rose-950/40 dark:border-rose-800/60',
            )}
          >
            {connected ? (
              <>
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" aria-hidden="true" />
                Live
              </>
            ) : (
              <>
                <WifiOff size={11} aria-hidden="true" />
                Disconnected
              </>
            )}
          </span>

          <Select
            value={selectedServer}
            onChange={(e) => setSelectedServer(e.target.value)}
            aria-label="Filter logs by source"
            className="w-44"
          >
            <option value="">All sources</option>
            <option value="hub">Hub</option>
            {servers.map((s) => (
              <option key={s.id} value={s.name}>{s.name}</option>
            ))}
          </Select>

          <Select
            value={selectedLevel}
            onChange={(e) => setSelectedLevel(e.target.value)}
            aria-label="Filter logs by level"
            className="w-36"
          >
            {LEVELS.map(({ value, label }) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </Select>

          {logs.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => { setLogs([]); setNewCount(0) }}
              aria-label="Clear log entries"
            >
              Clear
            </Button>
          )}
        </div>
      </div>

      {/* ── Column headers ───────────────────────────────────────────────── */}
      <div className="shrink-0 flex items-center gap-0 px-6 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/60">
        <span className="w-[4.5rem] shrink-0 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-zinc-400 dark:text-zinc-600">
          Time
        </span>
        <span className="w-20 shrink-0 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-zinc-400 dark:text-zinc-600">
          Level
        </span>
        <span className="w-36 shrink-0 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-zinc-400 dark:text-zinc-600">
          Source
        </span>
        <span className="flex-1 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-zinc-400 dark:text-zinc-600">
          Message
        </span>
        <span className="w-14 shrink-0 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-zinc-400 dark:text-zinc-600 text-right pr-2">
          Stream
        </span>
      </div>

      {/* ── Log rows ─────────────────────────────────────────────────────── */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto overscroll-contain"
      >
        {logs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-3">
            <Wifi size={28} className="text-zinc-300 dark:text-zinc-700" aria-hidden="true" />
            <p className="text-sm text-zinc-400 dark:text-zinc-600">Waiting for log entries…</p>
          </div>
        ) : (
          rowsWithSeparators.map((item) =>
            item.type === 'separator' ? (
              <DaySeparator key={item.key} label={item.label} />
            ) : (
              <LogRow key={item.entry.id} entry={item.entry} />
            ),
          )
        )}

        {/* Connection-lost footer strip */}
        {!connected && (
          <div className="sticky bottom-0 flex items-center gap-2 px-6 py-2 bg-rose-50 dark:bg-rose-950/50 border-t border-rose-200 dark:border-rose-900 text-xs text-rose-700 dark:text-rose-300">
            <WifiOff size={12} aria-hidden="true" />
            Live connection lost — the stream will reconnect automatically.
          </div>
        )}
      </div>

      {/* ── "N new" scroll-to-top pill ───────────────────────────────────── */}
      {newCount > 0 && (
        <button
          onClick={scrollToTop}
          className="fixed top-20 right-8 z-40 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold shadow-lg bg-blue-600 text-white hover:bg-blue-500 active:scale-95 transition-all"
          aria-label="Scroll to newest log entries"
        >
          <ArrowUp size={12} aria-hidden="true" />
          {newCount} new
        </button>
      )}
    </div>
  )
}

// ─── Day separator ────────────────────────────────────────────────────────────

function DaySeparator({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 px-6 py-2 sticky top-0 z-10 bg-zinc-100/90 dark:bg-zinc-950/90 backdrop-blur-sm">
      <div className="flex-1 h-px bg-zinc-200 dark:bg-zinc-800" />
      <span className="text-[10px] font-semibold uppercase tracking-widest text-zinc-400 dark:text-zinc-600 select-none">
        {label}
      </span>
      <div className="flex-1 h-px bg-zinc-200 dark:bg-zinc-800" />
    </div>
  )
}

// ─── Single log row ───────────────────────────────────────────────────────────

function LogRow({ entry }: { entry: LogEntry }) {
  const [expanded, setExpanded] = useState(false)
  const body = entry.raw && entry.raw !== entry.message ? entry.raw : entry.message
  const isMultiLine = body.includes('\n')
  const level = entry.level

  return (
    <div
      className={cn(
        'group flex items-start gap-0 border-l-[3px] border-b',
        'border-b-zinc-100 dark:border-b-zinc-800/70',
        'font-mono text-xs transition-colors duration-75',
        levelGutter[level] ?? levelGutter.info,
        levelHover[level] ?? levelHover.info,
      )}
    >
      {/* Time */}
      <div className="w-[4.5rem] shrink-0 px-2 py-2 tabular-nums text-[10px] leading-4 text-zinc-400 dark:text-zinc-600 select-none">
        {formatTime(entry.timestamp)}
      </div>

      {/* Level */}
      <div className={cn(
        'w-20 shrink-0 py-2 text-[10px] uppercase tracking-wider font-bold leading-4',
        levelLabel[level] ?? levelLabel.info,
      )}>
        {level}
      </div>

      {/* Source */}
      <div className="w-36 shrink-0 py-2 pr-2 leading-4 text-[10px] text-violet-600 dark:text-violet-400 truncate">
        {entry.server_name}
      </div>

      {/* Message */}
      <div className="flex-1 min-w-0 py-2 pr-2 leading-5">
        {isMultiLine && !expanded ? (
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className={cn('text-left w-full truncate block', levelText[level] ?? levelText.info)}
            title="Click to expand"
          >
            {entry.message}
            <span className="ml-2 text-[9px] text-zinc-400 dark:text-zinc-600 font-sans not-italic">
              ▸ expand
            </span>
          </button>
        ) : isMultiLine && expanded ? (
          <button
            type="button"
            onClick={() => setExpanded(false)}
            className={cn('text-left w-full', levelText[level] ?? levelText.info)}
            title="Click to collapse"
          >
            <pre className="whitespace-pre-wrap font-mono">
              {body}
            </pre>
            <span className="mt-1 block text-[9px] text-zinc-400 dark:text-zinc-600 font-sans not-italic">
              ▴ collapse
            </span>
          </button>
        ) : (
          <span className={cn('break-words', levelText[level] ?? levelText.info)}>
            {body}
          </span>
        )}
      </div>

      {/* Stream */}
      <div className="w-14 shrink-0 py-2 text-right pr-3 text-[9px] uppercase tracking-wider leading-4 text-zinc-300 dark:text-zinc-700 select-none">
        {entry.stream !== 'hub' ? entry.stream : ''}
      </div>
    </div>
  )
}

// ─── Row grouping helpers ─────────────────────────────────────────────────────

type RowItem =
  | { type: 'separator'; key: string; label: string }
  | { type: 'row'; entry: LogEntry }

function buildRowGroups(logs: LogEntry[]): RowItem[] {
  const items: RowItem[] = []
  let lastDay = ''
  for (const entry of logs) {
    const day = formatDay(entry.timestamp)
    if (day !== lastDay) {
      lastDay = day
      items.push({ type: 'separator', key: `sep-${day}-${entry.id}`, label: day })
    }
    items.push({ type: 'row', entry })
  }
  return items
}
