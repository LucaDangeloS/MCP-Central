import { useEffect, useState } from 'react'
import { statsApi, serversApi, logsApi, type Stats, type Server, type LogEntry } from '@/lib/api'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { StatusBadge } from '@/components/ui/badge'
import { formatDate } from '@/lib/utils'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { Server as ServerIcon, AlertTriangle, Activity, Clock } from 'lucide-react'

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [servers, setServers] = useState<Server[]>([])
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [loading, setLoading] = useState(true)
  // Track theme for chart colours
  const [isDark, setIsDark] = useState(() => document.documentElement.classList.contains('dark'))

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDark(document.documentElement.classList.contains('dark'))
    })
    observer.observe(document.documentElement, { attributeFilter: ['class'] })
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const load = async () => {
      const [s, srv, l] = await Promise.all([
        statsApi.get(),
        serversApi.list({ page_size: 10 }),
        logsApi.query({ level: 'error', page_size: 10 }),
      ])
      setStats(s.data)
      setServers(srv.data)
      setLogs(l.data)
      setLoading(false)
    }
    load().catch(console.error)
  }, [])

  if (loading) return <div className="text-zinc-500 text-sm">Loading...</div>

  const activityData = Object.entries(stats?.logs.activity_last_24h ?? {}).map(([name, count]) => ({
    name: name.length > 12 ? name.slice(0, 12) + '…' : name,
    logs: count,
  }))

  // Theme-aware chart colours
  const tickColor = isDark ? '#71717a' : '#52525b'
  const tooltipBg = isDark ? '#18181b' : '#ffffff'
  const tooltipBorder = isDark ? '#3f3f46' : '#e4e4e7'
  const tooltipLabel = isDark ? '#e4e4e7' : '#18181b'
  const tooltipItem = isDark ? '#60a5fa' : '#2563eb'

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-100">Dashboard</h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-0.5">Overview of your MCP servers</p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard icon={ServerIcon} label="Total Servers" value={stats?.servers.total ?? 0} color="blue" />
        <StatCard icon={Activity} label="Running" value={stats?.servers.running ?? 0} color="emerald" />
        <StatCard icon={AlertTriangle} label="Errors" value={stats?.servers.error ?? 0} color="red" />
        <StatCard icon={Clock} label="Errors (1h)" value={stats?.logs.errors_last_hour ?? 0} color="amber" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Activity chart */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Log Activity (24h)</CardTitle>
          </CardHeader>
          {activityData.length === 0 ? (
            <p className="text-sm text-zinc-500 dark:text-zinc-500">No log activity in the last 24 hours.</p>
          ) : (
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={activityData} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                <XAxis dataKey="name" tick={{ fontSize: 11, fill: tickColor }} />
                <YAxis tick={{ fontSize: 11, fill: tickColor }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: tooltipBg,
                    border: `1px solid ${tooltipBorder}`,
                    borderRadius: 8,
                    boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
                  }}
                  labelStyle={{ color: tooltipLabel, fontSize: 12 }}
                  itemStyle={{ color: tooltipItem, fontSize: 12 }}
                />
                <Bar dataKey="logs" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>

        {/* Recent errors */}
        <Card>
          <CardHeader>
            <CardTitle>Recent Errors</CardTitle>
          </CardHeader>
          <div className="space-y-2 overflow-y-auto max-h-52">
            {logs.length === 0 ? (
              <p className="text-sm text-zinc-500">No recent errors.</p>
            ) : (
              logs.map((l) => (
                <div key={l.id} className="text-xs border-l-2 border-red-500 dark:border-red-700 pl-2 py-0.5">
                  <div className="text-red-600 dark:text-red-300 font-medium truncate">{l.server_name}</div>
                  <div className="text-zinc-600 dark:text-zinc-400 truncate">{l.message}</div>
                  <div className="text-zinc-400 dark:text-zinc-600">{formatDate(l.timestamp)}</div>
                </div>
              ))
            )}
          </div>
        </Card>
      </div>

      {/* Server list */}
      <Card>
        <CardHeader>
          <CardTitle>Servers</CardTitle>
        </CardHeader>
        <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {servers.length === 0 ? (
            <p className="text-sm text-zinc-500 py-2">No servers registered yet. Upload a ZIP to get started.</p>
          ) : (
            servers.map((s) => (
              <div key={s.id} className="py-3 flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100">{s.name}</div>
                  <div className="text-xs text-zinc-500">{s.description || s.entrypoint_module}</div>
                </div>
                <div className="flex items-center gap-3">
                  {s.restart_count > 0 && (
                    <span className="text-xs text-amber-600 dark:text-amber-400">
                      {s.restart_count} restart{s.restart_count !== 1 ? 's' : ''}
                    </span>
                  )}
                  <StatusBadge status={s.status} />
                </div>
              </div>
            ))
          )}
        </div>
      </Card>
    </div>
  )
}

function StatCard({
  icon: Icon,
  label,
  value,
  color,
}: {
  icon: React.ElementType
  label: string
  value: number
  color: 'blue' | 'emerald' | 'red' | 'amber'
}) {
  const colors = {
    blue: 'text-blue-600 bg-blue-100 dark:text-blue-400 dark:bg-blue-900/30',
    emerald: 'text-emerald-600 bg-emerald-100 dark:text-emerald-400 dark:bg-emerald-900/30',
    red: 'text-red-600 bg-red-100 dark:text-red-400 dark:bg-red-900/30',
    amber: 'text-amber-600 bg-amber-100 dark:text-amber-400 dark:bg-amber-900/30',
  }
  return (
    <Card className="flex items-center gap-4">
      <div className={`p-2.5 rounded-lg ${colors[color]}`} aria-hidden="true">
        <Icon size={18} />
      </div>
      <div>
        <div className="text-2xl font-bold text-zinc-900 dark:text-zinc-100">{value}</div>
        <div className="text-xs text-zinc-500 dark:text-zinc-400">{label}</div>
      </div>
    </Card>
  )
}
