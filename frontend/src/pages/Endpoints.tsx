import { useEffect, useState } from 'react'
import { configApi, serversApi, groupsApi, type Server, type Group } from '@/lib/api'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge, StatusBadge } from '@/components/ui/badge'
import { Copy, Check } from 'lucide-react'

export default function Endpoints() {
  const [servers, setServers] = useState<Server[]>([])
  const [groups, setGroups] = useState<Group[]>([])
  const [loading, setLoading] = useState(true)
  const [copied, setCopied] = useState<string | null>(null)
  const [serviceUrl, setServiceUrl] = useState(window.location.origin)

  useEffect(() => {
    Promise.all([serversApi.list({ page_size: 200 }), groupsApi.list(), configApi.get()])
      .then(([s, g, config]) => {
        setServers(s.data)
        setGroups(g.data)
        setServiceUrl(config.data.service_url)
        setLoading(false)
      })
      .catch(console.error)
  }, [])

  const copy = async (text: string) => {
    await navigator.clipboard.writeText(text)
    setCopied(text)
    setTimeout(() => setCopied(null), 1500)
  }

  if (loading) return <div className="text-zinc-500 text-sm">Loading...</div>

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-100">Endpoints</h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-0.5">
          MCP endpoint URLs for AI client configuration
        </p>
      </div>

      {/* Global endpoint */}
      <Card>
        <CardHeader>
          <CardTitle>Global Endpoint</CardTitle>
          <Badge variant="info">All servers</Badge>
        </CardHeader>
        <EndpointRow url={`${serviceUrl}/mcp`} onCopy={copy} copied={copied} />
        <p className="text-xs text-zinc-500 mt-2">
          Use this when the AI client should discover every running server. Tools are namespaced as{' '}
          <code className="text-blue-600 dark:text-blue-400">server__tool</code>.
        </p>
      </Card>

      {/* Group endpoints */}
      {groups.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Group Endpoints</CardTitle>
          </CardHeader>
          <div className="space-y-4">
            {groups.map((g) => (
              <div key={g.id}>
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="text-sm text-zinc-800 dark:text-zinc-200 font-medium">{g.name}</span>
                  {g.require_api_key && <Badge variant="warning">API key required</Badge>}
                </div>
                <EndpointRow url={`${serviceUrl}/mcp/${g.name}`} onCopy={copy} copied={copied} />
                <p className="mt-1 text-xs text-zinc-500">
                  Group endpoint for only the servers assigned to{' '}
                  <code className="text-blue-600 dark:text-blue-400">{g.name}</code>.
                </p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Per-server endpoints */}
      {servers.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Per-Server Endpoints</CardTitle>
          </CardHeader>
          <div className="space-y-4">
            {servers.map((s) => (
              <div key={s.id}>
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="text-sm text-zinc-800 dark:text-zinc-200 font-medium">{s.name}</span>
                  <StatusBadge status={s.status} />
                </div>
                <EndpointRow url={`${serviceUrl}/mcp/server/${s.name}`} onCopy={copy} copied={copied} />
                <p className="mt-1 text-xs text-zinc-500">
                  Direct endpoint for this server only. Use it when an AI should see just this server's tools.
                </p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Example client config */}
      <Card>
        <CardHeader>
          <CardTitle>Example Client Config</CardTitle>
        </CardHeader>
        <pre className="text-xs font-mono bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-md p-3 text-zinc-700 dark:text-zinc-300 leading-6 overflow-x-auto">
{`{
  "mcpServers": {
    "mcp-central": {
      "url": "${serviceUrl}/mcp"
    }
  }
}`}
        </pre>
        <p className="text-xs text-zinc-500 mt-2">
          Paste this into your Claude Desktop or Cursor MCP configuration.
        </p>
      </Card>
    </div>
  )
}

function EndpointRow({
  url,
  onCopy,
  copied,
}: {
  url: string
  onCopy: (url: string) => void
  copied: string | null
}) {
  return (
    <div className="flex items-center gap-2 bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-md px-3 py-2">
      <code className="flex-1 text-xs font-mono text-blue-600 dark:text-blue-300 truncate">{url}</code>
      <button
        onClick={() => onCopy(url)}
        aria-label={`Copy ${url}`}
        className="p-1 text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 transition-colors shrink-0"
      >
        {copied === url
          ? <Check size={14} aria-hidden="true" />
          : <Copy size={14} aria-hidden="true" />}
      </button>
    </div>
  )
}
