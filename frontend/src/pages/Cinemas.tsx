import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { useSession } from '@/store/session'
import { Empty, ErrorNote, Spinner } from '@/components/ui'
import type { Cinema } from '@/api/types'

/** Cinema-first browsing: pick a hall, then see what's on there. */
export function Cinemas() {
  const { city } = useSession()

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ['cinemas', city?.id],
    queryFn: () =>
      api.get<Cinema[]>('/cinemas', { params: { city_id: city?.id } }).then((r) => r.data),
    enabled: Boolean(city),
  })

  if (isPending) return <Spinner label="Loading cinemas" />
  if (error) return <ErrorNote error={error} onRetry={() => void refetch()} />

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Cinemas</h1>
        <p className="mt-1 text-sm text-ink-500">
          {city ? `In ${city.name}` : 'Pick a city'} · prices are set by each hall
        </p>
      </div>

      {data && data.length === 0 ? (
        <Empty title="No cinemas here yet" />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {data?.map((cinema) => (
            <Link
              key={cinema.id}
              to={`/cinemas/${cinema.id}`}
              className="card p-4 transition-colors hover:border-ink-700"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="truncate font-semibold">{cinema.name}</h2>
                  <p className="text-sm text-ink-500">{cinema.locality}</p>
                </div>
                {cinema.brand && <span className="chip shrink-0">{cinema.brand}</span>}
              </div>
              {cinema.amenities.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {cinema.amenities.map((a) => (
                    <span key={a} className="chip">{a}</span>
                  ))}
                </div>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
