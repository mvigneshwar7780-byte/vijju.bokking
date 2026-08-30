import { NavLink, Navigate, Outlet, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Operator } from '@/api/endpoints'
import { useSession } from '@/store/session'
import { ApiClientError } from '@/api/client'
import { Empty, ErrorNote, Spinner } from '@/components/ui'
import { CreateCinema } from '@/pages/operator/CreateCinema'

const TABS = [
  { to: 'screens', label: 'Screens & seating' },
  { to: 'shows', label: 'Showtimes' },
  { to: 'bookings', label: 'Bookings' },
  { to: 'reports', label: 'Reports' },
]

/** Shell for the operator console: cinema picker plus section tabs. */
export function OperatorLayout() {
  const { user, hydrated } = useSession()
  const { cinemaId } = useParams()
  const navigate = useNavigate()

  // Ask the server rather than trusting the cached role.
  //
  // The role lives in the database, not in the token, so an administrator
  // promoting someone takes effect immediately. But the session store caches
  // the user from sign-in, so a client-side `role === 'customer'` check would
  // turn a freshly promoted operator away until they happened to reload. The
  // API is the authority; a 403 from it is the real answer.
  const { data: cinemas, isPending, error } = useQuery({
    queryKey: ['operator-cinemas'],
    queryFn: Operator.cinemas,
    enabled: Boolean(user),
  })

  if (!hydrated) return <Spinner label="Checking your session" />
  if (!user) return <Navigate to="/login" state={{ from: '/operator' }} replace />
  if (isPending) return <Spinner label="Loading your cinemas" />

  if (error instanceof ApiClientError && error.status === 403) {
    return (
      <Empty
        title="This area is for cinema operators"
        hint="Ask a platform administrator to change your account to Cinema operator. It takes effect straight away — no need to sign in again."
      />
    )
  }
  if (error) return <ErrorNote error={error} />

  if (!cinemas || cinemas.length === 0) {
    return (
      <div className="mx-auto max-w-xl space-y-4 text-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Set up your cinema</h1>
          <p className="mt-1 text-sm text-ink-500">
            Register the hall, then add seat tiers, screens and a seating plan.
            After that you can schedule shows and price them.
          </p>
        </div>
        <CreateCinema onCreated={(id) => navigate(`/operator/${id}/screens`)} />
      </div>
    )
  }

  const active = cinemaId ?? cinemas[0].id
  if (!cinemaId) return <Navigate to={`/operator/${active}/shows`} replace />

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Cinema console</h1>
          <p className="text-sm text-ink-500">
            You manage {cinemas.length} cinema{cinemas.length > 1 ? 's' : ''}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <CreateCinema />
          {cinemas.length > 1 && (
          <select
            className="field max-w-xs"
            value={active}
            onChange={(e) => {
              window.location.href = `/operator/${e.target.value}/shows`
            }}
          >
            {cinemas.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          )}
        </div>
      </div>

      <nav className="flex gap-1 overflow-x-auto border-b border-ink-800 pb-px">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={`/operator/${active}/${tab.to}`}
            className={({ isActive }) =>
              clsx(
                'shrink-0 rounded-t-lg px-4 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'border-b-2 border-brand-500 text-ink-100'
                  : 'text-ink-500 hover:text-ink-300',
              )
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>

      <Outlet context={{ cinemaId: active }} />
    </div>
  )
}
