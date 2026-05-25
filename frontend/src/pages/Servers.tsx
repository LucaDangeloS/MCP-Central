import { useEffect, useRef, useState } from 'react'
import { configApi, groupsApi, logsApi, serversApi, type Group, type McpTool, type Server } from '@/lib/api'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/select'
import { StatusBadge } from '@/components/ui/badge'
import {
  Play, Square, RotateCcw, ChevronDown, ChevronUp, AlertTriangle,
  SlidersHorizontal, X, Plus, Trash2, Terminal, Wrench,
} from 'lucide-react'
import { cn, formatDate } from '@/lib/utils'
import { useSSE } from '@/hooks/useSSE'

type ParameterRow = {
  id: string
  key: string
  value: string
}

export default function Servers() {
  const [servers, setServers] = useState<Server[]>([])
  const [groups, setGroups] = useState<Group[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [editingServer, setEditingServer] = useState<Server | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [serviceUrl, setServiceUrl] = useState(window.location.origin)

  const load = async () => {
    const [serverResp, groupResp, configResp] = await Promise.all([
      serversApi.list({ page_size: 200 }),
      groupsApi.list(),
      configApi.get(),
    ])
    setServers(serverResp.data)
    setGroups(groupResp.data)
    setServiceUrl(configResp.data.service_url)
    setLoading(false)
  }

  useEffect(() => { load().catch(console.error) }, [])

  const doAction = async (name: string, action: 'start' | 'stop' | 'restart') => {
    setError(null)
    setActionLoading(`${name}-${action}`)
    try {
      if (action === 'start') await serversApi.start(name)
      else if (action === 'stop') await serversApi.stop(name)
      else await serversApi.restart(name)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : `Failed to ${action} server`)
    } finally {
      setActionLoading(null)
    }
  }

  const deleteServer = async (server: Server) => {
    const confirmed = confirm(
      `Delete MCP server '${server.name}'? This stops the process and removes it from MCP Central.`,
    )
    if (!confirmed) return

    setError(null)
    setActionLoading(`${server.name}-delete`)
    try {
      await serversApi.delete(server.name)
      if (expanded === server.id) setExpanded(null)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete server')
    } finally {
      setActionLoading(null)
    }
  }

  if (loading) return <div className="text-zinc-500 text-sm">Loading...</div>

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-100">Servers</h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-0.5">
            {servers.length} server{servers.length !== 1 ? 's' : ''} registered
          </p>
        </div>
        <Button variant="secondary" onClick={() => load()} size="sm" aria-label="Refresh server list">
          Refresh
        </Button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          {error}
        </div>
      )}

      {servers.length === 0 ? (
        <Card>
          <p className="text-sm text-zinc-500 text-center py-8">
            No servers registered. Upload a ZIP package to deploy one.
          </p>
        </Card>
      ) : (
        <div className="space-y-3">
          {servers.map((server) => (
            <Card key={server.id} className="p-0 overflow-hidden">
              {/* Clickable header row — toggles accordion */}
              <button
                type="button"
                onClick={() => setExpanded(expanded === server.id ? null : server.id)}
                aria-expanded={expanded === server.id}
                aria-label={expanded === server.id ? `Collapse ${server.name}` : `Expand ${server.name}`}
                className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <StatusBadge status={server.status} />
                  <div className="min-w-0">
                    <div className="font-medium text-zinc-900 dark:text-zinc-100 text-sm">{server.name}</div>
                    {server.description && (
                      <div className="text-xs text-zinc-500 truncate">{server.description}</div>
                    )}
                    <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs">
                      <code className="rounded bg-zinc-100 dark:bg-zinc-900 px-1.5 py-0.5 font-mono text-blue-600 dark:text-blue-300 border border-zinc-200 dark:border-transparent">
                        {serviceUrl}/mcp/server/{server.name}
                      </code>
                      {server.group_id && (
                        <span className="text-zinc-500">
                          group: {groups.find((group) => group.id === server.group_id)?.name ?? server.group_id}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {server.pid && (
                    <span className="text-xs text-zinc-400 dark:text-zinc-500 hidden sm:block">PID {server.pid}</span>
                  )}
                  {/* Action buttons — stopPropagation so they don't toggle the accordion */}
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Configure ${server.name}`}
                    onClick={(e) => { e.stopPropagation(); setEditingServer(server) }}
                  >
                    <SlidersHorizontal size={14} aria-hidden="true" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Start ${server.name}`}
                    onClick={(e) => { e.stopPropagation(); doAction(server.name, 'start') }}
                    loading={actionLoading === `${server.name}-start`}
                    disabled={server.status === 'running' || server.status === 'starting'}
                  >
                    <Play size={14} aria-hidden="true" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Stop ${server.name}`}
                    onClick={(e) => { e.stopPropagation(); doAction(server.name, 'stop') }}
                    loading={actionLoading === `${server.name}-stop`}
                    disabled={server.status === 'stopped'}
                  >
                    <Square size={14} aria-hidden="true" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Restart ${server.name}`}
                    onClick={(e) => { e.stopPropagation(); doAction(server.name, 'restart') }}
                    loading={actionLoading === `${server.name}-restart`}
                  >
                    <RotateCcw size={14} aria-hidden="true" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Delete ${server.name}`}
                    onClick={(e) => { e.stopPropagation(); deleteServer(server) }}
                    loading={actionLoading === `${server.name}-delete`}
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </Button>
                  {/* Chevron — visual indicator only, click handled by the outer button */}
                  <span className="p-1.5 text-zinc-400 dark:text-zinc-500" aria-hidden="true">
                    {expanded === server.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                  </span>
                </div>
              </button>

              {expanded === server.id && (
                <div className="px-5 pb-5 border-t border-zinc-200 dark:border-zinc-800 space-y-3 text-sm pt-4">
                  <Detail label="Entrypoint" value={server.entrypoint_module} />
                  <Detail label="Auto-start" value={server.auto_start ? 'Yes' : 'No'} />
                  <Detail label="Restart on error" value={server.restart_on_error ? 'Yes' : 'No'} />
                  <Detail label="Restart count" value={String(server.restart_count)} />
                  <Detail label="Registered" value={formatDate(server.created_at)} />

                  <ServerLiveLogs serverName={server.name} />

                  <ServerTools server={server} onUpdated={load} />

                  {server.last_error && (
                    <div>
                      <div className="flex items-center gap-1.5 text-red-600 dark:text-red-400 mb-1.5">
                        <AlertTriangle size={13} aria-hidden="true" />
                        <span className="text-xs font-medium">Last Error</span>
                        {server.last_error_at && (
                          <span className="text-zinc-400 dark:text-zinc-500 text-xs ml-auto">
                            {formatDate(server.last_error_at)}
                          </span>
                        )}
                      </div>
                      <pre className="text-xs font-mono bg-red-50 border border-red-200 dark:bg-red-950/30 dark:border-red-900/50 rounded-md p-3 overflow-x-auto whitespace-pre-wrap text-red-700 dark:text-red-300 max-h-60">
                        {server.last_error}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      {editingServer && (
        <ServerSettingsDialog
          server={editingServer}
          groups={groups}
          onClose={() => setEditingServer(null)}
          onSaved={async () => {
            setEditingServer(null)
            await load()
          }}
        />
      )}
    </div>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-4">
      <span className="text-zinc-500 w-32 shrink-0">{label}</span>
      <span className="text-zinc-800 dark:text-zinc-200">{value}</span>
    </div>
  )
}

function ServerLiveLogs({ serverName }: { serverName: string }) {
  const [streaming, setStreaming] = useState(true)
  const [lines, setLines] = useState<string[]>([])
  const [streamError, setStreamError] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  const streamUrl = streaming ? logsApi.streamUrl(serverName) : null

  useSSE(streamUrl, {
    onMessage: (data) => {
      const line =
        typeof data === 'object' && data !== null && 'line' in data
          ? (data as { line: string }).line
          : String(data)
      setLines((current) => [...current.slice(-300), line])
      setStreamError(false)
      requestAnimationFrame(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }))
    },
    onError: () => setStreamError(true),
  })

  return (
    <div className="rounded-lg border border-zinc-200 dark:border-zinc-800">
      <div className="flex items-center justify-between gap-3 border-b border-zinc-200 dark:border-zinc-800 px-3 py-2">
        <div className="flex items-center gap-2 text-zinc-700 dark:text-zinc-200">
          <Terminal size={14} aria-hidden="true" />
          <span className="text-xs font-medium">Live Logs</span>
          {streaming && (
            <span className="flex items-center gap-1 text-[11px] text-emerald-600 dark:text-emerald-400">
              <span
                className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse"
                aria-hidden="true"
              />
              Streaming
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {lines.length > 0 && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setLines([])}
              aria-label={`Clear live logs for ${serverName}`}
            >
              Clear
            </Button>
          )}
          <Button
            type="button"
            variant={streaming ? 'danger' : 'secondary'}
            size="sm"
            onClick={() => {
              setStreamError(false)
              setStreaming((current) => !current)
            }}
            aria-label={
              streaming ? `Stop live logs for ${serverName}` : `Start live logs for ${serverName}`
            }
          >
            {streaming ? 'Stop' : 'Start Live Logs'}
          </Button>
        </div>
      </div>

      <div className="h-56 overflow-y-auto rounded-b-lg bg-zinc-50 dark:bg-zinc-950 p-3 font-mono text-xs">
        {lines.length === 0 ? (
          <div className="text-zinc-400 dark:text-zinc-600">
            {streaming ? 'Waiting for server output...' : 'Live logging is stopped.'}
          </div>
        ) : (
          lines.map((line, index) => (
            <div
              key={`${index}-${line}`}
              className="whitespace-pre-wrap leading-5 text-zinc-700 dark:text-zinc-300"
            >
              {line}
            </div>
          ))
        )}
        {streamError && (
          <div className="mt-2 text-red-500 dark:text-red-400">
            Live log connection failed. Check that you are still logged in and try again.
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}

function ServerSettingsDialog({
  server,
  groups,
  onClose,
  onSaved,
}: {
  server: Server
  groups: Group[]
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const [description, setDescription] = useState(server.description)
  const [autoStart, setAutoStart] = useState(server.auto_start)
  const [restartOnError, setRestartOnError] = useState(server.restart_on_error)
  const [groupId, setGroupId] = useState<number | null>(server.group_id)
  const [rows, setRows] = useState<ParameterRow[]>(() =>
    Object.entries(server.env_vars).map(([key, value], index) => ({
      id: `${key}-${index}`,
      key,
      value,
    })),
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const addRow = () => {
    setRows((current) => [...current, { id: crypto.randomUUID(), key: '', value: '' }])
  }

  const updateRow = (id: string, patch: Partial<ParameterRow>) => {
    setRows((current) => current.map((row) => (row.id === id ? { ...row, ...patch } : row)))
  }

  const removeRow = (id: string) => {
    setRows((current) => current.filter((row) => row.id !== id))
  }

  const save = async () => {
    setError(null)

    const envVars: Record<string, string> = {}
    for (const row of rows) {
      const key = row.key.trim()
      if (!key) continue
      if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) {
        setError(
          `Parameter name "${key}" is invalid. Use environment variable names like API_BASE_URL or MAX_RESULTS.`,
        )
        return
      }
      envVars[key] = row.value
    }

    setSaving(true)
    try {
      await serversApi.update(server.name, {
        description,
        auto_start: autoStart,
        restart_on_error: restartOnError,
        group_id: groupId,
        env_vars: envVars,
      })
      await onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save server settings')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 dark:bg-zinc-950/70 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="server-settings-title"
    >
      <div className="w-full max-w-2xl rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-xl">
        <div className="flex items-start justify-between gap-4 border-b border-zinc-200 dark:border-zinc-800 p-5">
          <div>
            <h2
              id="server-settings-title"
              className="text-lg font-semibold text-zinc-900 dark:text-zinc-100"
            >
              Configure {server.name}
            </h2>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              Runtime parameters are passed as environment variables when the MCP server starts.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close server settings"
            className="rounded-md p-1.5 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        <div className="max-h-[70vh] space-y-5 overflow-y-auto p-5">
          <label className="block space-y-1.5">
            <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200">Description</span>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              className="min-h-20 w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none focus:ring-2 focus:ring-blue-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100 transition-colors"
            />
          </label>

          <label className="flex items-center justify-between gap-4 rounded-lg border border-zinc-200 dark:border-zinc-800 p-3">
            <span>
              <span className="block text-sm font-medium text-zinc-800 dark:text-zinc-200">Auto-start</span>
              <span className="block text-xs text-zinc-500 dark:text-zinc-400">
                Start this server automatically when the hub starts.
              </span>
            </span>
            <input
              type="checkbox"
              checked={autoStart}
              onChange={(event) => setAutoStart(event.target.checked)}
              aria-label="Enable auto-start"
              className="h-4 w-4 rounded border-zinc-300 text-blue-600 focus:ring-blue-500"
            />
          </label>

          <label className="flex items-center justify-between gap-4 rounded-lg border border-zinc-200 dark:border-zinc-800 p-3">
            <span>
              <span className="block text-sm font-medium text-zinc-800 dark:text-zinc-200">Restart on error</span>
              <span className="block text-xs text-zinc-500 dark:text-zinc-400">
                Restart this server automatically after it crashes. First retry waits about 5 seconds.
              </span>
            </span>
            <input
              type="checkbox"
              checked={restartOnError}
              onChange={(event) => setRestartOnError(event.target.checked)}
              aria-label="Enable restart on error"
              className="h-4 w-4 rounded border-zinc-300 text-blue-600 focus:ring-blue-500"
            />
          </label>

          <div className="space-y-1.5">
            <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200">Group</span>
            <Select
              value={groupId ?? ''}
              onChange={(event) =>
                setGroupId(event.target.value === '' ? null : Number(event.target.value))
              }
              aria-label="Assign server to group"
            >
              <option value="">No group</option>
              {groups.map((group) => (
                <option key={group.id} value={group.id}>
                  {group.name}
                </option>
              ))}
            </Select>
          </div>

          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-medium text-zinc-800 dark:text-zinc-200">Runtime Parameters</h3>
                <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
                  Changes apply after restart. Avoid storing secrets here; use hub/container environment for credentials.
                </p>
              </div>
              <Button type="button" variant="secondary" size="sm" onClick={addRow} aria-label="Add runtime parameter">
                <Plus size={14} aria-hidden="true" /> Add
              </Button>
            </div>

            {rows.length === 0 ? (
              <div className="rounded-lg border border-dashed border-zinc-300 dark:border-zinc-700 p-4 text-center text-sm text-zinc-500 dark:text-zinc-400">
                No parameters configured.
              </div>
            ) : (
              <div className="space-y-2">
                {rows.map((row) => (
                  <div key={row.id} className="grid grid-cols-[1fr_1fr_auto] gap-2">
                    <input
                      value={row.key}
                      onChange={(event) => updateRow(row.id, { key: event.target.value })}
                      placeholder="PARAMETER_NAME"
                      aria-label="Parameter name"
                      className="rounded-md border border-zinc-300 bg-white px-3 py-2 font-mono text-sm text-zinc-900 outline-none focus:ring-2 focus:ring-blue-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
                    />
                    <input
                      value={row.value}
                      onChange={(event) => updateRow(row.id, { value: event.target.value })}
                      placeholder="value"
                      aria-label="Parameter value"
                      className="rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none focus:ring-2 focus:ring-blue-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => removeRow(row.id)}
                      aria-label="Remove parameter"
                    >
                      <Trash2 size={14} aria-hidden="true" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {server.status === 'running' && (
            <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200">
              This server is currently running. Restart it after saving for parameter changes to take effect.
            </div>
          )}

          {error && (
            <div className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
              {error}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-zinc-200 dark:border-zinc-800 p-5">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" onClick={save} loading={saving}>
            Save Settings
          </Button>
        </div>
      </div>
    </div>
  )
}

// ─── Server Tools panel ───────────────────────────────────────────────────────

function ServerTools({ server, onUpdated }: { server: Server; onUpdated: () => void }) {
  const [tools, setTools] = useState<McpTool[]>([])
  const [loadingTools, setLoadingTools] = useState(false)
  const [togglingTool, setTogglingTool] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Fetch tools whenever the accordion opens (server prop changes)
  useEffect(() => {
    if (server.status !== 'running') return
    setLoadingTools(true)
    setError(null)
    serversApi
      .tools(server.name)
      .then((r) => setTools(r.data))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load tools'))
      .finally(() => setLoadingTools(false))
  }, [server.name, server.status])

  const toggleTool = async (toolName: string, currentlyDisabled: boolean) => {
    setTogglingTool(toolName)
    setError(null)
    try {
      const next = currentlyDisabled
        ? server.disabled_tools.filter((t) => t !== toolName)
        : [...server.disabled_tools, toolName]
      await serversApi.update(server.name, { disabled_tools: next })
      onUpdated()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to update tool')
    } finally {
      setTogglingTool(null)
    }
  }

  // Not running — show a gentle nudge
  if (server.status !== 'running') {
    return (
      <div className="rounded-lg border border-zinc-200 dark:border-zinc-800">
        <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-200 dark:border-zinc-800 text-zinc-600 dark:text-zinc-400">
          <Wrench size={14} aria-hidden="true" />
          <span className="text-xs font-medium">Tools</span>
        </div>
        <p className="px-3 py-4 text-xs text-zinc-400 dark:text-zinc-600">
          Start the server to see available tools.
        </p>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-zinc-200 dark:border-zinc-800">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-200 dark:border-zinc-800">
        <Wrench size={14} className="text-zinc-500 dark:text-zinc-400" aria-hidden="true" />
        <span className="text-xs font-medium text-zinc-700 dark:text-zinc-300">Tools</span>
        {!loadingTools && tools.length > 0 && (
          <span className="text-[10px] text-zinc-400 dark:text-zinc-600 ml-1">
            {tools.length - server.disabled_tools.length} / {tools.length} enabled
          </span>
        )}
      </div>

      {/* Body */}
      {loadingTools ? (
        <div className="px-3 py-4 text-xs text-zinc-400 dark:text-zinc-600">Loading tools…</div>
      ) : tools.length === 0 ? (
        <div className="px-3 py-4 text-xs text-zinc-400 dark:text-zinc-600">
          No tools registered for this server yet.
        </div>
      ) : (
        <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/70">
          {tools.map((tool) => {
            const disabled = server.disabled_tools.includes(tool.name)
            const toggling = togglingTool === tool.name
            return (
              <li
                key={tool.name}
                className={cn(
                  'flex items-start justify-between gap-4 px-3 py-3 transition-colors',
                  disabled
                    ? 'opacity-50 bg-zinc-50 dark:bg-zinc-900/40'
                    : 'hover:bg-zinc-50 dark:hover:bg-zinc-800/30',
                )}
              >
                {/* Tool info */}
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span
                      className={cn(
                        'text-xs font-mono font-semibold',
                        disabled
                          ? 'text-zinc-400 dark:text-zinc-600 line-through'
                          : 'text-violet-700 dark:text-violet-400',
                      )}
                    >
                      {tool.name}
                    </span>
                    {disabled && (
                      <span className="text-[10px] font-sans font-medium px-1.5 py-px rounded bg-zinc-200 dark:bg-zinc-700 text-zinc-500 dark:text-zinc-400 uppercase tracking-wide">
                        Disabled
                      </span>
                    )}
                    <span className="text-[10px] font-sans font-medium px-1.5 py-px rounded bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-300 border border-blue-100 dark:border-blue-900/60">
                      {tool.call_count ?? 0} calls
                    </span>
                  </div>
                  {tool.description && (
                    <p className="mt-0.5 text-[11px] text-zinc-500 dark:text-zinc-400 leading-relaxed">
                      {tool.description}
                    </p>
                  )}
                </div>

                {/* Toggle switch */}
                <button
                  type="button"
                  role="switch"
                  aria-checked={!disabled}
                  aria-label={`${disabled ? 'Enable' : 'Disable'} tool ${tool.name}`}
                  disabled={toggling}
                  onClick={() => toggleTool(tool.name, disabled)}
                  className={cn(
                    'relative shrink-0 mt-0.5 h-5 w-9 rounded-full border-2 transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500',
                    toggling && 'opacity-50 cursor-wait',
                    !disabled
                      ? 'bg-blue-500 border-blue-500 dark:bg-blue-600 dark:border-blue-600'
                      : 'bg-zinc-200 border-zinc-200 dark:bg-zinc-700 dark:border-zinc-700',
                  )}
                >
                  <span
                    className={cn(
                      'absolute top-0.5 left-0.5 h-3 w-3 rounded-full bg-white shadow transition-transform duration-200',
                      !disabled ? 'translate-x-4' : 'translate-x-0',
                    )}
                    aria-hidden="true"
                  />
                </button>
              </li>
            )
          })}
        </ul>
      )}

      {/* Inline error */}
      {error && (
        <div className="px-3 py-2 border-t border-red-200 dark:border-red-900 text-xs text-red-600 dark:text-red-400">
          {error}
        </div>
      )}
    </div>
  )
}
