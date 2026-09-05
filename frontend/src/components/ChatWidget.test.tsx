/**
 * The chat widget's two states, and the behaviour that is easy to regress.
 *
 * The collapsed/expanded transition is the whole brief ("an icon if not used, a
 * normal chatbot when using it"), so it is asserted directly rather than through
 * a snapshot that would pass whatever the markup happened to be.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ChatWidget } from '@/components/ChatWidget'
import { Assistant } from '@/api/endpoints'

vi.mock('@/api/endpoints', () => ({
  Assistant: { ask: vi.fn() },
}))

const asked = vi.mocked(Assistant.ask)

const REPLY = {
  answer: 'Refunds are issued to the original payment method within five days.',
  sources: [{ section: 'Policy: Ticket Cancellation and Refund Schedule', excerpt: 'Refunds…' }],
  suggestions: ['Can I change my seat?'],
  grounded: true,
}

describe('ChatWidget', () => {
  beforeEach(() => {
    localStorage.clear()
    asked.mockReset()
  })

  it('shows only a launcher icon until it is opened', () => {
    render(<ChatWidget />)

    expect(screen.getByRole('button', { name: /open the help assistant/i })).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('opens into a chat panel and closes back to the icon', async () => {
    const user = userEvent.setup()
    render(<ChatWidget />)

    await user.click(screen.getByRole('button', { name: /open the help assistant/i }))

    expect(screen.getByRole('dialog', { name: /help assistant/i })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: /your question/i })).toBeInTheDocument()
    // The launcher is replaced by the panel, not shown alongside it.
    expect(screen.queryByRole('button', { name: /open the help assistant/i })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /close the help assistant/i }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /open the help assistant/i })).toBeInTheDocument()
  })

  it('closes on Escape', async () => {
    const user = userEvent.setup()
    render(<ChatWidget />)

    await user.click(screen.getByRole('button', { name: /open the help assistant/i }))
    await user.keyboard('{Escape}')

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('sends a question and renders the answer with its source', async () => {
    const user = userEvent.setup()
    asked.mockResolvedValue(REPLY)
    render(<ChatWidget />)

    await user.click(screen.getByRole('button', { name: /open the help assistant/i }))
    await user.type(screen.getByRole('textbox', { name: /your question/i }), 'how do refunds work?')
    await user.click(screen.getByRole('button', { name: /send/i }))

    expect(asked).toHaveBeenCalledWith('how do refunds work?')
    expect(await screen.findByText(REPLY.answer)).toBeInTheDocument()
    expect(screen.getByText('1 source')).toBeInTheDocument()
  })

  it('persists the conversation across a full remount', async () => {
    const user = userEvent.setup()
    asked.mockResolvedValue(REPLY)

    const first = render(<ChatWidget />)
    await user.click(screen.getByRole('button', { name: /open the help assistant/i }))
    await user.type(screen.getByRole('textbox', { name: /your question/i }), 'refunds?')
    await user.click(screen.getByRole('button', { name: /send/i }))
    await screen.findByText(REPLY.answer)

    // Unmount, not just close. Closing the panel leaves the component mounted,
    // so React state alone would carry the transcript and the assertion would
    // pass even with persistence deleted -- this must survive a real navigation.
    first.unmount()
    render(<ChatWidget />)
    await user.click(screen.getByRole('button', { name: /open the help assistant/i }))

    expect(screen.getByText(REPLY.answer)).toBeInTheDocument()
    expect(asked).toHaveBeenCalledTimes(1)
  })

  it('reports a failure instead of hanging on the typing indicator', async () => {
    const user = userEvent.setup()
    asked.mockRejectedValue(new Error('Network Error'))
    render(<ChatWidget />)

    await user.click(screen.getByRole('button', { name: /open the help assistant/i }))
    await user.type(screen.getByRole('textbox', { name: /your question/i }), 'refunds?')
    await user.click(screen.getByRole('button', { name: /send/i }))

    expect(await screen.findByText(/could not reach the help service/i)).toBeInTheDocument()
    // The composer must come back so the customer can retry.
    await waitFor(() =>
      expect(screen.getByRole('textbox', { name: /your question/i })).toBeEnabled(),
    )
  })

  it('will not send an empty question', async () => {
    const user = userEvent.setup()
    render(<ChatWidget />)

    await user.click(screen.getByRole('button', { name: /open the help assistant/i }))
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled()

    await user.type(screen.getByRole('textbox', { name: /your question/i }), '   ')
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled()
    expect(asked).not.toHaveBeenCalled()
  })

  it('survives localStorage being unavailable', async () => {
    const user = userEvent.setup()
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('The operation is insecure.')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('The operation is insecure.')
    })

    render(<ChatWidget />)
    await user.click(screen.getByRole('button', { name: /open the help assistant/i }))

    // A private window must get a working chat, not a blank screen.
    expect(screen.getByRole('dialog', { name: /help assistant/i })).toBeInTheDocument()
    vi.restoreAllMocks()
  })
})
