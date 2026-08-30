import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

/**
 * Provide `localStorage`.
 *
 * Under Node 26 + jsdom neither `window.localStorage` nor the global exists --
 * Node defines its own global that is undefined without `--localstorage-file`,
 * and it shadows jsdom's. The app stores auth tokens and the guest session key
 * there, so without this every test dies inside zustand's persist middleware.
 *
 * A tiny in-memory implementation is the right answer: deterministic, cleared
 * between tests, and independent of how the two runtimes negotiate the API.
 */
class MemoryStorage implements Storage {
  #items = new Map<string, string>()

  get length(): number { return this.#items.size }
  key(index: number): string | null { return [...this.#items.keys()][index] ?? null }
  getItem(key: string): string | null { return this.#items.get(key) ?? null }
  setItem(key: string, value: string): void { this.#items.set(key, String(value)) }
  removeItem(key: string): void { this.#items.delete(key) }
  clear(): void { this.#items.clear() }
}

for (const target of [globalThis, typeof window !== 'undefined' ? window : null]) {
  if (!target) continue
  Object.defineProperty(target, 'localStorage', {
    value: new MemoryStorage(),
    configurable: true,
    writable: true,
  })
}

// jsdom has no crypto.randomUUID; the app uses it for session and idempotency
// keys, so give it a deterministic stand-in.
if (!globalThis.crypto?.randomUUID) {
  let n = 0
  Object.defineProperty(globalThis, 'crypto', {
    value: {
      ...globalThis.crypto,
      randomUUID: () => `00000000-0000-4000-8000-${String(++n).padStart(12, '0')}`,
    },
    configurable: true,
  })
}

afterEach(() => {
  cleanup()
  globalThis.localStorage?.clear()
  vi.restoreAllMocks()
})
