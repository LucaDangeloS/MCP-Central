import { cn } from '@/lib/utils'
import { ChevronDown } from 'lucide-react'
import { type SelectHTMLAttributes, forwardRef } from 'react'

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  className?: string
}

/**
 * A styled <select> wrapper that matches the design system in both light and dark mode.
 * Drop-in replacement for raw <select> elements — accepts all native select props.
 */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, children, ...props }, ref) => (
    <div className="relative w-full">
      <select
        ref={ref}
        className={cn(
          // Layout
          'w-full appearance-none rounded-md border px-3 py-2 pr-9 text-sm',
          // Light mode
          'border-zinc-300 bg-white text-zinc-900',
          'hover:border-zinc-400',
          // Dark mode
          'dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-100',
          'dark:hover:border-zinc-500',
          // Focus
          'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent',
          'dark:focus:ring-blue-400',
          // Disabled
          'disabled:opacity-50 disabled:cursor-not-allowed',
          // Transition
          'transition-colors',
          className,
        )}
        {...props}
      >
        {children}
      </select>
      {/* Custom chevron icon — replaces the native OS arrow */}
      <ChevronDown
        size={15}
        className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-400 dark:text-zinc-500"
        aria-hidden="true"
      />
    </div>
  ),
)
Select.displayName = 'Select'
