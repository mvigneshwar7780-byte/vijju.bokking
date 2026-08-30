import { useEffect, useState } from 'react'
import clsx from 'clsx'
import { countdown } from '@/lib/format'

/**
 * The countdown against a hold's expiry.
 *
 * It ticks off `expires_at` (a server timestamp), not off a client-side
 * duration: a tab that was backgrounded for five minutes must show the *real*
 * remaining time when it wakes, not five minutes of un-ticked clock.
 * The server re-checks the deadline on every mutation regardless -- this is a
 * display, never an authority.
 */
export function HoldTimer({ expiresAt, onExpire }: { expiresAt: string; onExpire?: () => void }) {
  const [remaining, setRemaining] = useState(() =>
    Math.max(0, Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000)),
  )

  useEffect(() => {
    const tick = () => {
      const next = Math.max(0, Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000))
      setRemaining(next)
      if (next === 0) onExpire?.()
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [expiresAt, onExpire])

  const urgent = remaining <= 60

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 font-mono text-sm tabular-nums',
        urgent
          ? 'border-red-900 bg-red-950/40 text-red-300'
          : 'border-ink-700 bg-ink-850 text-ink-100',
      )}
      role="timer"
      aria-live={urgent ? 'assertive' : 'off'}
    >
      <span aria-hidden>⏳</span>
      {countdown(remaining)}
    </span>
  )
}
