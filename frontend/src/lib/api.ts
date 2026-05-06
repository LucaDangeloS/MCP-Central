/**
 * Typed API client — all backend communication goes through here.
 * Never use fetch() directly in components or hooks.
 */

const BASE = '/api/v1'

// ------------------------------------------------------------------ //
// Types                                                                //
// ------------------------------------------------------------------ //

export interface Meta {
  timestamp: string
  total?: number
  page?: number
  page_size?: number
}

export interface ApiResponse<T> {
  data: T
  meta: Meta
}

export interface Server {
  id: number
  name: string
  description: string
  path: string
  entrypoint_module: string
  env_vars: Record<string, string>
  disabled_tools: string[]
  python_version_constraint: string
  auto_start: boolean
  restart_on_error: boolean
  status: 'stopped' | 'starting' | 'running' | 'error' | 'restarting'
  pid: number | null
  restart_count: number
  last_error: string | null
  last_error_at: string | null
  group_id: number | null
  created_at: string
  updated_at: string
}

export interface McpTool {
  name: string
  description?: string
  inputSchema?: {
    type: string
    properties?: Record<string, { type?: string; description?: string }>
    required?: string[]
  }
}

export interface Group {
  id: number
  name: string
  description: string
  require_api_key: boolean
  hidden_tools: string[]
  rate_limit_rpm: number
  created_at: string
  updated_at: string
}

export interface ApiKey {
  id: number
  label: string
  description: string
  key_prefix: string
  group_id: number | null
  server_id: number | null
  created_at: string
  deleted_at: string | null
}

export interface ApiKeyCreated extends ApiKey {
  plaintext_key: string
}

export interface LogEntry {
  id: number
  server_name: string
  stream: 'stdout' | 'stderr' | 'hub'
  level: 'debug' | 'info' | 'warning' | 'error' | 'critical'
  message: string
  raw: string
  timestamp: string
}

export interface Stats {
  servers: {
    total: number
    running: number
    error: number
    stopped: number
    by_status: Record<string, number>
  }
  logs: {
    errors_last_hour: number
    activity_last_24h: Record<string, number>
  }
}

// ------------------------------------------------------------------ //
// Auth                                                                 //
// ------------------------------------------------------------------ //

let _token: string | null = localStorage.getItem('access_token')

export function setToken(token: string) {
  _token = token
  localStorage.setItem('access_token', token)
}

export function clearToken() {
  _token = null
  localStorage.removeItem('access_token')
}

export function getToken(): string | null {
  return _token
}

// ------------------------------------------------------------------ //
// Fetch wrapper                                                        //
// ------------------------------------------------------------------ //

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  }

  if (_token) {
    headers['Authorization'] = `Bearer ${_token}`
  }

  const res = await fetch(`${BASE}${path}`, { ...options, headers })

  if (res.status === 401) {
    clearToken()
    window.location.href = '/login'
    throw new Error('Unauthorized')
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(
      typeof body.detail === 'string'
        ? body.detail
        : JSON.stringify(body.detail ?? body)
    )
  }

  if (res.status === 204) return undefined as T
  return res.json()
}

// ------------------------------------------------------------------ //
// Auth API                                                             //
// ------------------------------------------------------------------ //

