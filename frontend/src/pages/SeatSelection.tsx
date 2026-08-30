import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Seats } from '@/api/endpoints'
import { ApiClientError } from '@/api/client'
import { SeatMap } from '@/components/SeatMap'
import { ErrorNote, Spinner, Stepper } from '@/components/ui'
import { rupees, showDateTime } from '@/lib/format'
import type { Seat } from '@/api/types'

export function SeatSelection() {
  const { showId = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<Map<string, Seat>>(new Map())
  const [notice, setNotice] = useState<string | null>(null)

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ['seatmap', showId],
    queryFn: () => Seats.map(showId),
    // Seats are contended state — a stale map means clicking a taken seat.
    // The hold request is still the authority; this just keeps the UI honest.
    refetchInterval: 15_000,
    staleTime: 5_000,
  })

  const subtotal = useMemo(
    () => [...selected.values()].reduce((sum, s) => sum + s.price_minor, 0),
    [selected],
  )

  const hold = useMutation({
    mutationFn: () => Seats.hold(showId, [...selected.keys()]),
    onSuccess: (h) => navigate(`/checkout/${h.hold_id}`, { state: { showId } }),
    onError: (err) => {
      setNotice(err instanceof ApiClientError ? err.message : 'Could not hold those seats.')
      // Whatever happened, our view of the map is now out of date.
      void queryClient.invalidateQueries({ queryKey: ['seatmap', showId] })
      setSelected(new Map())
    },
  })

  if (isPending) return <Spinner label="Loading seat map" />
  if (error) return <ErrorNote error={error} onRetry={() => void refetch()} />
  if (!data) return null

  const atLimit = selected.size >= data.max_seats_per_booking

  const toggle = (seat: Seat) => {
    setNotice(null)
    setSelected((prev) => {
      const next = new Map(prev)
      if (next.has(seat.seat_id)) next.delete(seat.seat_id)
      else if (next.size < data.max_seats_per_booking) next.set(seat.seat_id, seat)
      return next
    })
  }

  return (
    <div className="space-y-6">
      <Stepper step={1} />

      <header>
        <h1 className="text-xl font-bold tracking-tight">{data.movie_title}</h1>
        <p className="text-sm text-ink-500">
          {data.cinema_name} · {data.screen_name} · {showDateTime(data.starts_at)}
        </p>
      </header>

      {notice && (
        <div className="card border-amber-900/60 bg-amber-950/30 p-3 text-sm text-amber-200">
          {notice}
        </div>
      )}

      <div className="card p-4 sm:p-6">
        <SeatMap
          data={data}
          selected={new Set(selected.keys())}
          onToggle={toggle}
          disabled={hold.isPending}
        />
      </div>

      <div className="sticky bottom-4 z-20">
        <div className="card flex flex-wrap items-center gap-4 p-4 shadow-2xl">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">
              {selected.size === 0
                ? 'Select your seats'
                : `${selected.size} seat${selected.size > 1 ? 's' : ''} · ${[...selected.values()]
                    .map((s) => s.label)
                    .sort()
                    .join(', ')}`}
            </p>
            <p className="text-xs text-ink-500">
              {selected.size > 0
                ? `Tickets ${rupees(subtotal)} — fees and taxes calculated next`
                : `${data.available_seats} of ${data.total_seats} seats free${
                    atLimit ? '' : ''
                  }`}
            </p>
          </div>
          <button
            className="btn-primary"
            disabled={selected.size === 0 || hold.isPending}
            onClick={() => hold.mutate()}
          >
            {hold.isPending ? 'Holding seats…' : 'Continue'}
          </button>
        </div>
      </div>
    </div>
  )
}
