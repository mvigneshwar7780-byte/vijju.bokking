import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Admin } from '@/api/endpoints'
import { useSession } from '@/store/session'
import { Empty, ErrorNote, Spinner } from '@/components/ui'
import type { UserAdmin } from '@/api/types'

const ROLES = [
  { value: 'customer', label: 'Customer', hint: 'Books tickets' },
  { value: 'cinema_operator', label: 'Cinema operator', hint: 'Runs their own halls' },
  { value: 'admin', label: 'Administrator', hint: 'Full platform control' },
] as const

const ROLE_TONE: Record<string, string> = {
  admin: 'border-brand-600/50 text-brand-400',
  cinema_operator: 'border-emerald-800 text-emerald-300',
  customer: 'border-ink-700 text-ink-400',
}

/**
 * Grant someone cinema-operator access.
 *
 * There is deliberately no self-service route to this: anyone could otherwise
 * sign up and start listing a cinema they do not own. Promotion is an
 * administrator's decision, and this is where it is made.
 */
export function AdminUsers() {
  const { user, hydrated } = useSession()
  const qc = useQueryClient()
  const [filter, setFilter] = useState<string>('')
  const [search, setSearch] = useState('')

  const users = useQuery({
    queryKey: ['admin-users', filter],
    queryFn: () => Admin.users(1, filter || undefined),
    enabled: user?.role === 'admin',
  })

  const setRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: UserAdmin['role'] }) =>
      Admin.setRole(id, role),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
  })

  if (!hydrated) return <Spinner label="Checking your session" />
  if (!user) return <Navigate to="/login" state={{ from: '/admin/users' }} replace />
  if (user.role !== 'admin') {
    return (
      <Empty
        title="Administrators only"
        hint="Only a platform administrator can change what someone is allowed to do."
      />
    )
  }
  if (users.isPending) return <Spinner label="Loading accounts" />
  if (users.error) return <ErrorNote error={users.error} />

  const rows = (users.data?.items ?? []).filter((u) =>
    search
      ? `${u.email} ${u.full_name}`.toLowerCase().includes(search.toLowerCase())
      : true,
  )

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Accounts</h1>
        <p className="mt-1 text-sm text-ink-500">
          Promote someone to <strong>Cinema operator</strong> and they can register
          their hall, add screens and schedule shows — but only their own.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div className="flex-1 min-w-48">
          <label className="label" htmlFor="search">Search</label>
          <input
            id="search" className="field" placeholder="name or email"
            value={search} onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="role-filter">Role</label>
          <select
            id="role-filter" className="field w-44" value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="">All</option>
            {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
        </div>
      </div>

      {setRole.error && <ErrorNote error={setRole.error} />}
      {setRole.data && (
        <div className="card border-emerald-900/50 bg-emerald-950/20 p-3 text-sm text-emerald-200">
          {setRole.data.message}
        </div>
      )}

      {rows.length === 0 ? (
        <Empty title="No accounts match" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-ink-500">
              <tr className="border-b border-ink-800">
                <th className="py-2 pr-3">Account</th>
                <th className="py-2 pr-3">Role</th>
                <th className="py-2 pr-3">Cinemas</th>
                <th className="py-2">Change role to</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((u) => (
                <tr key={u.id} className="border-b border-ink-850">
                  <td className="py-2.5 pr-3">
                    <div className="font-medium">{u.full_name}</div>
                    <div className="text-xs text-ink-500">{u.email}</div>
                  </td>
                  <td className="py-2.5 pr-3">
                    <span className={clsx('chip', ROLE_TONE[u.role])}>
                      {u.role.replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td className="py-2.5 pr-3 text-ink-300">{u.managed_cinemas}</td>
                  <td className="py-2.5">
                    <select
                      className="field w-44 !py-1.5 !text-xs"
                      value={u.role}
                      disabled={setRole.isPending}
                      onChange={(e) =>
                        setRole.mutate({
                          id: u.id,
                          role: e.target.value as UserAdmin['role'],
                        })
                      }
                    >
                      {ROLES.map((r) => (
                        <option key={r.value} value={r.value}>{r.label}</option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-ink-500">
        Demoting yourself is refused while you are the only administrator — that
        would lock everyone out of this page.
      </p>
    </div>
  )
}
