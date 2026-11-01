/**
 * Opening the chat widget from elsewhere in the app.
 *
 * A DOM event rather than shared state: the widget owns its own transcript and
 * open/closed flag, and lifting that into a store so one button could reach it
 * would make every page re-render on every keystroke typed into the chat.
 *
 * The widget listens while it is mounted; if it is not, dispatching is a no-op
 * rather than an error.
 */

const EVENT = 'cineai:assistant-open'

export type AssistantOpenDetail = { question?: string }

/** Open the assistant, optionally pre-filling a question to send. */
export function openAssistant(question?: string): void {
  window.dispatchEvent(
    new CustomEvent<AssistantOpenDetail>(EVENT, { detail: { question } }),
  )
}

/** Subscribe. Returns the unsubscribe function, for an effect cleanup. */
export function onAssistantOpen(
  handler: (detail: AssistantOpenDetail) => void,
): () => void {
  const listener = (e: Event) => handler((e as CustomEvent<AssistantOpenDetail>).detail ?? {})
  window.addEventListener(EVENT, listener)
  return () => window.removeEventListener(EVENT, listener)
}
