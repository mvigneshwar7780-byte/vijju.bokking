import { Seats } from '@/api/endpoints'

/**
 * Deferred hold release, safe under React StrictMode.
 *
 * Releasing a seat hold in an effect's cleanup looks right and is wrong in
 * development: StrictMode deliberately mounts, unmounts and remounts every
 * component to surface impure effects. The cleanup therefore runs on *page
 * load*, so the seats were handed back the moment checkout opened. The
 * countdown carried on ticking against the timestamp fetched before that, so
 * the page looked healthy while every request against the hold returned
 * "hold expired".
 *
 * The fix is to make the release cancellable rather than immediate. Cleanup
 * schedules it; a remount within the grace window cancels it. StrictMode's
 * remount is effectively instantaneous, so it always cancels; a real navigation
 * never remounts, so the release always fires.
 *
 * Destructive work in effect cleanup needs this shape in general — the cleanup
 * is not a reliable signal that the user went anywhere.
 */
const GRACE_MS = 500

const pending = new Map<string, ReturnType<typeof setTimeout>>()

export function scheduleHoldRelease(holdId: string): void {
  if (!holdId || pending.has(holdId)) return
  pending.set(
    holdId,
    setTimeout(() => {
      pending.delete(holdId)
      void Seats.release(holdId, 'abandoned').catch(() => undefined)
    }, GRACE_MS),
  )
}

export function cancelHoldRelease(holdId: string): void {
  const timer = pending.get(holdId)
  if (timer !== undefined) {
    clearTimeout(timer)
    pending.delete(holdId)
  }
}

/** Test helper: is a release currently queued for this hold? */
export function isReleasePending(holdId: string): boolean {
  return pending.has(holdId)
}
