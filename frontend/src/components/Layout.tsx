import { Link, NavLink, Outlet } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Catalog } from '@/api/endpoints'
import { useSession } from '@/store/session'
import clsx from 'clsx'

function CityPicker() {
  const { city, setCity } = useSession()
  const [open, setOpen] = useState(false)
  const { data: cities } = useQuery({ queryKey: ['cities'], queryFn: Catalog.cities })

  // Pick a default city on first load so the app is never in a "no city" state
  // that every listing query would have to special-case.
  useEffect(() => {
    if (!city && cities?.length) setCity(cities[0])
  }, [city, cities, setCity])

  return (
    <div className="relative">
      <button className="btn-ghost !px-3 !py-2" onClick={() => setOpen((v) => !v)}>
        <span aria-hidden>📍</span>
        <span>{city?.name ?? 'Select city'}</span>
        <span className="text-ink-500" aria-hidden>▾</span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <ul className="absolute right-0 z-20 mt-2 w-52 overflow-hidden card py-1 shadow-2xl">
            {cities?.map((c) => (
              <li key={c.id}>
                <button
                  className={clsx(
                    'w-full px-4 py-2 text-left text-sm hover:bg-ink-800',
                    c.id === city?.id && 'text-brand-400',
                  )}
                  onClick={() => { setCity(c); setOpen(false) }}
                >
                  {c.name}
                  <span className="ml-2 text-xs text-ink-500">{c.state}</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

export function Layout() {
  const { user, signOut, hydrate } = useSession()
  useEffect(() => { void hydrate() }, [hydrate])

  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-30 border-b border-ink-800 bg-ink-950/85 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-4 px-4">
          <Link to="/" className="text-lg font-black tracking-tight">
            vijju<span className="text-brand-500">.booking</span>
          </Link>

          <nav className="ml-4 hidden gap-1 sm:flex">
            {[
              { to: '/', label: 'Now Showing', end: true },
              { to: '/cinemas', label: 'Cinemas' },
              { to: '/bookings', label: 'My Bookings' },
              ...(user && user.role !== 'customer'
                ? [{ to: '/operator', label: 'Console' }]
                : []),
              ...(user?.role === 'admin'
                ? [{ to: '/admin/users', label: 'Accounts' }]
                : []),
            ].map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  clsx(
                    'rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                    isActive ? 'bg-ink-800 text-ink-100' : 'text-ink-300 hover:text-ink-100',
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            <CityPicker />
            {user ? (
              <div className="flex items-center gap-2">
                <span className="hidden text-sm text-ink-300 sm:inline">{user.full_name}</span>
                <button className="btn-ghost !px-3 !py-2" onClick={() => void signOut()}>
                  Sign out
                </button>
              </div>
            ) : (
              <Link to="/login" className="btn-primary !px-3 !py-2">Sign in</Link>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8">
        <Outlet />
      </main>

      <footer className="border-t border-ink-800 py-8 text-center text-xs text-ink-500">
        vijju.booking — a movie ticketing reference implementation. Payments are simulated.
      </footer>
    </div>
  )
}
