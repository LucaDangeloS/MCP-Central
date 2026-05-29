import { useCallback, useEffect, useState } from 'react'
import { configApi, uploadApi, type Server } from '@/lib/api'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { StatusBadge } from '@/components/ui/badge'
import { Upload as UploadIcon, CheckCircle, XCircle, FileCode } from 'lucide-react'
import { cn } from '@/lib/utils'

const DEFAULT_SERVER_CODE = `"""Single-file MCP server entrypoint.

Replace this with your MCP server implementation.
"""

def main():
    # Start your stdio MCP server here.
    raise RuntimeError("Replace the editor template with your MCP server code.")
`

const DEFAULT_MANIFEST = JSON.stringify(
  {
    name: 'my-server',
    version: '1.0.0',
    description: '',
    entrypoint: 'main.py',
    module: 'main',
    language: 'python',
    env: {},
    tools: [],
  },
  null,
  2,
)

export default function Upload() {
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [mode, setMode] = useState<'zip' | 'codebase' | 'editor'>('zip')
  const [result, setResult] = useState<{ server: Server; message: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [serverName, setServerName] = useState('')
  const [description, setDescription] = useState('')
  const [code, setCode] = useState(DEFAULT_SERVER_CODE)
  const [manifestJson, setManifestJson] = useState(DEFAULT_MANIFEST)
  const [requirements, setRequirements] = useState('# no requirements\n')
  const [autoStart, setAutoStart] = useState(true)
  const [serviceUrl, setServiceUrl] = useState(window.location.origin)

  useEffect(() => {
    configApi.get()
      .then((resp) => setServiceUrl(resp.data.service_url))
      .catch(console.error)
  }, [])

  const handleFile = async (file: File) => {
    if (!file.name.endsWith('.zip')) {
      setError('Only .zip files are accepted')
      return
    }
    setError(null)
    setResult(null)
    setUploading(true)
    try {
      const resp = mode === 'codebase'
        ? await uploadApi.uploadCodebase(file, { auto_start: autoStart, replace_existing: true })
        : await uploadApi.upload(file)
      setResult({ server: resp.data.server, message: resp.data.message })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }, [mode, autoStart])

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) handleFile(file)
  }

  const createFromEditor = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError(null)
    setResult(null)

    const name = serverName.trim()
    if (!/^[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]$/.test(name)) {
      setError(
        'Server name must use lowercase letters, numbers, hyphens, or underscores, and must be 3–64 characters.',
      )
      return
    }

    let manifest: Record<string, unknown>
    try {
      const parsed = JSON.parse(manifestJson) as unknown
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        setError('manifest.json must be a JSON object.')
        return
      }
      manifest = parsed as Record<string, unknown>
    } catch (err) {
      setError(
        err instanceof Error
          ? `manifest.json is not valid JSON: ${err.message}`
          : 'manifest.json is not valid JSON.',
      )
      return
    }

    setCreating(true)
    try {
      const resp = await uploadApi.createSingleFile({
        name,
        description,
        code,
        requirements,
        manifest,
        auto_start: autoStart,
      })
      setResult({ server: resp.data.server, message: resp.data.message })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Server creation failed')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="space-y-5 max-w-4xl">
      <div>
        <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-100">Deploy</h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-0.5">
          Upload Python, JavaScript, or TypeScript MCP packages, or create a single-file Python server
        </p>
      </div>

      {/* Mode switcher */}
      <div className="inline-flex rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-1">
        <button
          type="button"
          onClick={() => setMode('zip')}
          className={cn(
            'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
            mode === 'zip'
              ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950'
              : 'text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100',
          )}
        >
          ZIP Upload
        </button>
        <button
          type="button"
          onClick={() => setMode('codebase')}
          className={cn(
            'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
            mode === 'codebase'
              ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950'
              : 'text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100',
          )}
        >
          Codebase Upload
        </button>
        <button
          type="button"
          onClick={() => setMode('editor')}
          className={cn(
            'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
            mode === 'editor'
              ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950'
              : 'text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100',
          )}
        >
          Single-file Editor
        </button>
      </div>

      {/* Drop zone */}
      {mode === 'zip' || mode === 'codebase' ? (
        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cn(
            'border-2 border-dashed rounded-xl p-12 flex flex-col items-center gap-4 transition-colors cursor-pointer',
            dragging
              ? 'border-blue-500 bg-blue-50 dark:bg-blue-950/20'
              : 'border-zinc-300 dark:border-zinc-700 hover:border-zinc-400 dark:hover:border-zinc-500 hover:bg-zinc-50 dark:hover:bg-zinc-900/50',
          )}
        >
          <div
            className="w-14 h-14 rounded-full bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center"
            aria-hidden="true"
          >
            <UploadIcon size={24} className="text-zinc-500 dark:text-zinc-400" />
          </div>
          <div className="text-center">
            <p className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
              Drop your {mode === 'codebase' ? 'codebase' : 'package'} .zip file here
            </p>
            <p className="text-xs text-zinc-500 mt-1">or click to browse</p>
          </div>
          <div>
            <input
              id="file-upload"
              type="file"
              accept=".zip"
              className="sr-only"
              onChange={onInputChange}
            />
            <Button
              variant="secondary"
              size="sm"
              loading={uploading}
              onClick={() => document.getElementById('file-upload')?.click()}
              type="button"
            >
              {uploading ? 'Uploading…' : 'Browse files'}
            </Button>
          </div>
          {mode === 'codebase' && (
            <label className="flex items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400">
              <input
                type="checkbox"
                checked={autoStart}
                onChange={(event) => setAutoStart(event.target.checked)}
                aria-label="Auto-start codebase server"
                className="h-4 w-4 rounded border-zinc-300 text-blue-600 focus:ring-blue-500"
              />
              Auto-start after upload and refresh dependencies on every start
            </label>
          )}
        </div>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileCode size={18} aria-hidden="true" /> Single-file MCP Server
            </CardTitle>
          </CardHeader>
          <form className="space-y-4" onSubmit={createFromEditor}>
            <div className="grid gap-4 md:grid-cols-2">
              <label className="block space-y-1.5">
                <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200">Server name</span>
                <input
                  value={serverName}
                  onChange={(event) => setServerName(event.target.value)}
                  placeholder="my-server"
                  className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none focus:ring-2 focus:ring-blue-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100 transition-colors"
                  aria-label="Single-file server name"
                />
              </label>
              <label className="block space-y-1.5">
                <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200">Description</span>
                <input
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="Optional description"
                  className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none focus:ring-2 focus:ring-blue-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100 transition-colors"
                  aria-label="Single-file server description"
                />
              </label>
            </div>

            <label className="block space-y-1.5">
              <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200">Python code</span>
              <textarea
                value={code}
                onChange={(event) => setCode(event.target.value)}
                spellCheck={false}
                className="min-h-80 w-full rounded-lg border border-zinc-300 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-950 px-4 py-3 font-mono text-sm leading-6 text-zinc-800 dark:text-zinc-100 outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
                aria-label="Single-file MCP server Python code"
              />
            </label>

            <label className="block space-y-1.5">
              <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
                manifest.json
              </span>
              <textarea
                value={manifestJson}
                onChange={(event) => setManifestJson(event.target.value)}
                spellCheck={false}
                className="min-h-56 w-full rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 px-3 py-2 font-mono text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
                aria-label="Single-file server manifest JSON"
              />
            </label>

            <label className="block space-y-1.5">
              <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
                requirements.txt
              </span>
              <textarea
                value={requirements}
                onChange={(event) => setRequirements(event.target.value)}
                spellCheck={false}
                className="min-h-24 w-full rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 px-3 py-2 font-mono text-sm text-zinc-900 dark:text-zinc-100 outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
                aria-label="Single-file server requirements"
              />
            </label>

            <label className="flex items-center justify-between gap-4 rounded-lg border border-zinc-200 dark:border-zinc-800 p-3">
              <span>
                <span className="block text-sm font-medium text-zinc-800 dark:text-zinc-200">
                  Auto-start after creation
                </span>
                <span className="block text-xs text-zinc-500 dark:text-zinc-400">
                  Creates a venv, installs requirements, and starts the server immediately.
                </span>
              </span>
              <input
                type="checkbox"
                checked={autoStart}
                onChange={(event) => setAutoStart(event.target.checked)}
                aria-label="Auto-start single-file server"
                className="h-4 w-4 rounded border-zinc-300 text-blue-600 focus:ring-blue-500"
              />
            </label>

            <div className="flex justify-end">
              <Button type="submit" loading={creating}>Create Server</Button>
            </div>
          </form>
        </Card>
      )}

      {/* Error */}
      {error && (
        <div className="flex items-start gap-2 p-4 rounded-xl border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/30 text-red-700 dark:text-red-300">
          <XCircle size={16} className="shrink-0 mt-0.5" aria-hidden="true" />
          <div>
            <p className="text-sm font-medium text-red-700 dark:text-red-200">Deployment failed</p>
            <p className="text-xs mt-1 whitespace-pre-wrap">{error}</p>
          </div>
        </div>
      )}

      {/* Success */}
      {result && (
        <div className="flex items-start gap-2 p-4 rounded-xl border border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300">
          <CheckCircle size={16} className="shrink-0 mt-0.5" aria-hidden="true" />
          <div className="min-w-0">
            <p className="text-sm font-medium text-emerald-800 dark:text-emerald-200">{result.message}</p>
            <div className="mt-2 flex items-center gap-2 text-sm">
              <span className="font-mono text-emerald-700 dark:text-emerald-300">{result.server.name}</span>
              <StatusBadge status={result.server.status} />
            </div>
            <div className="mt-2 text-xs text-emerald-600 dark:text-emerald-400">
              MCP endpoint:{' '}
              <code className="font-mono">{serviceUrl}/mcp/server/{result.server.name}</code>
            </div>
          </div>
        </div>
      )}

      {/* Format docs */}
      <Card>
        <CardHeader>
          <CardTitle>ZIP Package Format</CardTitle>
        </CardHeader>
        <div className="text-sm text-zinc-600 dark:text-zinc-400 space-y-3">
          <p>Your ZIP must contain the following files at the root:</p>
          <pre className="text-xs font-mono bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-md p-3 text-zinc-700 dark:text-zinc-300 leading-6">
{`server.zip
|-- manifest.json     required
|-- requirements.txt  Python dependencies, or pyproject.toml
|-- package.json      JS/TS dependencies
+-- main.py           or index.js / src/index.ts entrypoint`}
          </pre>
          <p>
            Language is detected automatically from{' '}
            <code className="text-blue-600 dark:text-blue-400 text-xs">manifest.language</code>,
            the entrypoint extension, or{' '}
            <code className="text-blue-600 dark:text-blue-400 text-xs">package.json</code>.
            Python packages use requirements metadata; JavaScript and TypeScript packages use
            package metadata and run through Node/npm/npx.
          </p>
          <p>
            Minimal{' '}
            <code className="text-blue-600 dark:text-blue-400 text-xs">manifest.json</code>:
          </p>
          <pre className="text-xs font-mono bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-md p-3 text-zinc-700 dark:text-zinc-300 leading-6">
{`{
  "name": "my-server",
  "version": "1.0.0",
  "entrypoint": "main.py",
  "module": "main"
}`}
          </pre>
          <p>Minimal JavaScript package manifest:</p>
          <pre className="text-xs font-mono bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-md p-3 text-zinc-700 dark:text-zinc-300 leading-6">
{`{
  "name": "my-node-server",
  "version": "1.0.0",
  "entrypoint": "index.js"
}`}
          </pre>
          <p>
            See{' '}
            <a
              href="/docs/server-manifest.md"
              className="text-blue-600 dark:text-blue-400 hover:underline"
              target="_blank"
              rel="noreferrer"
            >
              docs/server-manifest.md
            </a>{' '}
            for the full specification.
          </p>
        </div>
      </Card>
    </div>
  )
}
