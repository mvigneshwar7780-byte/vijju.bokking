/**
 * Releasing a hold must survive React StrictMode.
 *
 * StrictMode mounts, unmounts and remounts every component in development. An
 * effect cleanup that releases the seats therefore fires on *page load* — which
 * is exactly what happened: checkout opened, the seats went back on sale
 * immediately, the countdown kept ticking against a timestamp fetched before
 * that, and every request against the hold returned "hold expired" while the
 * page looked perfectly healthy.
 *
 * So the release is scheduled and cancellable: a remount inside the grace
 * window calls it off, a genuine navigation does not.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Seats } from '@/api/endpoints'
import {
  cancelHoldRelease,
  isReleasePending,
  scheduleHoldRelease,
} from '@/lib/holdRelease'

const HOLD = 'hold-1'

beforeEach(() => {
  vi.useFakeTimers()
  vi.spyOn(Seats, 'release').mockResolvedValue({} as never)
})

afterEach(() => {
  cancelHoldRelease(HOLD)
  vi.useRealTimers()
})

describe('deferred hold release', () => {
  it('releases the seats after a real navigation away', async () => {
    scheduleHoldRelease(HOLD)
    expect(isReleasePending(HOLD)).toBe(true)
    expect(Seats.release).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(1000)

    expect(Seats.release).toHaveBeenCalledWith(HOLD, 'abandoned')
    expect(isReleasePending(HOLD)).toBe(false)
  })

  it('does NOT release when the component remounts immediately', async () => {
    // The StrictMode sequence: mount, cleanup, mount again.
    scheduleHoldRelease(HOLD)   // cleanup from the simulated unmount
    cancelHoldRelease(HOLD)     // the immediate remount

    await vi.advanceTimersByTimeAsync(5000)

    expect(Seats.release).not.toHaveBeenCalled()
    expect(isReleasePending(HOLD)).toBe(false)
  })

  it('is idempotent — repeated scheduling releases once', async () => {
    scheduleHoldRelease(HOLD)
    scheduleHoldRelease(HOLD)
    scheduleHoldRelease(HOLD)

    await vi.advanceTimersByTimeAsync(1000)

    expect(Seats.release).toHaveBeenCalledTimes(1)
  })

  it('cancelling an unscheduled hold is harmless', () => {
    expect(() => cancelHoldRelease('never-scheduled')).not.toThrow()
  })

  it('tracks holds independently', async () => {
    scheduleHoldRelease('hold-a')
    scheduleHoldRelease('hold-b')
    cancelHoldRelease('hold-a')

    await vi.advanceTimersByTimeAsync(1000)

    expect(Seats.release).toHaveBeenCalledTimes(1)
    expect(Seats.release).toHaveBeenCalledWith('hold-b', 'abandoned')
  })
})
