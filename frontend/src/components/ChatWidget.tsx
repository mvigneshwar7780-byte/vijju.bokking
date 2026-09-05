/**
 * The support assistant: a floating button that opens into a chat panel.
 *
 * Two details are load-bearing rather than decorative:
 *
 *  - The transcript lives in `localStorage`, so closing the panel to go and
 *    check a seat map does not throw away the answer you just asked for. Every
 *    access is guarded -- private windows and "block site data" make these
 *    accessors *throw*, not return null, and an unguarded read would take the
 *    whole app down with it.
 *  - The panel is a `dialog`-shaped region with focus moved into it on open and
 *    returned on close, because a chat you cannot reach or leave from the
 *    keyboard is not usable.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import { Assistant } from '@/api/endpoints'
import type { AssistantReply } from '@/api/types'

type Turn = {
  id: string
  role: 'user' | 'bot'
  text: string
  sources?: { section: string; excerpt: string }[]
  suggestions?: string[]
  grounded?: boolean
}

const STORAGE_KEY = 'cineai.assistant'
const MAX_STORED_TURNS = 40

const GREETING: Turn = {
  id: 'greeting',
  role: 'bot',
  text: 'Hi. Ask me about refunds, cancellations, seat changes, cinema formats or anything else about booking here.',
  suggestions: ['How do refunds work?', 'Can I change my seat?', 'What is IMAX?'],
}

function loadTurns(): Turn[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return [GREETING]
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed) || parsed.length === 0) return [GREETING]
    return parsed as Turn[]
  } catch {
    // Corrupt JSON, or storage unavailable. Either way a fresh conversation is
    // a better outcome than a blank screen.
    return [GREETING]
  }
}

function saveTurns(turns: Turn[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(turns.slice(-MAX_STORED_TURNS)))
  } catch {
    // Quota exceeded or storage blocked. The transcript stays in memory for
    // this session; losing persistence is not worth breaking the chat over.
  }
}

export function ChatWidget() {
  const [open, setOpen] = useState(false)
  const [turns, setTurns] = useState<Turn[]>(loadTurns)
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)

  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const launcherRef = useRef<HTMLButtonElement>(null)

  useEffect(() => saveTurns(turns), [turns])

  // Pin to the newest message whenever the transcript grows or the panel opens.
  useEffect(() => {
    if (!open) return
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [turns, open, pending])

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  const close = useCallback(() => {
    setOpen(false)
    // Send focus back where it came from, or the keyboard user is stranded at
    // the top of the document.
    launcherRef.current?.focus()
  }, [])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, close])

  const ask = useCallback(
    async (question: string) => {
      const asked = question.trim()
      if (!asked || pending) return

      const mine: Turn = { id: `u${Date.now()}`, role: 'user', text: asked }
      setTurns((prev) => [...prev, mine])
      setDraft('')
      setPending(true)

      try {
        const reply: AssistantReply = await Assistant.ask(asked)
        setTurns((prev) => [
          ...prev,
          {
            id: `b${Date.now()}`,
            role: 'bot',
            text: reply.answer,
            sources: reply.sources,
            suggestions: reply.suggestions,
            grounded: reply.grounded,
          },
        ])
      } catch (error) {
        setTurns((prev) => [
          ...prev,
          {
            id: `e${Date.now()}`,
            role: 'bot',
            text:
              error instanceof Error
                ? `I could not reach the help service (${error.message}). Please try again.`
                : 'I could not reach the help service. Please try again.',
            grounded: false,
          },
        ])
      } finally {
        setPending(false)
      }
    },
    [pending],
  )

  const reset = () => setTurns([GREETING])

  if (!open) {
    return (
      <button
        ref={launcherRef}
        onClick={() => setOpen(true)}
        aria-label="Open the help assistant"
        className="fixed bottom-5 right-5 z-40 flex size-14 items-center justify-center rounded-full bg-brand-500 text-white shadow-2xl shadow-brand-500/25 transition hover:bg-brand-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 focus-visible:ring-offset-ink-950"
      >
        <ChatIcon />
      </button>
    )
  }

  return (
    <section
      role="dialog"
      aria-label="Help assistant"
      aria-modal="false"
      className="fixed inset-x-0 bottom-0 z-40 flex h-[85dvh] flex-col overflow-hidden border-t border-ink-700 bg-ink-900 shadow-2xl sm:inset-x-auto sm:bottom-5 sm:right-5 sm:h-[min(34rem,80dvh)] sm:w-[23rem] sm:rounded-2xl sm:border"
    >
      <header className="flex items-center gap-3 border-b border-ink-800 bg-ink-850 px-4 py-3">
        <span className="flex size-8 items-center justify-center rounded-full bg-brand-500/15 text-brand-500">
          <ChatIcon small />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">Help assistant</p>
          <p className="truncate text-[11px] text-ink-500">Answers from our help centre</p>
        </div>
        <button
          onClick={reset}
          className="rounded-lg px-2 py-1 text-[11px] text-ink-300 transition hover:bg-ink-800 hover:text-ink-100"
        >
          Clear
        </button>
        <button
          onClick={close}
          aria-label="Close the help assistant"
          className="rounded-lg px-2 py-1 text-lg leading-none text-ink-300 transition hover:bg-ink-800 hover:text-ink-100"
        >
          ×
        </button>
      </header>

      {/* The transcript is itself the live region, so a new bubble is announced
          where it actually lives. Mirroring the text into a separate sr-only
          node instead would put every answer in the DOM twice. */}
      <div
        ref={scrollRef}
        aria-live="polite"
        aria-atomic="false"
        className="flex-1 space-y-3 overflow-y-auto px-4 py-4"
      >
        {turns.map((turn) => (
          <Bubble key={turn.id} turn={turn} onPick={ask} disabled={pending} />
        ))}
        {pending && (
          <div className="flex gap-1.5 px-1 py-2" aria-label="Assistant is typing">
            {[0, 150, 300].map((delay) => (
              <span
                key={delay}
                className="size-1.5 animate-bounce rounded-full bg-ink-500"
                style={{ animationDelay: `${delay}ms` }}
              />
            ))}
          </div>
        )}
      </div>

      <form
        className="flex items-center gap-2 border-t border-ink-800 px-3 py-3"
        onSubmit={(e) => {
          e.preventDefault()
          void ask(draft)
        }}
      >
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask a question…"
          aria-label="Your question"
          maxLength={500}
          className="field !py-2 flex-1"
        />
        <button
          type="submit"
          disabled={pending || !draft.trim()}
          aria-label="Send"
          className="btn-primary !px-3 !py-2 disabled:opacity-40"
        >
          <SendIcon />
        </button>
      </form>
    </section>
  )
}

