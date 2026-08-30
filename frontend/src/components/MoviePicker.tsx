import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Catalog, Operator } from '@/api/endpoints'
import { ErrorNote, Spinner } from '@/components/ui'
import { runtime } from '@/lib/format'
import type { MovieCard } from '@/api/types'

/**
 * Choose a film to schedule.
 *
 * Searches the **shared catalogue**, not the operator's own contributions. That
 * distinction is the whole point of the data model: one `movies` row plays at
 * many halls at different prices. Listing only titles you personally added
 * meant a new operator saw an empty dropdown with nothing to type into, and no
 * way to add anything — while ten films sat in the catalogue they could have
 * scheduled immediately.
 *
 * If the film genuinely is not listed, it can be added here, which is also the
 * only route to `POST /operator/movies`.
 */
export function MoviePicker({
  value,
  onChange,
}: {
  value: string | null
  onChange: (movieId: string | null, movie?: MovieCard) => void
}) {
  const [search, setSearch] = useState('')
  const [adding, setAdding] = useState(false)

  const results = useQuery({
    queryKey: ['catalogue-search', search],
    queryFn: () =>
      Catalog.movies({ q: search || undefined, page_size: 20 }),
  })

  const selected = results.data?.items.find((m) => m.id === value)

  if (adding) {
    return (
      <NewMovieForm
        initialTitle={search}
        onCancel={() => setAdding(false)}
        onCreated={(movie) => {
          setAdding(false)
          setSearch(movie.title)
          onChange(movie.id, movie)
        }}
      />
    )
  }

  return (
    <div className="space-y-2">
      <input
        className="field"
        placeholder="Search the film catalogue…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      {results.isPending && <Spinner label="Searching" />}
      {results.error && <ErrorNote error={results.error} />}

      {results.data && (
        <div className="max-h-56 space-y-1 overflow-y-auto rounded-lg border border-ink-800 p-1">
          {results.data.items.length === 0 && (
            <p className="p-3 text-sm text-ink-500">
              No film matches “{search}”.
            </p>
          )}
          {results.data.items.map((movie) => (
            <button
              key={movie.id}
              type="button"
              onClick={() => onChange(movie.id, movie)}
              className={clsx(
                'flex w-full items-center gap-3 rounded-md px-2 py-1.5 text-left transition-colors',
                movie.id === value
                  ? 'bg-brand-500/15 ring-1 ring-brand-500'
                  : 'hover:bg-ink-800',
              )}
            >
              <div className="h-12 w-8 shrink-0 overflow-hidden rounded bg-ink-850">
                {movie.poster_url && (
                  <img src={movie.poster_url} alt="" className="size-full object-cover" />
                )}
              </div>
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">{movie.title}</div>
                <div className="truncate text-[11px] text-ink-500">
                  {runtime(movie.runtime_minutes)}
                  {movie.certification && ` · ${movie.certification}`}
                  {movie.genres.length > 0 &&
                    ` · ${movie.genres.map((g) => g.name).join(', ')}`}
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] text-ink-500">
          {selected
            ? `Selected: ${selected.title}`
            : 'Pick a film from the shared catalogue.'}
        </p>
        <button
          type="button"
          className="btn-ghost !py-1 !text-[11px]"
          onClick={() => setAdding(true)}
        >
          Not listed? Add a film
        </button>
      </div>
    </div>
  )
}

/** Add a title to the shared catalogue. */
function NewMovieForm({
  initialTitle,
  onCreated,
  onCancel,
}: {
  initialTitle: string
  onCreated: (movie: MovieCard) => void
  onCancel: () => void
}) {
  const qc = useQueryClient()
  const languages = useQuery({ queryKey: ['languages'], queryFn: Catalog.languages })

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) => Operator.createMovie(body),
    onSuccess: (movie) => {
      void qc.invalidateQueries({ queryKey: ['catalogue-search'] })
      onCreated(movie as unknown as MovieCard)
    },
  })

  return (
    <div className="space-y-3 rounded-lg border border-ink-700 bg-ink-850 p-3">
      <div>
        <h4 className="text-sm font-semibold">Add a film</h4>
        <p className="mt-0.5 text-[11px] text-ink-500">
          Films are shared across the platform — other cinemas can schedule this
          title too, at their own prices.
        </p>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <label className="label" htmlFor="m-title">Title</label>
          <input id="m-title" className="field" defaultValue={initialTitle}
            placeholder="Monsoon Light" />
        </div>
        <div>
          <label className="label" htmlFor="m-runtime">Runtime (minutes)</label>
          <input id="m-runtime" className="field" type="number" min="1" max="600"
            defaultValue={120} />
        </div>
        <div>
          <label className="label" htmlFor="m-cert">Certification</label>
          <input id="m-cert" className="field" placeholder="UA13+" />
        </div>
        <div>
          <label className="label" htmlFor="m-lang">Language</label>
          <select id="m-lang" className="field">
            {languages.data?.map((l) => (
              <option key={l.id} value={l.code}>{l.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="m-genres">Genres (comma separated)</label>
          <input id="m-genres" className="field" placeholder="Drama, Thriller" />
        </div>
        <div className="sm:col-span-2">
          <label className="label" htmlFor="m-synopsis">Synopsis</label>
          <textarea id="m-synopsis" className="field" rows={2}
            placeholder="What is it about?" />
        </div>
        <div className="sm:col-span-2">
          <label className="label" htmlFor="m-poster">Poster URL (optional)</label>
          <input id="m-poster" className="field" placeholder="https://…" />
        </div>
      </div>

      {create.error && <ErrorNote error={create.error} />}

      <div className="flex gap-2">
        <button type="button" className="btn-ghost flex-1 !py-1.5 !text-xs" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className="btn-primary flex-1 !py-1.5 !text-xs"
          disabled={create.isPending}
          onClick={() => {
            const get = (id: string) =>
              (document.getElementById(id) as HTMLInputElement | HTMLTextAreaElement | null)
                ?.value ?? ''
            const lang = (document.getElementById('m-lang') as HTMLSelectElement | null)?.value
            create.mutate({
              title: get('m-title'),
              runtime_minutes: Number(get('m-runtime')) || 120,
              certification: get('m-cert') || null,
              synopsis: get('m-synopsis'),
              poster_url: get('m-poster') || null,
              status: 'now_showing',
              original_language_code: lang ?? 'en',
              language_codes: lang ? [lang] : [],
              genre_names: get('m-genres').split(',').map((g) => g.trim()).filter(Boolean),
            })
          }}
        >
          {create.isPending ? 'Adding…' : 'Add film'}
        </button>
      </div>
    </div>
  )
}
