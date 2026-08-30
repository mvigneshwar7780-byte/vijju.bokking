import { useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Operator } from '@/api/endpoints'
import { ErrorNote, Spinner } from '@/components/ui'
import { MoviePicker } from '@/components/MoviePicker'
import { rupees, showDate, showTime } from '@/lib/format'

type Ctx = { cinemaId: string }

function isoDate(offsetDays = 0): string {
  const d = new Date()
  d.setDate(d.getDate() + offsetDays)
  return d.toISOString().slice(0, 10)
}

/** Schedule showtimes and price them per seat tier. */
export function OperatorShows() {
  const { cinemaId } = useOutletContext<Ctx>()
  const qc = useQueryClient()
  const [from, setFrom] = useState(isoDate())
  const [to, setTo] = useState(isoDate(7))
  const [creating, setCreating] = useState(false)

  const shows = useQuery({
    queryKey: ['op-shows', cinemaId, from, to],
    queryFn: () => Operator.shows(cinemaId, from, to),
  })
  const screens = useQuery({
    queryKey: ['op-screens', cinemaId],
    queryFn: () => Operator.screens(cinemaId),
  })
  const categories = useQuery({
    queryKey: ['op-categories', cinemaId],
    queryFn: () => Operator.seatCategories(cinemaId),
  })

  const cancel = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      Operator.cancelShow(id, reason),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['op-shows', cinemaId] }),
  })

  if (shows.isPending) return <Spinner label="Loading schedule" />

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end gap-3">
        <div><label className="label">From</label>
          <input type="date" className="field w-40" value={from}
            onChange={(e) => setFrom(e.target.value)} /></div>
        <div><label className="label">To</label>
          <input type="date" className="field w-40" value={to}
            onChange={(e) => setTo(e.target.value)} /></div>
        <button className="btn-primary ml-auto" onClick={() => setCreating((v) => !v)}>
          {creating ? 'Close' : 'Schedule a show'}
        </button>
      </div>

      {creating && (
        <ShowForm
          cinemaId={cinemaId}
          screens={screens.data ?? []}
          categories={categories.data ?? []}
          onDone={() => {
            setCreating(false)
            void qc.invalidateQueries({ queryKey: ['op-shows', cinemaId] })
          }}
        />
      )}

      {cancel.error && <ErrorNote error={cancel.error} />}

      {shows.data && shows.data.length === 0 ? (
        <div className="card p-8 text-center text-sm text-ink-500">
          Nothing scheduled in this range.
        </div>
      ) : (
        <div className="space-y-2">
          {shows.data?.map((show) => (
            <article key={show.id} className="card p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-semibold">{show.movie_title}</h3>
                    <span className="chip">{show.format_code}</span>
                    <span
                      className={clsx(
                        'chip',
                        show.status === 'open' && 'border-emerald-800 text-emerald-300',
                        show.status === 'cancelled' && 'border-red-900 text-red-300',
                      )}
                    >
                      {show.status}
                    </span>
                  </div>
                  <p className="mt-0.5 text-sm text-ink-300">
                    {showDate(show.starts_at)} · {showTime(show.starts_at)} ·{' '}
                    {show.screen_name} · {show.audio_language}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {show.prices.map((p) => (
                      <span key={p.seat_category_id} className="chip">
                        {p.category} {rupees(p.price_minor, { compact: true })}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="text-right">
                  <p className="text-sm font-semibold">
                    {show.booked_seats}/{show.total_seats} sold
                  </p>
                  <p className="text-xs text-ink-500">
                    {show.occupancy_percent}% · {rupees(show.gross_minor, { compact: true })}
                  </p>
                  {show.status !== 'cancelled' && (
                    <button
                      className="btn-ghost mt-2 !py-1 !text-[11px]"
                      onClick={() => {
                        const reason = window.prompt('Why is this show being cancelled?')
                        if (reason) cancel.mutate({ id: show.id, reason })
                      }}
                    >
                      Cancel show
                    </button>
                  )}
                </div>
              </div>

              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-ink-850">
                <div
                  className="h-full rounded-full bg-brand-500"
                  style={{ width: `${show.occupancy_percent}%` }}
                />
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}

function ShowForm({
  cinemaId, screens, categories, onDone,
}: {
  cinemaId: string
  screens: { id: string; name: string; total_seats: number }[]
  categories: { id: string; name: string; default_price_minor: number }[]
  onDone: () => void
}) {
  const [prices, setPrices] = useState<Record<string, number>>(
    Object.fromEntries(categories.map((c) => [c.id, c.default_price_minor / 100])),
  )
  const [movieId, setMovieId] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) => Operator.createShow(cinemaId, body),
    onSuccess: onDone,
  })

  const usable = screens.filter((s) => s.total_seats > 0)

  return (
    <form
      className="card space-y-3 p-4"
      onSubmit={(e) => {
        e.preventDefault()
        const f = new FormData(e.currentTarget)
        if (!movieId) return
        create.mutate({
          screen_id: String(f.get('screen')),
          movie_id: movieId,
          format_code: String(f.get('format')),
          show_date: String(f.get('date')),
          start_time: `${String(f.get('time'))}:00`,
          prices: categories.map((c) => ({
            seat_category_id: c.id,
            price_minor: Math.round((prices[c.id] ?? 0) * 100),
          })),
        })
      }}
    >
      {usable.length === 0 && (
        <p className="text-sm text-amber-300">
          No screen has a seating plan yet. Add one under “Screens & seating” first.
        </p>
      )}

      <div>
        <label className="label">Film</label>
        <MoviePicker value={movieId} onChange={(id) => setMovieId(id)} />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <div><label className="label">Screen</label>
          <select name="screen" required className="field">
            {usable.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select></div>
        <div><label className="label">Format</label>
          <input name="format" defaultValue="2D" className="field" /></div>
        <div><label className="label">Date</label>
          <input name="date" type="date" required className="field"
            defaultValue={isoDate(1)} /></div>
        <div><label className="label">Start time</label>
          <input name="time" type="time" required className="field" defaultValue="18:30" /></div>
      </div>

      <div>
        <p className="label">Price per seat tier</p>
        <p className="mb-2 text-xs text-ink-500">
          Every tier in the screen needs a price — this is what makes the same film
          cost different amounts at different halls.
        </p>
        <div className="flex flex-wrap gap-2">
          {categories.map((c) => (
            <div key={c.id}>
              <label className="label">{c.name} (₹)</label>
              <input
                type="number" min="0" className="field w-28"
                value={prices[c.id] ?? 0}
                onChange={(e) =>
                  setPrices((p) => ({ ...p, [c.id]: Number(e.target.value) }))
                }
              />
            </div>
          ))}
        </div>
      </div>

      {create.error && <ErrorNote error={create.error} />}
      <button
        className="btn-primary"
        disabled={create.isPending || usable.length === 0 || !movieId}
      >
        {create.isPending ? 'Scheduling…' : 'Schedule show'}
      </button>
      {!movieId && (
        <p className="text-[11px] text-amber-300">Choose a film to continue.</p>
      )}
    </form>
  )
}
