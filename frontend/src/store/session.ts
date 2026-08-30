/** Client state that outlives a page: who is signed in, and which city they
 *  are browsing. Everything else is server state and belongs to React Query. */
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { Auth } from '@/api/endpoints'
import { tokenStore } from '@/api/client'
import type { City, User } from '@/api/types'

interface SessionState {
  user: User | null
  city: City | null
  hydrated: boolean
  setCity: (city: City) => void
  signIn: (email: string, password: string) => Promise<void>
  register: (body: { email: string; password: string; full_name: string }) => Promise<void>
  signOut: () => Promise<void>
  hydrate: () => Promise<void>
}

export const useSession = create<SessionState>()(
  persist(
    (set, get) => ({
      user: null,
      city: null,
      hydrated: false,

      setCity: (city) => set({ city }),

      signIn: async (email, password) => {
        const { user, tokens } = await Auth.login({ email, password })
        tokenStore.set(tokens)
        set({ user })
      },

      register: async (body) => {
        const { user, tokens } = await Auth.register(body)
        tokenStore.set(tokens)
        set({ user })
      },

      signOut: async () => {
        const refresh = tokenStore.refresh
        if (refresh) await Auth.logout(refresh).catch(() => undefined)
        tokenStore.clear()
        set({ user: null })
      },

      /** Re-validate a persisted session on boot: a stored user object means
       *  nothing if the refresh token has since been revoked. */
      hydrate: async () => {
        if (get().hydrated) return
        if (!tokenStore.access && !tokenStore.refresh) {
          set({ hydrated: true, user: null })
          return
        }
        try {
          set({ user: await Auth.me(), hydrated: true })
        } catch {
          tokenStore.clear()
          set({ user: null, hydrated: true })
        }
      },
    }),
    {
      // Distinct from `cineai.guest` in api/client.ts. These two must never
      // share a key: this one holds a JSON blob, that one holds a 32-char id.
      name: 'cineai.app',
      partialize: (s) => ({ city: s.city, user: s.user }),
    },
  ),
)
