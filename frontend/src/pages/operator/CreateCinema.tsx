import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Catalog, Operator } from '@/api/endpoints'
import { ErrorNote } from '@/components/ui'

/**
 * Register a cinema. Whoever creates it becomes its operator, and from then on
 * only they (and a platform administrator) can touch it or anything under it.
 */
export function CreateCinema({ onCreated }: { onCreated?: (id: string) => void }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const cities = useQuery({ queryKey: ['cities'], queryFn: Catalog.cities })

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) => Operator.createCinema(body),
    onSuccess: (cinema) => {
      setOpen(false)
      void qc.invalidateQueries({ queryKey: ['operator-cinemas'] })
      onCreated?.(cinema.id)
    },
  })

  if (!open) {
    return (
      <button className="btn-primary" onClick={() => setOpen(true)}>
        Add a theater
      </button>
    )
  }

  return (
    <form
      className="card space-y-4 p-4"
      onSubmit={(e) => {
        e.preventDefault()
        const f = new FormData(e.currentTarget)
        create.mutate({
          city_id: String(f.get('city')),
          name: String(f.get('name')),
          brand: String(f.get('brand')) || null,
          address_line: String(f.get('address')),
          locality: String(f.get('locality')) || null,
          timezone: String(f.get('timezone')),
          amenities: String(f.get('amenities'))
            .split(',')
            .map((a) => a.trim())
            .filter(Boolean),
        })
      }}
    >
      <div>
        <h2 className="font-semibold">New cinema</h2>
        <p className="mt-1 text-xs text-ink-500">
          You become this cinema&apos;s operator. Next you will add seat tiers,
          screens and a seating plan before you can schedule a show.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <label className="label" htmlFor="name">Cinema name</label>
          <input id="name" name="name" required minLength={2} className="field"
            placeholder="Starlight Cinemas, Indiranagar" />
        </div>
        <div>
          <label className="label" htmlFor="brand">Brand (optional)</label>
          <input id="brand" name="brand" className="field" placeholder="Starlight" />
        </div>
        <div>
          <label className="label" htmlFor="city">City</label>
          <select id="city" name="city" required className="field">
            {cities.data?.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>
        <div className="sm:col-span-2">
          <label className="label" htmlFor="address">Address</label>
          <input id="address" name="address" required minLength={4} className="field"
            placeholder="100 Feet Road, Indiranagar" />
        </div>
        <div>
          <label className="label" htmlFor="locality">Locality</label>
          <input id="locality" name="locality" className="field" placeholder="Indiranagar" />
        </div>
        <div>
          <label className="label" htmlFor="timezone">Time zone</label>
          <input id="timezone" name="timezone" defaultValue="Asia/Kolkata" className="field" />
          <p className="mt-1 text-[11px] text-ink-500">
            Showtimes are entered in this zone.
          </p>
        </div>
        <div className="sm:col-span-2">
          <label className="label" htmlFor="amenities">Amenities (comma separated)</label>
          <input id="amenities" name="amenities" className="field"
            placeholder="Parking, F&amp;B, Wheelchair Access" />
        </div>
      </div>

      {create.error && <ErrorNote error={create.error} />}

      <div className="flex gap-2">
        <button type="button" className="btn-ghost flex-1" onClick={() => setOpen(false)}>
          Cancel
        </button>
        <button className="btn-primary flex-1" disabled={create.isPending}>
          {create.isPending ? 'Creating…' : 'Create cinema'}
        </button>
      </div>
    </form>
  )
}
