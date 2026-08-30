import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Showtimes as ShowtimesApi } from '@/api/endpoints'
import { useSession } from '@/store/session'
import { Empty, ErrorNote, Spinner } from '@/components/ui'
import { dayLabel, rupees, showTime } from '@/lib/format'
import type { ShowCard } from '@/api/types'

const BAND_STYLE: Record<ShowCard['availability_band'], string> = {
  available: 'border-emerald-800/70 text-emerald-300 hover:bg-emerald-950/40',
  filling_fast: 'border-amber-800/70 text-amber-300 hover:bg-amber-950/40',
  almost_full: 'border-red-900/70 text-red-300 hover:bg-red-950/40',
  sold_out: 'border-ink-800 text-ink-600 cursor-not-allowed',
}

const BAND_LABEL: Record<ShowCard['availability_band'], string> = {
  available: 'Available',
  filling_fast: 'Filling fast',
  almost_full: 'Almost full',
  sold_out: 'Sold out',
}

export function Showtimes() {
  const { movieId = '' } = useParams()
  const { city } = useSession()
  const [date, setDate] = useState<string | undefined>()

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ['showtimes', movieId, city?.id, date],
    queryFn: () => ShowtimesApi.board({ movie_id: movieId, city_id: city!.id, date }),
    enabled: Boolean(city),
  })

  if (isPending) return <Spinner label="Loading showtimes" />
  if (error) return <ErrorNote error={error} onRetry={() => void refetch()} />
  if (!data) return null

  return (
    <div className="space-y-6">
      <div>
        <Link to={`/movies/${movieId}`} className="text-sm text-ink-500 hover:text-ink-300">
          ← {data.movie_title}
        </Link>
        <h1 className="mt-1 text-2xl font-bold tracking-tight">Choose a showtime</h1>
        <p className="text-sm text-ink-500">{data.city_name}</p>
      </div>

      {data.available_dates.length > 0 && (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {data.available_dates.map((d) => {
            const { weekday, day, month } = dayLabel(d)
            const active = d === data.show_date
            return (
              <button
                key={d}
                onClick={() => setDate(d)}
                className={clsx(
                  'flex w-16 shrink-0 flex-col items-center rounded-lg border py-2 transition-colors',
                  active
                    ? 'border-brand-500 bg-brand-500 text-white'
                    : 'border-ink-800 text-ink-300 hover:border-ink-700',
                )}
              >
                <span className="text-[10px] font-medium">{weekday}</span>
                <span className="text-lg font-bold leading-none">{day}</span>
                <span className="text-[10px]">{month}</span>
              </button>
            )
          })}
        </div>
      )}

      {data.cinemas.length === 0 ? (
        <Empty
          title="No shows on this date"
          hint="Pick another date, or check back — schedules open a few days ahead."
        />
      ) : (
        <div className="space-y-4">
          {data.cinemas.map((cinema) => (
            <section key={cinema.cinema_id} className="card p-4">
              <header className="mb-3">
                <h2 className="font-semibold">{cinema.cinema_name}</h2>
                <p className="text-xs text-ink-500">
                  {cinema.locality}
                  {cinema.amenities.length > 0 && ` · ${cinema.amenities.join(' · ')}`}
                </p>
              </header>

              <div className="flex flex-wrap gap-2">
                {cinema.shows.map((show) => {
                  const disabled = !show.is_bookable || show.availability_band === 'sold_out'
                  const inner = (
                    <div className="text-center">
                      <div className="font-semibold">{showTime(show.starts_at)}</div>
                      <div className="text-[10px] opacity-80">
                        {show.format_code} · {show.audio_language}
                      </div>
                      <div className="mt-0.5 text-[10px] opacity-60">
                        from {rupees(show.min_price_minor, { compact: true })}
                      </div>
                    </div>
                  )
                  const cls = clsx(
                    'min-w-[6.5rem] rounded-lg border px-3 py-2 transition-colors',
                    BAND_STYLE[show.availability_band],
                  )
                  return disabled ? (
                    <div key={show.id} className={cls} title={BAND_LABEL[show.availability_band]}>
                      {inner}
                    </div>
                  ) : (
                    <Link
                      key={show.id}
                      to={`/shows/${show.id}/seats`}
                      className={cls}
                      title={`${BAND_LABEL[show.availability_band]} · ${show.screen_name}`}
                    >
                      {inner}
                    </Link>
                  )
                })}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
