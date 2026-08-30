/**
 * "Proceed to payment" must become clickable.
 *
 * The regression this guards: the button is gated on `!email`, and the contact
 * email defaults to the signed-in user's. The session hydrates *after* first
 * render, so seeding it with `useState(user?.email)` captured '' forever and
 * the button stayed disabled with no explanation. It looked like a dead button.
 *
 * These tests drive the real component through the real router and query
 * client, with only the network stubbed — the bug lived in the wiring, so
 * testing the component in isolation would have missed it.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { ApiClientError } from '@/api/client'
import { Checkout } from '@/pages/Checkout'
import { renderPage } from '@/test/harness'
import { useSession } from '@/store/session'
import { cancelHoldRelease } from '@/lib/holdRelease'
import { Bookings, Seats, Showtimes } from '@/api/endpoints'
import type { Hold, PriceQuote, User } from '@/api/types'

const HOLD: Hold = {
  hold_id: 'hold-1',
  show_id: 'show-1',
  seat_ids: ['s1', 's2'],
  seat_labels: ['E5', 'E6'],
  seat_count: 2,
  expires_at: new Date(Date.now() + 180_000).toISOString(),
  seconds_remaining: 180,
  subtotal_minor: 52000,
  is_kept: false,
}

const QUOTE: PriceQuote = {
  ticket_subtotal_minor: 52000,
  fnb_subtotal_minor: 0,
  discount_minor: 0,
  convenience_fee_minor: 4160,
  tax_minor: 10109,
  total_minor: 66269,
  currency: 'INR',
  lines: [{ label: 'Tickets x2', amount_minor: 52000, kind: 'tickets' }],
  offer_code: null,
  offer_label: null,
  offer_error: null,
}

const SIGNED_IN: User = {
  id: 'u1',
  email: 'asha@example.com',
  full_name: 'Asha',
  phone: null,
  role: 'customer',
  is_active: true,
  default_city_id: null,
  preferences: {},
  created_at: new Date().toISOString(),
}

function renderCheckout() {
  return renderPage(<Checkout />, {
    path: '/checkout/:holdId',
    route: '/checkout/hold-1',
  })
}

const proceed = () =>
  screen.getByRole('button', { name: /proceed to payment/i })

beforeEach(() => {
  vi.spyOn(Seats, 'getHold').mockResolvedValue(HOLD)
  vi.spyOn(Seats, 'release').mockResolvedValue({} as never)
  vi.spyOn(Bookings, 'quote').mockResolvedValue(QUOTE)
  vi.spyOn(Showtimes, 'show').mockResolvedValue({
    movie_title: 'Iron Meridian',
    cinema_name: 'PVR: Forum Mall',
    screen_name: 'Audi 1',
  } as never)
  useSession.setState({ user: null, city: null, hydrated: false })
})

describe('Checkout', () => {
  it('enables the proceed button once the session provides an email', async () => {
    renderCheckout()
    await screen.findByText(/review your booking/i)

    // The session hydrates after first render — exactly the timing that broke it.
    act(() => useSession.setState({ user: SIGNED_IN, hydrated: true }))

    await waitFor(() => expect(proceed()).toBeEnabled())
    expect(screen.getByLabelText(/email for the ticket/i)).toHaveValue(
      'asha@example.com',
    )
  })

  it('stays disabled for a guest until they type an email, and says why', async () => {
    renderCheckout()
    await screen.findByText(/review your booking/i)
    await waitFor(() => expect(proceed()).toBeDisabled())

    // A disabled control with no explanation is its own bug.
    expect(screen.getByText(/add an email address above/i)).toBeInTheDocument()

    await userEvent.type(
      screen.getByLabelText(/email for the ticket/i),
      'guest@example.com',
    )
    await waitFor(() => expect(proceed()).toBeEnabled())
  })

  it('keeps what the customer typed when the session hydrates later', async () => {
    renderCheckout()
    await screen.findByText(/review your booking/i)

    await userEvent.type(
      screen.getByLabelText(/email for the ticket/i),
      'typed@example.com',
    )
    // A late auth refresh must not overwrite the field under their cursor.
    act(() => useSession.setState({ user: SIGNED_IN, hydrated: true }))

    await waitFor(() =>
      expect(screen.getByLabelText(/email for the ticket/i)).toHaveValue(
        'typed@example.com',
      ),
    )
  })

  it('creates the booking with the resolved email when clicked', async () => {
    const create = vi
      .spyOn(Bookings, 'create')
      .mockResolvedValue({ id: 'booking-1' } as never)

    renderCheckout()
    await screen.findByText(/review your booking/i)
    act(() => useSession.setState({ user: SIGNED_IN, hydrated: true }))
    await waitFor(() => expect(proceed()).toBeEnabled())

    await userEvent.click(proceed())

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1))
    const [body, idempotencyKey] = create.mock.calls[0]
    expect(body).toMatchObject({
      hold_id: 'hold-1',
      contact_email: 'asha@example.com',
    })
    // Every attempt carries an idempotency key, so a double-click cannot
    // produce two bookings.
    expect(idempotencyKey).toBeTruthy()
  })

  it('offers to keep the seats while the hold is only a short selection', async () => {
    renderCheckout()
    await screen.findByText(/review your booking/i)
    expect(
      screen.getByRole('button', { name: /keep seats on hold/i }),
    ).toBeInTheDocument()
  })
})

describe('Checkout hold release', () => {
  /**
   * What actually protects against StrictMode is that the release is
   * *cancellable*, not that it is skipped. So that is what is asserted here.
   *
   * Reproducing StrictMode's double-invoke through the test wrapper turned out
   * to be unreliable -- an earlier version of this test rendered inside
   * `<StrictMode>` and passed even with the bug reintroduced, which is worse
   * than having no test. Expressing the same sequence explicitly (unmount, then
   * an immediate remount cancels) is deterministic and does discriminate: an
   * implementation that releases synchronously in cleanup fails it.
   */
  it('a release queued on leaving can still be called off', async () => {
    const release = vi.spyOn(Seats, 'release').mockResolvedValue({} as never)

    const { unmount } = renderCheckout()
    await screen.findByText(/review your booking/i)

    unmount()
    // The remount StrictMode performs immediately after its fake unmount.
    cancelHoldRelease('hold-1')

    await new Promise((resolve) => setTimeout(resolve, 900))
    expect(release).not.toHaveBeenCalled()
  })

  it('releases the seats when the customer really does leave', async () => {
    const release = vi.spyOn(Seats, 'release').mockResolvedValue({} as never)

    const { unmount } = renderCheckout()
    await screen.findByText(/review your booking/i)
    unmount()

    await waitFor(
      () => expect(release).toHaveBeenCalledWith('hold-1', 'abandoned'),
      { timeout: 2000 },
    )
  })

  it('shows the expired screen when the quote reports a dead hold', async () => {
    // The countdown cannot see a hold released elsewhere; the quote can.
    vi.spyOn(Bookings, 'quote').mockRejectedValue(
      new ApiClientError('Your seat hold expired.', 'HOLD_EXPIRED', 409),
    )

    renderCheckout()

    expect(await screen.findByText(/your seat hold expired/i)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /choose seats again/i }),
    ).toBeInTheDocument()
  })
})
