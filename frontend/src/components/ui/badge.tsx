import { cn } from '@/lib/utils'

type BadgeVariant = 'default' | 'success' | 'warning' | 'error' | 'info'

const variants: Record<BadgeVariant, string> = {
  default:
    'bg-zinc-100 text-zinc-700 border border-zinc-200 dark:bg-zinc-700 dark:text-zinc-200 dark:border-zinc-600',
  success:
    'bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-900/60 dark:text-emerald-300 dark:border-emerald-700/50',
  warning:
    'bg-amber-50 text-amber-700 border border-amber-200 dark:bg-amber-900/60 dark:text-amber-300 dark:border-amber-700/50',
  error:
    'bg-red-50 text-red-700 border border-red-200 dark:bg-red-900/60 dark:text-red-300 dark:border-red-700/50',
  info:
    'bg-blue-50 text-blue-700 border border-blue-200 dark:bg-blue-900/60 dark:text-blue-300 dark:border-blue-700/50',
}

interface BadgeProps {
  children: React.ReactNode
  variant?: BadgeVariant
  className?: string
}

export function Badge({ children, variant = 'default', className }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium',
        variants[variant],
        className,
      )}
    >
      {children}
    </span>
  )
}

const statusVariantMap: Record<string, BadgeVariant> = {
  running: 'success',
  starting: 'info',
  restarting: 'warning',
  stopped: 'default',
  error: 'error',
}

const statusLabelMap: Record<string, string> = {
  running: 'Running',
  starting: 'Starting',
  restarting: 'Restarting',
  stopped: 'Stopped',
  error: 'Error',
}

export function StatusBadge({ status }: { status: string }) {
  const variant = statusVariantMap[status] ?? 'default'
  const label = statusLabelMap[status] ?? (status.charAt(0).toUpperCase() + status.slice(1))
  return <Badge variant={variant}>{label}</Badge>
}
