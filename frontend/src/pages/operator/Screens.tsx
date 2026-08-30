import { useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Operator } from '@/api/endpoints'
import { ErrorNote, Spinner } from '@/components/ui'
import { rupees } from '@/lib/format'
import type { LayoutRowInput } from '@/api/types'

type Ctx = { cinemaId: string }

/** Screens, seat tiers, and the seating plan for each screen. */
export function OperatorScreens() {
  const { cinemaId } = useOutletContext<Ctx>()
  const qc = useQueryClient()
  const [editing, setEditing] = useState<string | null>(null)

  const screens = useQuery({
    queryKey: ['op-screens', cinemaId],
    queryFn: () => Operator.screens(cinemaId),
  })
  const categories = useQuery({
    queryKey: ['op-categories', cinemaId],
    queryFn: () => Operator.seatCategories(cinemaId),
  })

  const addCategory = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      Operator.createSeatCategory(cinemaId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['op-categories', cinemaId] }),
  })
  const addScreen = useMutation({
    mutationFn: (body: Record<string, unknown>) => Operator.createScreen(cinemaId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['op-screens', cinemaId] }),
  })

  if (screens.isPending || categories.isPending) return <Spinner />

  return (
    <div className="space-y-6">
      {/* ---- seat tiers ------------------------------------------------ */}
      <section className="card p-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-300">
          Seat tiers
        </h2>
        <p className="mt-1 text-xs text-ink-500">
          Tiers belong to this cinema. Their default price is the starting point —
          each showtime can override it.
        </p>

        <div className="mt-3 flex flex-wrap gap-2">
          {categories.data?.map((c) => (
            <div key={c.id} className="rounded-lg border border-ink-700 bg-ink-850 px-3 py-2">
              <p className="text-sm font-medium">{c.name}</p>
              <p className="text-xs text-ink-500">
                {c.code} · {rupees(c.default_price_minor, { compact: true })}
              </p>
            </div>
          ))}
        </div>

        <form
          className="mt-4 flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            const f = new FormData(e.currentTarget)
            addCategory.mutate({
              code: String(f.get('code')),
              name: String(f.get('name')),
              default_price_minor: Math.round(Number(f.get('price')) * 100),
            })
            e.currentTarget.reset()
          }}
        >
          <div><label className="label">Code</label>
            <input name="code" required className="field w-24" placeholder="PREM" /></div>
          <div><label className="label">Name</label>
            <input name="name" required className="field w-40" placeholder="Premium" /></div>
          <div><label className="label">Default price (₹)</label>
            <input name="price" type="number" min="0" required className="field w-32" /></div>
          <button className="btn-ghost" disabled={addCategory.isPending}>Add tier</button>
        </form>
        {addCategory.error && <div className="mt-2"><ErrorNote error={addCategory.error} /></div>}
      </section>

      {/* ---- screens ---------------------------------------------------- */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-300">
            Screens
          </h2>
        </div>

        {screens.data?.map((screen) => (
          <div key={screen.id} className="card p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="font-semibold">{screen.name}</h3>
                <p className="text-xs text-ink-500">
                  Screen {screen.screen_number} · {screen.total_seats} seats ·{' '}
                  {screen.supported_formats.join(', ')}
                  {screen.sound_system && ` · ${screen.sound_system}`}
                </p>
              </div>
              <button
                className="btn-ghost !py-1.5 !text-xs"
                onClick={() => setEditing(editing === screen.id ? null : screen.id)}
              >
                {screen.total_seats === 0 ? 'Add seating plan' : 'Edit seating plan'}
              </button>
            </div>
            {editing === screen.id && (
              <LayoutEditor
                screenId={screen.id}
                categoryCodes={(categories.data ?? []).map((c) => c.code)}
                onDone={() => {
                  setEditing(null)
                  void qc.invalidateQueries({ queryKey: ['op-screens', cinemaId] })
                }}
              />
            )}
          </div>
        ))}

        <form
          className="card flex flex-wrap items-end gap-2 p-4"
          onSubmit={(e) => {
            e.preventDefault()
            const f = new FormData(e.currentTarget)
            addScreen.mutate({
              name: String(f.get('name')),
              screen_number: Number(f.get('number')),
              supported_formats: String(f.get('formats')).split(',').map((s) => s.trim()),
            })
            e.currentTarget.reset()
          }}
        >
          <div><label className="label">Name</label>
            <input name="name" required className="field w-40" placeholder="Audi 1" /></div>
          <div><label className="label">Number</label>
            <input name="number" type="number" min="1" required className="field w-24" /></div>
          <div><label className="label">Formats</label>
            <input name="formats" defaultValue="2D" className="field w-44" /></div>
          <button className="btn-primary" disabled={addScreen.isPending}>Add screen</button>
        </form>
        {addScreen.error && <ErrorNote error={addScreen.error} />}
      </section>
    </div>
  )
}

