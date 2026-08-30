import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Catalog } from '@/api/endpoints'
import { useSession } from '@/store/session'
import { Empty, ErrorNote, Spinner } from '@/components/ui'
import { runtime } from '@/lib/format'
import type { MovieCard as MovieCardType } from '@/api/types'

function MovieCard({ movie }: { movie: MovieCardType }) {
  return (
    <Link
      to={`/movies/${movie.id}`}
      className="group card overflow-hidden transition-colors hover:border-ink-700"
    >
      <div className="aspect-[2/3] overflow-hidden bg-ink-850">
        {movie.poster_url ? (
          <img
            src={movie.poster_url}
            alt=""
            loading="lazy"
            className="size-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
          />
        ) : (
          <div className="flex size-full items-center justify-center text-ink-700">No poster</div>
        )}
      </div>
      <div className="space-y-1.5 p-3">
        <h3 className="truncate font-semibold leading-tight">{movie.title}</h3>
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-ink-500">
          {movie.rating_average != null && (
            <span className="text-amber-400">★ {movie.rating_average.toFixed(1)}</span>
          )}
          <span>{runtime(movie.runtime_minutes)}</span>
          {movie.certification && <span className="chip">{movie.certification}</span>}
        </div>
        <p className="truncate text-xs text-ink-500">
          {movie.genres.map((g) => g.name).join(' · ')}
        </p>
      </div>
    </Link>
  )
}

export function Home() {
  const { city } = useSession()
  const [query, setQuery] = useState('')

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ['movies', city?.id, query],
    queryFn: () =>
      Catalog.movies({
        city_id: city?.id,
        status: query ? undefined : 'now_showing',
        q: query || undefined,
        page_size: 24,
      }),
    enabled: Boolean(city),
  })

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            {query ? 'Search results' : 'Now showing'}
          </h1>
          <p className="mt-1 text-sm text-ink-500">
            {city ? `In ${city.name}` : 'Pick a city to see showtimes'}
          </p>
        </div>
        <input
          className="field max-w-xs"
          placeholder="Search films…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {isPending && <Spinner label="Loading films" />}
      {error && <ErrorNote error={error} onRetry={() => void refetch()} />}
      {data && data.items.length === 0 && (
        <Empty title="Nothing showing here yet" hint="Try another city or clear the search." />
      )}
      {data && data.items.length > 0 && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          {data.items.map((m) => <MovieCard key={m.id} movie={m} />)}
        </div>
      )}
    </div>
  )
}
