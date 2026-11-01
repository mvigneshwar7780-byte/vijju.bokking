/**
 * Terms and policies.
 *
 * Deliberately not the help centre. That page answers "can I bring popcorn?" —
 * short, searchable, shared with the assistant. This one is a formal document
 * that people navigate by its numbering, so the article/clause hierarchy is
 * what the layout is built around.
 *
 * Clauses collapse by default: 37 of them expanded is a wall nobody reads, and
 * the numbered contents list is how anyone actually arrives at the one they
 * came for.
 */
import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Help } from '@/api/endpoints'
import { ErrorNote, Spinner } from '@/components/ui'

export function Terms() {
  const { hash } = useLocation()
  const [open, setOpen] = useState<Set<string>>(new Set())
  const jumped = useRef<string | null>(null)

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ['legal-terms'],
    queryFn: Help.terms,
    staleTime: 60 * 60_000,
  })

  const articles = data?.articles

  // Arriving at /terms#3-2-… must open that clause as well as scroll to it,
  // or the reader lands on a collapsed heading and sees nothing.
  useEffect(() => {
    const target = hash.replace('#', '')
    if (!target || !articles || jumped.current === target) return
    jumped.current = target
    setOpen((prev) => new Set(prev).add(target))
    requestAnimationFrame(() => {
      document.getElementById(target)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }, [hash, articles])

  if (isPending) return <Spinner label="Loading the terms" />
  if (error) return <ErrorNote error={error} onRetry={() => void refetch()} />
  if (!articles?.length) return <ErrorNote error={new Error('No terms are published.')} />

  const toggle = (slug: string) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(slug)) next.delete(slug)
      else next.add(slug)
      return next
    })

  const allOpen = articles.flatMap((a) => a.clauses).every((c) => open.has(c.slug))

  return (
    <div className="mx-auto max-w-4xl">
      <header className="border-b border-ink-800 pb-6">
        <h1 className="text-3xl font-bold tracking-tight">Terms &amp; policies</h1>
        <p className="mt-2 max-w-2xl text-sm text-ink-300">
          Terms of service, privacy, copyright and dispute resolution.
        </p>

        <div className="mt-4 rounded-lg border border-amber-900/60 bg-amber-950/20 px-4 py-3">
          <p className="text-xs text-amber-200">
            <strong className="font-semibold">Demonstration content.</strong>{' '}
            vijju.booking is a reference implementation. These policies are
            template text used to exercise the product — they are not a binding
            agreement, and payments on this site are simulated.
          </p>
        </div>
      </header>

      {/* ------------------------------------------------- contents ------- */}
      <nav aria-label="Contents" className="mt-8">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="label !mb-0">Contents</h2>
          <button
            className="btn-ghost !px-3 !py-1 !text-xs"
            onClick={() =>
              setOpen(
                allOpen ? new Set() : new Set(articles.flatMap((a) => a.clauses.map((c) => c.slug))),
              )
            }
          >
            {allOpen ? 'Collapse all' : 'Expand all'}
          </button>
        </div>
        <ol className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
          {articles.map((a) => (
            <li key={a.slug}>
              <a
                href={`#${a.slug}`}
                className="flex gap-2 rounded-md px-2 py-1 text-sm text-ink-300 transition-colors hover:bg-ink-800/60 hover:text-ink-100"
              >
                <span className="font-mono text-xs text-brand-500">{a.number}.</span>
                <span>{a.title}</span>
              </a>
            </li>
          ))}
        </ol>
      </nav>

      {/* ------------------------------------------------- articles ------- */}
      <div className="mt-10 space-y-10">
        {articles.map((article) => (
          <section key={article.slug} id={article.slug} className="scroll-mt-24">
            <h2 className="flex gap-3 border-b border-ink-800 pb-2 text-xl font-semibold">
              <span className="font-mono text-brand-500">{article.number}.</span>
              {article.title}
            </h2>

            <div className="mt-4 space-y-2">
              {article.clauses.map((clause) => {
                const isOpen = open.has(clause.slug)
                return (
                  <article
                    key={clause.slug}
                    id={clause.slug}
                    className="scroll-mt-24 overflow-hidden rounded-lg border border-ink-800"
                  >
                    <h3>
                      <button
                        onClick={() => toggle(clause.slug)}
                        aria-expanded={isOpen}
                        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-ink-800/50"
                      >
                        <span className="font-mono text-xs text-ink-500">{clause.number}</span>
                        <span className="flex-1 text-sm font-medium">{clause.title}</span>
                        <span
                          aria-hidden
                          className={clsx(
                            'text-ink-500 transition-transform',
                            isOpen && 'rotate-90',
                          )}
                        >
                          ›
                        </span>
                      </button>
                    </h3>

                    {isOpen && (
                      <div className="space-y-3 border-t border-ink-800 px-4 py-4 text-sm leading-relaxed text-ink-300">
                        {clause.body.map((paragraph, i) => (
                          <p key={i}>{paragraph}</p>
                        ))}
                      </div>
                    )}
                  </article>
                )
              })}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
