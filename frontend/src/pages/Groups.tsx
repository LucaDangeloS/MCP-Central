import { useEffect, useState } from 'react'
import { groupsApi, serversApi, type Group, type Server } from '@/lib/api'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Plus, SlidersHorizontal, Trash2, X } from 'lucide-react'

export default function Groups() {
  const [groups, setGroups] = useState<Group[]>([])
  const [servers, setServers] = useState<Server[]>([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [requireKey, setRequireKey] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editingGroup, setEditingGroup] = useState<Group | null>(null)

  const load = async () => {
    const [groupResp, serverResp] = await Promise.all([
      groupsApi.list(),
      serversApi.list({ page_size: 200 }),
    ])
    setGroups(groupResp.data)
    setServers(serverResp.data)
    setLoading(false)
  }

  useEffect(() => { load().catch(console.error) }, [])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setCreating(true)
    try {
      await groupsApi.create({ name: newName, description: newDesc, require_api_key: requireKey })
      setNewName('')
      setNewDesc('')
      setRequireKey(false)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create group')
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (name: string) => {
    if (!confirm(`Delete group '${name}'? This cannot be undone.`)) return
    try {
      setError(null)
      await groupsApi.delete(name)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete group')
    }
  }

  const updateServerGroup = async (server: Server, groupId: number | null) => {
    try {
      setError(null)
      await serversApi.update(server.name, { group_id: groupId })
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update server group')
    }
  }

  if (loading) return <div className="text-zinc-500 text-sm">Loading...</div>

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-100">Groups</h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-0.5">
          Organize servers and apply access policies
        </p>
      </div>

      {/* Create form */}
      <Card>
        <CardHeader>
          <CardTitle>Create Group</CardTitle>
        </CardHeader>
        <form onSubmit={handleCreate} className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label htmlFor="grp-name" className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                Name *
              </label>
              <Input
                id="grp-name"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="my-group"
                required
                pattern="^[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]$"
                title="Lowercase letters, numbers, hyphens, underscores only"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="grp-desc" className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                Description
              </label>
              <Input
                id="grp-desc"
                value={newDesc}
                onChange={(e) => setNewDesc(e.target.value)}
                placeholder="Optional description"
              />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300 cursor-pointer">
            <input
              type="checkbox"
              checked={requireKey}
              onChange={(e) => setRequireKey(e.target.checked)}
              className="accent-blue-500"
              aria-label="Require API key for this group"
            />
            Require API key
          </label>
          {error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</p>}
          <Button type="submit" loading={creating} size="sm">
            <Plus size={14} aria-hidden="true" />
            Create
          </Button>
        </form>
      </Card>

      {/* Groups list */}
      {groups.length === 0 ? (
        <Card>
          <p className="text-sm text-zinc-500 text-center py-6">No groups yet.</p>
        </Card>
      ) : (
        <div className="space-y-3">
          {groups.map((g) => (
            <Card key={g.id}>
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-zinc-900 dark:text-zinc-100 text-sm">{g.name}</span>
                    {g.require_api_key && <Badge variant="warning">API key required</Badge>}
                  </div>
                  {g.description && (
                    <p className="text-xs text-zinc-500 mt-0.5">{g.description}</p>
                  )}
                  <div className="mt-2 text-xs text-zinc-500">
                    MCP endpoint:{' '}
                    <code className="text-blue-600 dark:text-blue-400 font-mono">/mcp/{g.name}</code>
                  </div>
                  <div className="mt-3 space-y-2">
                    <div className="text-xs font-medium text-zinc-600 dark:text-zinc-400">MCP servers</div>
                    {servers.filter((server) => server.group_id === g.id).length === 0 ? (
                      <p className="text-xs text-zinc-400 dark:text-zinc-500">No servers in this group.</p>
                    ) : (
                      <div className="flex flex-wrap gap-2">
                        {servers
                          .filter((server) => server.group_id === g.id)
                          .map((server) => (
                            <span
                              key={server.id}
                              className="inline-flex items-center gap-1 rounded-full border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-transparent px-2 py-1 text-xs text-zinc-700 dark:text-zinc-300"
                            >
                              {server.name}
                              <button
                                type="button"
                                onClick={() => updateServerGroup(server, null)}
                                aria-label={`Remove ${server.name} from ${g.name}`}
                                className="text-zinc-400 hover:text-red-500 dark:text-zinc-500 dark:hover:text-red-400 transition-colors"
                              >
                                <X size={12} aria-hidden="true" />
                              </button>
                            </span>
                          ))}
                      </div>
                    )}
                    <Select
                      value=""
                      onChange={(event) => {
                        const server = servers.find((item) => item.id === Number(event.target.value))
                        if (server) updateServerGroup(server, g.id)
                      }}
                      aria-label={`Add MCP server to ${g.name}`}
                      className="w-auto text-xs py-1.5"
                    >
                      <option value="">Add server…</option>
                      {servers
                        .filter((server) => server.group_id !== g.id)
                        .map((server) => (
                          <option key={server.id} value={server.id}>{server.name}</option>
                        ))}
                    </Select>
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => setEditingGroup(g)}
                    aria-label={`Edit group ${g.name}`}
                    className="p-1.5 text-zinc-400 hover:text-zinc-700 dark:text-zinc-500 dark:hover:text-zinc-300 transition-colors"
                  >
                    <SlidersHorizontal size={14} aria-hidden="true" />
                  </button>
                  <button
                    onClick={() => handleDelete(g.name)}
                    aria-label={`Delete group ${g.name}`}
                    className="p-1.5 text-zinc-400 hover:text-red-600 dark:text-zinc-500 dark:hover:text-red-400 transition-colors"
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {editingGroup && (
        <GroupSettingsDialog
          group={editingGroup}
          onClose={() => setEditingGroup(null)}
          onSaved={async () => {
            setEditingGroup(null)
            await load()
          }}
        />
      )}
    </div>
  )
}

function GroupSettingsDialog({
  group,
  onClose,
  onSaved,
}: {
  group: Group
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const [description, setDescription] = useState(group.description)
  const [requireApiKey, setRequireApiKey] = useState(group.require_api_key)
  const [rateLimit, setRateLimit] = useState(String(group.rate_limit_rpm))
  const [hiddenTools, setHiddenTools] = useState(group.hidden_tools.join('\n'))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = async () => {
    setError(null)
    const parsedRateLimit = Number(rateLimit)
    if (!Number.isInteger(parsedRateLimit) || parsedRateLimit < 0) {
      setError('Rate limit must be a non-negative integer.')
      return
    }

    setSaving(true)
    try {
      await groupsApi.update(group.name, {
        description,
        require_api_key: requireApiKey,
        rate_limit_rpm: parsedRateLimit,
        hidden_tools: hiddenTools
          .split('\n')
          .map((tool) => tool.trim())
          .filter(Boolean),
      })
      await onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update group')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 dark:bg-zinc-950/70 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="group-settings-title"
    >
      <div className="w-full max-w-xl rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-xl">
        <div className="flex items-start justify-between gap-4 border-b border-zinc-200 dark:border-zinc-800 p-5">
          <div>
            <h2
              id="group-settings-title"
              className="text-lg font-semibold text-zinc-900 dark:text-zinc-100"
            >
              Edit {group.name}
            </h2>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              Update access policy and tool visibility for this group.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close group settings"
            className="rounded-md p-1.5 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        <div className="space-y-4 p-5">
          <label className="block space-y-1.5">
            <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200">Description</span>
            <Input value={description} onChange={(event) => setDescription(event.target.value)} />
          </label>

          <label className="flex items-center justify-between gap-4 rounded-lg border border-zinc-200 dark:border-zinc-800 p-3">
            <span>
              <span className="block text-sm font-medium text-zinc-800 dark:text-zinc-200">
                Require API key
              </span>
              <span className="block text-xs text-zinc-500 dark:text-zinc-400">
                Protect this group's MCP endpoint with API keys.
              </span>
            </span>
            <input
              type="checkbox"
              checked={requireApiKey}
              onChange={(event) => setRequireApiKey(event.target.checked)}
              aria-label="Require API key for group"
              className="h-4 w-4 rounded border-zinc-300 text-blue-600 focus:ring-blue-500"
            />
          </label>

          <label className="block space-y-1.5">
            <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200">Rate limit RPM</span>
            <Input
              type="number"
              min="0"
              value={rateLimit}
              onChange={(event) => setRateLimit(event.target.value)}
              aria-label="Group rate limit requests per minute"
            />
            <span className="block text-xs text-zinc-500 dark:text-zinc-400">Use 0 for unlimited.</span>
          </label>

          <label className="block space-y-1.5">
            <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200">Hidden tools</span>
            <textarea
              value={hiddenTools}
              onChange={(event) => setHiddenTools(event.target.value)}
              placeholder="server__tool_name"
              aria-label="Hidden tools, one per line"
              className="min-h-24 w-full rounded-md border border-zinc-300 bg-white px-3 py-2 font-mono text-sm text-zinc-900 outline-none focus:ring-2 focus:ring-blue-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100 transition-colors"
            />
            <span className="block text-xs text-zinc-500 dark:text-zinc-400">
              One namespaced tool per line.
            </span>
          </label>

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
            Save Group
          </Button>
        </div>
      </div>
    </div>
  )
}
