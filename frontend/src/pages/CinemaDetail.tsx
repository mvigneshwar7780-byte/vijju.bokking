import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Browse } from '@/api/endpoints'
import { Empty, ErrorNote, Spinner } from '@/components/ui'
import { dayLabel, rupees, runtime, showTime } from '@/lib/format'

/** Everything playing at one hall, priced by that hall. */
export function CinemaDetail() {
  const { cinemaId = '' } = useParams()
  const [date, setDate] = useState<string | undefined>()

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ['cinema-movies', cinemaId, date],
    queryFn: () => Browse.moviesAtCinema(cinemaId, date),
  })

  if (isPending) return <Spinner label="Loading listings" />
  if (error) return <ErrorNote error={error} onRetry={() => void refetch()} />
  if (!data) return null

  const dates = [...new Set(data.movies.flatMap((m) => m.available_dates))].sort()

  return (
    <div className="space-y-6">
      <div>
        <Link to="/cinemas" className="text-sm text-ink-500 hover:text-ink-300">
          ← All cinemas
        </Link>
        <h1 className="mt-1 text-2xl font-bold tracking-tight">{data.cinema_name}</h1>
        <p className="text-sm text-ink-500">
          {data.locality} · {data.city_name}
        </p>
        {data.amenities.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {data.amenities.map((a) => <span key={a} className="chip">{a}</span>)}
          </div>
        )}
      </div>

      {dates.length > 0 && (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {dates.map((d) => {
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

      {data.movies.length === 0 ? (
        <Empty title="Nothing playing on this date" hint="Try another date." />
      ) : (
        <div className="space-y-3">
          {data.movies.map((movie) => (
            <article key={movie.movie_id} className="card flex gap-4 p-4">
              <Link to={`/movies/${movie.movie_id}`} className="shrink-0">
                <div className="h-32 w-22 overflow-hidden rounded-lg bg-ink-850">
                  {movie.poster_url && (
                    <img src={movie.poster_url} alt="" className="size-full object-cover" />
                  )}
                </div>
              </Link>

              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <Link
                      to={`/movies/${movie.movie_id}`}
                      className="font-semibold hover:text-brand-400"
                    >
                      {movie.title}
                    </Link>
                    <p className="mt-0.5 text-xs text-ink-500">
                      {runtime(movie.runtime_minutes)}
                      {movie.certification && ` · ${movie.certification}`}
                      {movie.genres.length > 0 && ` · ${movie.genres.join(', ')}`}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-semibold">
                      {rupees(movie.min_price_minor, { compact: true })}
                      {movie.max_price_minor !== movie.min_price_minor && (
                        <span className="text-ink-500">
                          {' – '}{rupees(movie.max_price_minor, { compact: true })}
                        </span>
                      )}
                    </p>
                    <p className="text-[11px] text-ink-500">at this cinema</p>
                  </div>
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  {movie.formats.map((f) => <span key={f} className="chip">{f}</span>)}
                  {movie.languages.slice(0, 2).map((l) => (
                    <span key={l} className="chip">{l}</span>
                  ))}
                  <span className="text-xs text-ink-500">
                    {movie.show_count} show{movie.show_count > 1 ? 's' : ''}
                    {movie.next_show_at && ` · next ${showTime(movie.next_show_at)}`}
                  </span>
                </div>

                <Link
                  to={`/movies/${movie.movie_id}/showtimes`}
                  className="btn-primary mt-3 !py-1.5 !text-xs"
                >
                  See showtimes
                </Link>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