export const authApi = {
  login: async (username: string, password: string): Promise<{ access_token: string; refresh_token: string }> => {
    const form = new URLSearchParams({ username, password })
    const res = await fetch(`${BASE}/auth/token`, {
      method: 'POST',
      body: form,
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
    if (!res.ok) throw new Error('Invalid credentials')
    return res.json()
  },
}

// ------------------------------------------------------------------ //
// Servers API                                                          //
// ------------------------------------------------------------------ //

export const serversApi = {
  list: (params?: { page?: number; page_size?: number; group_id?: number }) => {
    const q = new URLSearchParams()
    if (params?.page) q.set('page', String(params.page))
    if (params?.page_size) q.set('page_size', String(params.page_size))
    if (params?.group_id) q.set('group_id', String(params.group_id))
    return request<ApiResponse<Server[]>>(`/servers?${q}`)
  },
  get: (name: string) => request<ApiResponse<Server>>(`/servers/${name}`),
  create: (data: { name: string; path: string; description?: string; entrypoint_module?: string; auto_start?: boolean; restart_on_error?: boolean; group_id?: number; env_vars?: Record<string, string> }) =>
    request<ApiResponse<Server>>('/servers', { method: 'POST', body: JSON.stringify(data) }),
  update: (name: string, data: Partial<Pick<Server, 'description' | 'entrypoint_module' | 'env_vars' | 'disabled_tools' | 'auto_start' | 'restart_on_error' | 'group_id'>>) =>
    request<ApiResponse<Server>>(`/servers/${name}`, { method: 'PATCH', body: JSON.stringify(data) }),
  delete: (name: string) => request<void>(`/servers/${name}`, { method: 'DELETE' }),
  start: (name: string) => request<ApiResponse<Server>>(`/servers/${name}/start`, { method: 'POST' }),
  stop: (name: string) => request<ApiResponse<Server>>(`/servers/${name}/stop`, { method: 'POST' }),
  restart: (name: string) => request<ApiResponse<Server>>(`/servers/${name}/restart`, { method: 'POST' }),
  tools: (name: string) => request<ApiResponse<McpTool[]>>(`/servers/${name}/tools`),
}

// ------------------------------------------------------------------ //
// Groups API                                                           //
// ------------------------------------------------------------------ //

export const groupsApi = {
  list: () => request<ApiResponse<Group[]>>('/groups'),
  get: (name: string) => request<ApiResponse<Group>>(`/groups/${name}`),
  create: (data: { name: string; description?: string; require_api_key?: boolean; rate_limit_rpm?: number }) =>
    request<ApiResponse<Group>>('/groups', { method: 'POST', body: JSON.stringify(data) }),
  update: (name: string, data: Partial<Group>) =>
    request<ApiResponse<Group>>(`/groups/${name}`, { method: 'PATCH', body: JSON.stringify(data) }),
  delete: (name: string) => request<void>(`/groups/${name}`, { method: 'DELETE' }),
}

// ------------------------------------------------------------------ //
// API Keys                                                             //
// ------------------------------------------------------------------ //

export const keysApi = {
  list: (params?: { group_id?: number; server_id?: number }) => {
    const q = new URLSearchParams()
    if (params?.group_id) q.set('group_id', String(params.group_id))
    if (params?.server_id) q.set('server_id', String(params.server_id))
    const suffix = q.toString()
    return request<ApiResponse<ApiKey[]>>(`/keys${suffix ? `?${suffix}` : ''}`)
  },
  create: (data: { label: string; description?: string; group_id?: number; server_id?: number }) =>
    request<ApiResponse<ApiKeyCreated>>('/keys', { method: 'POST', body: JSON.stringify(data) }),
  revoke: (id: number) => request<void>(`/keys/${id}`, { method: 'DELETE' }),
}

// ------------------------------------------------------------------ //
// Logs API                                                             //
// ------------------------------------------------------------------ //

export const logsApi = {
  query: (params?: { server_name?: string; level?: string; stream?: string; page?: number; page_size?: number }) => {
    const q = new URLSearchParams()
    if (params?.server_name) q.set('server_name', params.server_name)
    if (params?.level) q.set('level', params.level)
    if (params?.stream) q.set('stream', params.stream)
    if (params?.page) q.set('page', String(params.page))
    if (params?.page_size) q.set('page_size', String(params.page_size))
    return request<ApiResponse<LogEntry[]>>(`/logs?${q}`)
  },
  streamUrl: (server_name?: string) => {
    const q = new URLSearchParams()
    if (server_name) q.set('server_name', server_name)
    const suffix = q.toString()
    return `${BASE}/logs/stream${suffix ? `?${suffix}` : ''}`
  },
}

// ------------------------------------------------------------------ //
// Stats API                                                            //
// ------------------------------------------------------------------ //

export const statsApi = {
  get: () => request<ApiResponse<Stats>>('/stats'),
}

// ------------------------------------------------------------------ //
// Upload API                                                           //
// ------------------------------------------------------------------ //

export const uploadApi = {
  upload: async (file: File): Promise<ApiResponse<{ server: Server; manifest: Record<string, unknown>; message: string }>> => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${BASE}/upload`, {
      method: 'POST',
      headers: _token ? { Authorization: `Bearer ${_token}` } : {},
      body: form,
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body))
    }
    return res.json()
  },
  createSingleFile: (data: {
    name: string
    description?: string
    code: string
    requirements?: string
    env_vars?: Record<string, string>
    auto_start?: boolean
  }) => request<ApiResponse<{ server: Server; manifest: Record<string, unknown>; message: string }>>(
    '/upload/single-file',
    { method: 'POST', body: JSON.stringify(data) },
  ),
}