/** Rows in, seat grid out. Refused by the API if seats are already sold. */
function LayoutEditor({
  screenId,
  categoryCodes,
  onDone,
}: {
  screenId: string
  categoryCodes: string[]
  onDone: () => void
}) {
  const [rows, setRows] = useState<LayoutRowInput[]>([
    { row_label: 'A', seat_count: 10, category_code: categoryCodes[0] ?? 'STD',
      aisles_after: [5], wheelchair_seats: [] },
  ])

  const save = useMutation({
    mutationFn: () => Operator.setLayout(screenId, { rows }),
    onSuccess: onDone,
  })

  const update = (i: number, patch: Partial<LayoutRowInput>) =>
    setRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))

  return (
    <div className="mt-4 space-y-3 border-t border-ink-800 pt-4">
      <p className="text-xs text-ink-500">
        One line per row. Aisles are seat numbers to leave a walkway after — they
        take up grid space without being seats.
      </p>

      {rows.map((row, i) => (
        <div key={i} className="flex flex-wrap items-end gap-2">
          <div><label className="label">Row</label>
            <input className="field w-16" value={row.row_label}
              onChange={(e) => update(i, { row_label: e.target.value.toUpperCase() })} /></div>
          <div><label className="label">Seats</label>
            <input className="field w-20" type="number" min="1" max="60" value={row.seat_count}
              onChange={(e) => update(i, { seat_count: Number(e.target.value) })} /></div>
          <div><label className="label">Tier</label>
            <select className="field w-32" value={row.category_code}
              onChange={(e) => update(i, { category_code: e.target.value })}>
              {categoryCodes.map((c) => <option key={c} value={c}>{c}</option>)}
            </select></div>
          <div><label className="label">Aisles after</label>
            <input className="field w-28" value={row.aisles_after.join(',')}
              onChange={(e) =>
                update(i, {
                  aisles_after: e.target.value.split(',')
                    .map((s) => Number(s.trim())).filter(Boolean),
                })
              } /></div>
          <button
            className="btn-ghost !py-1.5 !text-xs"
            onClick={() => setRows((p) => p.filter((_, idx) => idx !== i))}
          >
            Remove
          </button>
        </div>
      ))}

      <div className="flex gap-2">
        <button
          className="btn-ghost !py-1.5 !text-xs"
          onClick={() =>
            setRows((p) => [
              ...p,
              {
                row_label: String.fromCharCode(65 + p.length),
                seat_count: 10,
                category_code: categoryCodes[0] ?? 'STD',
                aisles_after: [5],
                wheelchair_seats: [],
              },
            ])
          }
        >
          Add row
        </button>
        <button className="btn-primary !py-1.5 !text-xs" disabled={save.isPending}
          onClick={() => save.mutate()}>
          {save.isPending ? 'Saving…' : `Save plan (${rows.reduce((n, r) => n + r.seat_count, 0)} seats)`}
        </button>
      </div>
      {save.error && <ErrorNote error={save.error} />}
    </div>
  )
}
