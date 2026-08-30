import type { ReactElement, ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { render } from '@testing-library/react'

/**
 * Render a page the way the app does — router, query client, providers — so a
 * test exercises the real wiring rather than a component in isolation. Most of
 * the frontend bugs worth catching live in that wiring.
 */
export function renderPage(
  ui: ReactElement,
  { path, route }: { path: string; route: string },
): ReturnType<typeof render> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[route]}>
          <Routes>
            <Route path={path} element={children} />
            {/* Catch-all so a successful navigation is not reported as an
                unmatched route. Tests assert on the call, not the destination. */}
            <Route path="*" element={<div data-testid="navigated" />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    )
  }

  return render(ui, { wrapper: Wrapper })
}
