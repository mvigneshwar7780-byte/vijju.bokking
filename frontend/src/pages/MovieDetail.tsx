import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Catalog } from '@/api/endpoints'
import { ErrorNote, Spinner } from '@/components/ui'
import { runtime } from '@/lib/format'
import { PriceComparison } from '@/components/PriceComparison'
import { useSession } from '@/store/session'

export function MovieDetail() {
  const { movieId = '' } = useParams()
  const { city } = useSession()
  const { data: movie, isPending, error, refetch } = useQuery({
    queryKey: ['movie', movieId],
    queryFn: () => Catalog.movie(movieId),
  })

  if (isPending) return <Spinner label="Loading film" />
  if (error) return <ErrorNote error={error} onRetry={() => void refetch()} />
  if (!movie) return null

  const cast = movie.credits.filter((c) => c.credit_type === 'cast')
  const director = movie.credits.find((c) => c.job === 'Director')
  const attrs = movie.ai_attributes as { mood?: string[]; themes?: string[] }

  return (
    <article className="space-y-8">
      <div className="grid gap-6 sm:grid-cols-[220px_1fr]">
        <div className="overflow-hidden rounded-xl bg-ink-850">
          {movie.poster_url && <img src={movie.poster_url} alt="" className="w-full" />}
        </div>

        <div className="space-y-4">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">{movie.title}</h1>
            {movie.tagline && <p className="mt-1 text-ink-300 italic">{movie.tagline}</p>}
          </div>

          <div className="flex flex-wrap items-center gap-2 text-sm text-ink-300">
            {movie.rating_average != null && (
              <span className="text-amber-400">
                ★ {movie.rating_average.toFixed(1)}
                <span className="ml-1 text-xs text-ink-500">({movie.rating_count})</span>
              </span>
            )}
            <span>{runtime(movie.runtime_minutes)}</span>
            {movie.certification && <span className="chip">{movie.certification}</span>}
            <span>{movie.languages.map((l) => l.name).join(', ')}</span>
          </div>

          <div className="flex flex-wrap gap-1.5">
            {movie.genres.map((g) => <span key={g.id} className="chip">{g.name}</span>)}
            {attrs?.mood?.map((m) => (
              <span key={m} className="chip border-brand-600/40 text-brand-400">{m}</span>
            ))}
          </div>

          <p className="max-w-2xl leading-relaxed text-ink-300">{movie.synopsis}</p>

          <dl className="grid gap-x-8 gap-y-1 text-sm sm:grid-cols-2">
            {director && (
              <div className="flex gap-2">
                <dt className="text-ink-500">Director</dt>
                <dd>{director.person.name}</dd>
              </div>
            )}
            {cast.length > 0 && (
              <div className="flex gap-2">
                <dt className="text-ink-500">Cast</dt>
                <dd>{cast.map((c) => c.person.name).join(', ')}</dd>
              </div>
            )}
          </dl>

          <Link to={`/movies/${movie.id}/showtimes`} className="btn-primary">
            Book tickets
          </Link>
        </div>
      </div>

      {city && <PriceComparison movieId={movie.id} cityId={city.id} />}
    </article>
  )
}
