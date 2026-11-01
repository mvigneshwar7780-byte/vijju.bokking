/**
 * The help centre.
 *
 * Reads the same knowledge base the assistant answers from, so the page and the
 * chatbot cannot drift apart — edit the corpus and both change.
 *
 * Two details carry most of the usefulness:
 *  - Every section has a stable `#slug` anchor, which is what the assistant's
 *    source citations link to. Following a citation lands on the full policy
 *    rather than the 150-character excerpt the bubble showed.
 *  - Filtering matches the body text, not just the heading. People search for
 *    "popcorn" or "wheelchair", which are words inside a policy, not its title.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Help } from '@/api/endpoints'
import { ErrorNote, Spinner } from '@/components/ui'
import { openAssistant } from '@/lib/assistant'

export function HelpCentre() {
  const { hash } = useLocation()
  const [filter, setFilter] = useState('')
  const scrolledTo = useRef<string | null>(null)

  // Derived, not stored: the URL is the single source of which section is
  // highlighted, so an anchor click and a citation link behave identically.
  const active = hash.replace('#', '')

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ['help-sections'],
    queryFn: Help.sections,
    // The corpus changes on re-ingest, not per request.
    staleTime: 5 * 60_000,
  })

  const sections = useMemo(() => data?.sections ?? [], [data])

  const matches = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return sections
    return sections.filter(
      (s) =>
        s.title.toLowerCase().includes(q) ||
        s.body.some((line) => line.toLowerCase().includes(q)),
    )
  }, [sections, filter])

  const grouped = useMemo(() => {
    const out = new Map<string, typeof matches>()
    for (const s of matches) {
      const list = out.get(s.category) ?? []
      list.push(s)
      out.set(s.category, list)
    }
    return out
  }, [matches])

  // Jump to a citation's anchor once the content exists. Guarded so it fires
  // only on the first arrival — otherwise every re-render would yank the
  // reader back to the anchor while they were scrolling.
  useEffect(() => {
    const target = hash.replace('#', '')
    if (!target || sections.length === 0 || scrolledTo.current === target) return
    const node = document.getElementById(target)
    if (!node) return
    scrolledTo.current = target
    node.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [hash, sections.length])

  if (isPending) return <Spinner label="Loading the help centre" />
  if (error) return <ErrorNote error={error} onRetry={() => void refetch()} />

  return (
    <div className="grid gap-8 lg:grid-cols-[16rem_1fr]">
      {/* ---------------------------------------------------- contents --- */}
      <aside className="lg:sticky lg:top-24 lg:self-start">
        <h1 className="text-2xl font-bold tracking-tight">Help centre</h1>
        <p className="mt-1 text-sm text-ink-300">
          Policies, formats and answers to the questions we get most.
        </p>

        <label className="sr-only" htmlFor="help-filter">Search the help centre</label>
        <input
          id="help-filter"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Search — refunds, food, IMAX…"
          className="field mt-4 !py-2"
        />

        <nav className="mt-5 hidden lg:block">
          {[...grouped.entries()].map(([category, list]) => (
            <div key={category} className="mb-5">
              <p className="label !mb-2">{list[0].category_label}</p>
              <ul className="space-y-1">
                {list.map((s) => (
                  <li key={s.slug}>
                    <a
                      href={`#${s.slug}`}
                      className={clsx(
                        'block rounded-md px-2 py-1 text-xs transition-colors',
                        active === s.slug
                          ? 'bg-ink-800 text-ink-100'
                          : 'text-ink-300 hover:bg-ink-800/60 hover:text-ink-100',
                      )}
                    >
                      {s.title}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
      </aside>

      {/* ---------------------------------------------------- sections --- */}
      <div>
        {matches.length === 0 ? (
          <div className="card p-10 text-center">
            <p className="font-semibold">Nothing matches “{filter}”</p>
            <p className="mt-1 text-sm text-ink-300">
              Try a different word, or ask the assistant — it can answer in your own phrasing.
            </p>
            <button className="btn-primary mt-4" onClick={() => openAssistant(filter)}>
              Ask the assistant
            </button>
          </div>
        ) : (
          [...grouped.entries()].map(([category, list]) => (
            <section key={category} className="mb-10">
              <h2 className="mb-4 text-xs font-semibold uppercase tracking-widest text-ink-500">
                {list[0].category_label}
              </h2>

              <div className="space-y-4">
                {list.map((s) => (
                  <article
                    key={s.slug}
                    id={s.slug}
                    className={clsx(
                      'card scroll-mt-24 p-5 transition-colors',
                      active === s.slug && 'border-brand-500/60',
                    )}
                  >
                    <div className="flex items-start justify-between gap-4">
                      <h3 className="font-semibold">{s.title}</h3>
                      {/* A copyable deep link, so a support reply can point at
                          one policy instead of "see the help centre". */}
                      <a
                        href={`#${s.slug}`}
                        aria-label={`Link to ${s.title}`}
                        className="shrink-0 text-xs text-ink-500 transition-colors hover:text-brand-500"
                      >
                        #
                      </a>
                    </div>

                    <div className="mt-3 space-y-2 text-sm text-ink-300">
                      {s.body.map((line, i) =>
                        line.startsWith('-') ? (
                          <p key={i} className="flex gap-2">
                            <span aria-hidden className="text-brand-500">•</span>
                            <span>{line.replace(/^-\s*/, '')}</span>
                          </p>
                        ) : (
                          <p key={i}>{line}</p>
                        ),
                      )}
                    </div>
                  </article>
                ))}
              </div>
            </section>
          ))
        )}

        {matches.length > 0 && (
          <div className="card flex flex-wrap items-center justify-between gap-4 p-5">
            <div>
              <p className="font-semibold">Still not sure?</p>
              <p className="mt-1 text-sm text-ink-300">
                The assistant answers from this same material, in your own words.
              </p>
            </div>
            <button className="btn-primary" onClick={() => openAssistant()}>
              Ask the assistant
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