function Bubble({
  turn,
  onPick,
  disabled,
}: {
  turn: Turn
  onPick: (q: string) => void
  disabled: boolean
}) {
  const mine = turn.role === 'user'

  return (
    <div className={clsx('flex flex-col', mine ? 'items-end' : 'items-start')}>
      <div
        className={clsx(
          'max-w-[85%] whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-sm',
          mine
            ? 'rounded-br-sm bg-brand-500 text-white'
            : 'rounded-bl-sm bg-ink-800 text-ink-100',
          turn.grounded === false && !mine && 'border border-amber-900/60',
        )}
      >
        {turn.text}
      </div>

      {turn.sources && turn.sources.length > 0 && (
        <details className="mt-1.5 max-w-[85%] text-[11px] text-ink-500">
          <summary className="cursor-pointer hover:text-ink-300">
            {turn.sources.length} source{turn.sources.length > 1 ? 's' : ''}
          </summary>
          <ul className="mt-1.5 space-y-1.5">
            {turn.sources.map((s) => (
              <li key={s.section} className="rounded-lg bg-ink-850 px-2.5 py-2">
                <p className="font-medium text-ink-300">{s.section}</p>
                <p className="mt-0.5 text-ink-500">{s.excerpt}</p>
              </li>
            ))}
          </ul>
        </details>
      )}

      {turn.suggestions && turn.suggestions.length > 0 && (
        <div className="mt-2 flex max-w-[92%] flex-wrap gap-1.5">
          {turn.suggestions.map((s) => (
            <button
              key={s}
              disabled={disabled}
              onClick={() => onPick(s)}
              className="rounded-full border border-ink-700 px-2.5 py-1 text-[11px] text-ink-300 transition hover:border-brand-500 hover:text-ink-100 disabled:opacity-40"
            >
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function ChatIcon({ small = false }: { small?: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={small ? 'size-4' : 'size-6'}
      aria-hidden
    >
      <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
    </svg>
  )
}

function SendIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="size-4"
      aria-hidden
    >
      <path d="m22 2-7 20-4-9-9-4Z" />
      <path d="M22 2 11 13" />
    </svg>
  )
}
