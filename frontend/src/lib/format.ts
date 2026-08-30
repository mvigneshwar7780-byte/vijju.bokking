/** Money and time formatting.
 *
 *  Money arrives from the API as integer paise and is *only* formatted here --
 *  the UI never does arithmetic on it. Every total the user sees was computed
 *  server-side; recomputing client-side is how a display drifts from an invoice.
 */
export function rupees(minor: number, opts: { compact?: boolean } = {}): string {
  const value = minor / 100
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: opts.compact && Number.isInteger(value) ? 0 : 2,
    minimumFractionDigits: opts.compact && Number.isInteger(value) ? 0 : 2,
  }).format(value)
}

export function showTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-IN', {
    hour: 'numeric', minute: '2-digit', hour12: true,
  })
}

export function showDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-IN', {
    weekday: 'short', day: 'numeric', month: 'short',
  })
}

export function showDateTime(iso: string): string {
  return `${showDate(iso)}, ${showTime(iso)}`
}

export function dayLabel(isoDate: string): { weekday: string; day: string; month: string } {
  const d = new Date(`${isoDate}T00:00:00`)
  return {
    weekday: d.toLocaleDateString('en-IN', { weekday: 'short' }).toUpperCase(),
    day: String(d.getDate()),
    month: d.toLocaleDateString('en-IN', { month: 'short' }).toUpperCase(),
  }
}

export function runtime(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return h ? `${h}h ${m}m` : `${m}m`
}

export function countdown(seconds: number): string {
  const m = Math.floor(Math.max(seconds, 0) / 60)
  const s = Math.max(seconds, 0) % 60
  return `${m}:${String(s).padStart(2, '0')}`
}
