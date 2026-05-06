import { useEffect, useState } from 'react'
import { keysApi, groupsApi, serversApi, type ApiKey, type ApiKeyCreated, type Group, type Server } from '@/lib/api'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Plus, Trash2, Copy, Check } from 'lucide-react'
import { formatDate } from '@/lib/utils'

export default function ApiKeys() {
  const [keys, setKeys] = useState<ApiKey[]>([])
  const [groups, setGroups] = useState<Group[]>([])
  const [servers, setServers] = useState<Server[]>([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [newLabel, setNewLabel] = useState('')
  const [scopeType, setScopeType] = useState<'group' | 'server'>('group')
  const [selectedScope, setSelectedScope] = useState<number | ''>('')
  const [newKey, setNewKey] = useState<ApiKeyCreated | null>(null)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    const [k, g, s] = await Promise.all([
      keysApi.list(),
      groupsApi.list(),
      serversApi.list({ page_size: 200 }),
    ])
    setKeys(k.data)
    setGroups(g.data)
    setServers(s.data)
    setLoading(false)
  }

  useEffect(() => { load().catch(console.error) }, [])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedScope) return
    setError(null)
    setCreating(true)
    try {
      const scopeId = Number(selectedScope)
      const resp = await keysApi.create({
        label: newLabel,
        ...(scopeType === 'group' ? { group_id: scopeId } : { server_id: scopeId }),
      })
      setNewKey(resp.data)
      setNewLabel('')
      setSelectedScope('')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create key')
    } finally {
      setCreating(false)
    }
  }

  const handleCopy = async (text: string) => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleRevoke = async (id: number) => {
    if (!confirm('Revoke this API key? It will stop working immediately.')) return
    await keysApi.revoke(id)
    await load()
  }

  if (loading) return <div className="text-zinc-500 text-sm">Loading...</div>

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-100">API Keys</h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-0.5">
          Manage keys for group and single-server endpoint access
        </p>
      </div>

      {/* New key revealed */}
      {newKey && (
        <Card className="border-emerald-300 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/30">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-emerald-700 dark:text-emerald-300 mb-2">
                API key created — copy it now. It will never be shown again.
              </p>
              <code className="text-xs font-mono text-emerald-800 dark:text-emerald-200 break-all bg-emerald-100 dark:bg-emerald-900/30 px-3 py-2 rounded-md block border border-emerald-200 dark:border-transparent">
                {newKey.plaintext_key}
              </code>
            </div>
            <button
              onClick={() => handleCopy(newKey.plaintext_key)}
              aria-label="Copy API key to clipboard"
              className="p-2 text-emerald-600 hover:text-emerald-700 dark:text-emerald-400 dark:hover:text-emerald-300 shrink-0 transition-colors"
            >
              {copied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
            </button>
          </div>
          <button
            onClick={() => setNewKey(null)}
            aria-label="Dismiss key notice"
            className="mt-3 text-xs text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 transition-colors"
          >
            I have saved the key — dismiss
          </button>
        </Card>
      )}

      {/* Create form */}
      <Card>
        <CardHeader>
          <CardTitle>Create API Key</CardTitle>
        </CardHeader>
        <form onSubmit={handleCreate} className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label htmlFor="key-label" className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                Label *
              </label>
              <Input
                id="key-label"
                value={newLabel}
                onChange={(e) => setNewLabel(e.target.value)}
                placeholder="My integration key"
                required
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="key-scope-type" className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                Scope *
              </label>
              <Select
                id="key-scope-type"
                value={scopeType}
                onChange={(e) => {
                  setScopeType(e.target.value as 'group' | 'server')
                  setSelectedScope('')
                }}
                aria-label="Select API key scope type"
              >
                <option value="group">Group endpoint</option>
                <option value="server">Single MCP server endpoint</option>
              </Select>
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="key-scope" className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                {scopeType === 'group' ? 'Group *' : 'MCP server *'}
              </label>
              <Select
                id="key-scope"
                value={selectedScope}
                onChange={(e) => setSelectedScope(e.target.value === '' ? '' : Number(e.target.value))}
                required
                aria-label={scopeType === 'group' ? 'Select group for API key' : 'Select MCP server for API key'}
              >
                <option value="">Select {scopeType === 'group' ? 'a group' : 'an MCP server'}</option>
                {(scopeType === 'group' ? groups : servers).map((item) => (
                  <option key={item.id} value={item.id}>{item.name}</option>
                ))}
              </Select>
            </div>
          </div>
          {error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</p>}
          <Button type="submit" loading={creating} size="sm">
            <Plus size={14} aria-hidden="true" />
            Generate Key
          </Button>
        </form>
      </Card>

      {/* Keys list */}
      {keys.length === 0 ? (
        <Card>
          <p className="text-sm text-zinc-500 text-center py-6">No API keys yet.</p>
        </Card>
      ) : (
        <Card>
          <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
            {keys.map((k) => (
              <div key={k.id} className="py-3 flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-zinc-900 dark:text-zinc-100">{k.label}</span>
                    <Badge variant="default">
                      {k.group_id !== null
                        ? `group: ${groups.find((g) => g.id === k.group_id)?.name ?? k.group_id}`
                        : `server: ${servers.find((s) => s.id === k.server_id)?.name ?? k.server_id}`}
                    </Badge>
                  </div>
                  <div className="text-xs text-zinc-400 dark:text-zinc-500 mt-0.5 font-mono">
                    {k.key_prefix}{'*'.repeat(8)}
                    <span className="ml-3 font-sans text-zinc-400 dark:text-zinc-500">
                      Created {formatDate(k.created_at)}
                    </span>
                  </div>
                </div>
                <button
                  onClick={() => handleRevoke(k.id)}
                  aria-label={`Revoke API key ${k.label}`}
                  className="p-1.5 text-zinc-400 hover:text-red-600 dark:text-zinc-500 dark:hover:text-red-400 transition-colors shrink-0"
                >
                  <Trash2 size={14} aria-hidden="true" />
                </button>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
