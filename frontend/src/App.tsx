import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Layout } from '@/components/Layout'
import { Home } from '@/pages/Home'
import { MovieDetail } from '@/pages/MovieDetail'
import { Showtimes } from '@/pages/Showtimes'
import { SeatSelection } from '@/pages/SeatSelection'
import { Checkout } from '@/pages/Checkout'
import { Payment } from '@/pages/Payment'
import { Ticket } from '@/pages/Ticket'
import { MyBookings } from '@/pages/MyBookings'
import { Login } from '@/pages/Login'
import { Cinemas } from '@/pages/Cinemas'
import { CinemaDetail } from '@/pages/CinemaDetail'
import { OperatorLayout } from '@/pages/operator/OperatorLayout'
import { OperatorScreens } from '@/pages/operator/Screens'
import { OperatorShows } from '@/pages/operator/Shows'
import { OperatorBookings } from '@/pages/operator/Bookings'
import { OperatorReports } from '@/pages/operator/Reports'
import { AdminUsers } from '@/pages/admin/Users'
import { ApiClientError } from '@/api/client'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      // A 4xx is the server telling you the request was wrong. Retrying it
      // just repeats the mistake — only retry transient failures.
      retry: (failureCount, error) => {
        if (error instanceof ApiClientError && error.status >= 400 && error.status < 500) {
          return false
        }
        return failureCount < 2
      },
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Home />} />
            <Route path="movies/:movieId" element={<MovieDetail />} />
            <Route path="movies/:movieId/showtimes" element={<Showtimes />} />
            <Route path="shows/:showId/seats" element={<SeatSelection />} />
            <Route path="checkout/:holdId" element={<Checkout />} />
            <Route path="pay/:bookingId" element={<Payment />} />
            <Route path="tickets/:bookingId" element={<Ticket />} />
            <Route path="cinemas" element={<Cinemas />} />
            <Route path="cinemas/:cinemaId" element={<CinemaDetail />} />
            <Route path="bookings" element={<MyBookings />} />

            {/* Operator console. Access is enforced server-side on every
                request; this route guard only avoids showing a dead UI. */}
            {/* Platform administration. Server-enforced on every request;
                these guards only avoid rendering a dead page. */}
            <Route path="admin/users" element={<AdminUsers />} />

            <Route path="operator" element={<OperatorLayout />}>
              <Route path=":cinemaId/screens" element={<OperatorScreens />} />
              <Route path=":cinemaId/shows" element={<OperatorShows />} />
              <Route path=":cinemaId/bookings" element={<OperatorBookings />} />
              <Route path=":cinemaId/reports" element={<OperatorReports />} />
            </Route>
            <Route path="login" element={<Login />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
