import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { authApi } from '@/lib/api'
import { useAuthStore } from '@/store/auth'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Plug } from 'lucide-react'

export default function Login() {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const login = useAuthStore((s) => s.login)
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const { access_token } = await authApi.login(username, password)
      login(access_token)
      navigate('/')
    } catch {
      setError('Invalid username or password')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-zinc-100 dark:bg-zinc-950 flex items-center justify-center px-4 py-8">
      <div className="grid w-full max-w-4xl gap-6 md:grid-cols-[minmax(0,1fr)_minmax(320px,380px)]">
        <section className="rounded-xl border border-blue-200 dark:border-blue-900 bg-white dark:bg-zinc-900 p-6 shadow-sm dark:shadow-none">
          <div className="mb-4 inline-flex rounded-full bg-blue-50 dark:bg-blue-950/50 px-3 py-1 text-xs font-medium text-blue-700 dark:text-blue-300">
            Public MCP discovery
          </div>
          <h2 className="text-2xl font-bold text-zinc-900 dark:text-zinc-100">Agents start here</h2>
          <p className="mt-2 text-sm leading-6 text-zinc-600 dark:text-zinc-300">
            MCP Central exposes machine-readable discovery without admin authentication. Use these
            URLs to enumerate available MCP servers, endpoints, JSON-RPC methods, and API-key rules.
          </p>
          <div className="mt-5 space-y-3 text-sm">
            <DiscoveryLink label="Discovery JSON" href="/.well-known/mcp-central.json" />
            <DiscoveryLink label="MCP endpoint info" href="/mcp" />
            <DiscoveryLink label="OpenAPI JSON" href="/api/openapi.json" />
            <DiscoveryLink label="API docs" href="/api/docs" />
          </div>
          <div className="mt-5 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              MCP communication
            </p>
            <p className="mt-2 text-sm text-zinc-700 dark:text-zinc-300">
              Send MCP JSON-RPC 2.0 requests with <code className="text-blue-600 dark:text-blue-300">POST /mcp</code>.
              Tools are namespaced as <code className="text-blue-600 dark:text-blue-300">server__tool</code>.
              If an endpoint requires a key, pass <code className="text-blue-600 dark:text-blue-300">Authorization: Bearer &lt;api_key&gt;</code>.
            </p>
          </div>
        </section>

        <div className="w-full">
        <div className="flex flex-col items-center mb-8">
          <div className="w-12 h-12 rounded-xl bg-blue-600 flex items-center justify-center mb-4">
            <Plug size={22} className="text-white" aria-hidden="true" />
          </div>
          <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-100">MCP Central</h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-1">
            Sign in to manage your MCP servers
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 space-y-4 shadow-sm dark:shadow-none"
        >
          <div className="space-y-1.5">
            <label htmlFor="username" className="text-sm text-zinc-700 dark:text-zinc-300 font-medium">
              Username
            </label>
            <Input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="password" className="text-sm text-zinc-700 dark:text-zinc-300 font-medium">
              Password
            </label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>

          {error && (
            <p
              role="alert"
              className="text-sm text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-950/40 px-3 py-2 rounded-md border border-red-200 dark:border-red-800"
            >
              {error}
            </p>
          )}

          <Button type="submit" loading={loading} className="w-full">
            Sign in
          </Button>
        </form>
        </div>
      </div>
    </div>
  )
}

function DiscoveryLink({ label, href }: { label: string; href: string }) {
  return (
    <a
      href={href}
      className="flex items-center justify-between rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-zinc-800 dark:text-zinc-200 hover:border-blue-300 dark:hover:border-blue-800"
    >
      <span>{label}</span>
      <code className="text-xs text-blue-600 dark:text-blue-300">{href}</code>
    </a>
  )
}
