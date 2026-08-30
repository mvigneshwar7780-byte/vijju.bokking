import clsx from 'clsx'
import type { ReactNode } from 'react'

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-16 text-ink-300">
      <span className="size-5 animate-spin rounded-full border-2 border-ink-700 border-t-brand-500" />
      <span className="text-sm">{label}…</span>
    </div>
  )
}

export function ErrorNote({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : 'Something went wrong.'
  return (
    <div className="card border-red-900/60 bg-red-950/30 p-4">
      <p className="text-sm text-red-200">{message}</p>
      {onRetry && (
        <button className="btn-ghost mt-3 !py-1.5 !text-xs" onClick={onRetry}>Try again</button>
      )}
    </div>
  )
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="card p-10 text-center">
      <p className="font-semibold">{title}</p>
      {hint && <p className="mt-1 text-sm text-ink-300">{hint}</p>}
    </div>
  )
}

export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'good' | 'warn' | 'bad' }) {
  return (
    <span
      className={clsx('chip', {
        'border-emerald-800 text-emerald-300': tone === 'good',
        'border-amber-800 text-amber-300': tone === 'warn',
        'border-red-900 text-red-300': tone === 'bad',
      })}
    >
      {children}
    </span>
  )
}

export function Stepper({ step }: { step: 1 | 2 | 3 | 4 }) {
  const steps = ['Seats', 'Review', 'Payment', 'Ticket']
  return (
    <ol className="mb-6 flex items-center gap-2 text-xs">
      {steps.map((label, i) => {
        const n = (i + 1) as 1 | 2 | 3 | 4
        return (
          <li key={label} className="flex items-center gap-2">
            <span
              className={clsx(
                'flex size-6 items-center justify-center rounded-full font-semibold',
                n < step && 'bg-emerald-900 text-emerald-200',
                n === step && 'bg-brand-500 text-white',
                n > step && 'border border-ink-700 text-ink-500',
              )}
            >
              {n < step ? '✓' : n}
            </span>
            <span className={clsx(n === step ? 'text-ink-100' : 'text-ink-500')}>{label}</span>
            {i < steps.length - 1 && <span className="mx-1 h-px w-6 bg-ink-700" />}
          </li>
        )
      })}
    </ol>
  )
}
