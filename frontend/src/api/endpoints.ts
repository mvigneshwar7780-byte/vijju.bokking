/** Thin, typed wrappers over the API. One function per endpoint, no logic. */
import { api, sessionKey } from './client'
import type {
  AuthResponse, Booking, CancellationQuote, Cinema, CinemaMovies, City, FnbItem, Genre,
  Hold, Language, LayoutPreview, LayoutRowInput, MovieCard, MovieDetail,
  MoviePriceComparison, OccupancyReport, OperatorBooking, Page, PriceQuote,
  RevenueReport, ScreenAdmin, SeatCategoryAdmin, SeatMap, ShowAdmin, ShowSummary,
  ShowtimeBoard, StartPayment, User, UserAdmin,
} from './types'

export const Auth = {
  register: (body: { email: string; password: string; full_name: string; phone?: string }) =>
    api.post<AuthResponse>('/auth/register', body).then((r) => r.data),
  login: (body: { email: string; password: string }) =>
    api.post<AuthResponse>('/auth/login', body).then((r) => r.data),
  logout: (refresh_token: string) =>
    api.post('/auth/logout', { refresh_token }).then((r) => r.data),
  me: () => api.get<User>('/me').then((r) => r.data),
}

export const Catalog = {
  cities: () => api.get<City[]>('/cities').then((r) => r.data),
  movies: (params: {
    status?: string; city_id?: string; genre?: string; language?: string
    q?: string; page?: number; page_size?: number
  }) => api.get<Page<MovieCard>>('/movies', { params }).then((r) => r.data),
  movie: (id: string) => api.get<MovieDetail>(`/movies/${id}`).then((r) => r.data),
  genres: () => api.get<Genre[]>('/genres').then((r) => r.data),
  languages: () => api.get<Language[]>('/languages').then((r) => r.data),
}

export const Showtimes = {
  board: (params: { movie_id: string; city_id: string; date?: string }) =>
    api.get<ShowtimeBoard>('/showtimes', { params }).then((r) => r.data),
  show: (id: string) => api.get<ShowSummary & Record<string, unknown>>(`/shows/${id}`).then((r) => r.data),
}

export const Seats = {
  map: (showId: string) => api.get<SeatMap>(`/shows/${showId}/seatmap`).then((r) => r.data),
  hold: (showId: string, seatIds: string[]) =>
    api.post<Hold>('/holds', {
      show_id: showId, seat_ids: seatIds, session_key: sessionKey(),
    }).then((r) => r.data),
  getHold: (holdId: string) =>
    api.get<Hold>(`/holds/${holdId}`, { params: { session_key: sessionKey() } }).then((r) => r.data),
  /** Ask to hold the seats for the full window (and survive navigation). */
  keep: (holdId: string) =>
    api.post<Hold>(`/holds/${holdId}/keep`, { session_key: sessionKey() })
      .then((r) => r.data),

  release: (holdId: string, reason: 'explicit' | 'abandoned' = 'explicit') =>
    api.delete(`/holds/${holdId}`, { data: { session_key: sessionKey(), reason } })
      .then((r) => r.data),

  /**
   * Release on tab-close / navigation away.
   *
   * `keepalive` lets the request outlive the page, which a normal XHR does not
   * -- without it, closing the tab leaves the seats held until the TTL lapses,
   * which is the whole problem this is here to avoid. `sendBeacon` would be the
   * usual tool but it only issues POST.
   */
  releaseBeacon: (holdId: string) => {
    try {
      void fetch(`/api/v1/holds/${holdId}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_key: sessionKey(), reason: 'abandoned' }),
        keepalive: true,
      })
    } catch {
      /* best effort: the hold's TTL is the backstop */
    }
  },
}

export const Fnb = {
  forCinema: (cinemaId: string) =>
    api.get<FnbItem[]>(`/cinemas/${cinemaId}/fnb`).then((r) => r.data),
}

export const Bookings = {
  quote: (body: {
    hold_id: string
    fnb?: { fnb_item_id: string; quantity: number }[]
    offer_code?: string | null
  }) => api.post<PriceQuote>('/bookings/quote', { ...body, session_key: sessionKey() }).then((r) => r.data),

  create: (
    body: {
      hold_id: string
      contact_email: string
      contact_phone?: string | null
      fnb?: { fnb_item_id: string; quantity: number }[]
      offer_code?: string | null
    },
    idempotencyKey: string,
  ) =>
    api.post<Booking>('/bookings', { ...body, session_key: sessionKey() }, {
      headers: { 'Idempotency-Key': idempotencyKey },
    }).then((r) => r.data),

  get: (id: string) => api.get<Booking>(`/bookings/${id}`).then((r) => r.data),
  mine: (page = 1) =>
    api.get<Page<Booking>>('/bookings', { params: { page, page_size: 20 } }).then((r) => r.data),
  cancellationQuote: (id: string) =>
    api.get<CancellationQuote>(`/bookings/${id}/cancellation-quote`).then((r) => r.data),
  cancel: (id: string, reason?: string) =>
    api.post<Booking>(`/bookings/${id}/cancel`, { reason }).then((r) => r.data),
}

export const Payments = {
  start: (bookingId: string, method: string) =>
    api.post<StartPayment>(`/bookings/${bookingId}/pay`, { method }).then((r) => r.data),
  /** Stands in for the PSP's hosted checkout page. The gateway then delivers a
   *  signed webhook to the API, which is what actually confirms the booking. */
  completeMock: (orderId: string, outcome: 'success' | 'failure', method: string) =>
    api.post<{ outcome: string; status: string }>(
      `/payments/mock/${orderId}/complete`, null, { params: { outcome, method } },
    ).then((r) => r.data),
}

export const Browse = {
  /** Cinema-first: everything playing at one hall, at that hall's prices. */
  moviesAtCinema: (cinemaId: string, date?: string) =>
    api.get<CinemaMovies>(`/cinemas/${cinemaId}/movies`, { params: { date } })
      .then((r) => r.data),

  /** Movie-first: every hall showing this film, cheapest first. */
  cinemasForMovie: (movieId: string, cityId: string, date?: string) =>
    api.get<MoviePriceComparison>(`/movies/${movieId}/cinemas`, {
      params: { city_id: cityId, date },
    }).then((r) => r.data),
}

export const Operator = {
  cinemas: () => api.get<Cinema[]>('/operator/cinemas').then((r) => r.data),
  createCinema: (body: Record<string, unknown>) =>
    api.post<Cinema>('/operator/cinemas', body).then((r) => r.data),
  updateCinema: (id: string, body: Record<string, unknown>) =>
    api.patch<Cinema>(`/operator/cinemas/${id}`, body).then((r) => r.data),

  seatCategories: (cinemaId: string) =>
    api.get<SeatCategoryAdmin[]>(`/operator/cinemas/${cinemaId}/seat-categories`)
      .then((r) => r.data),
  createSeatCategory: (cinemaId: string, body: Record<string, unknown>) =>
    api.post(`/operator/cinemas/${cinemaId}/seat-categories`, body).then((r) => r.data),

  screens: (cinemaId: string) =>
    api.get<ScreenAdmin[]>(`/operator/cinemas/${cinemaId}/screens`).then((r) => r.data),
  createScreen: (cinemaId: string, body: Record<string, unknown>) =>
    api.post<ScreenAdmin>(`/operator/cinemas/${cinemaId}/screens`, body).then((r) => r.data),
  setLayout: (screenId: string, body: { rows: LayoutRowInput[]; screen_label?: string }) =>
    api.put<LayoutPreview>(`/operator/screens/${screenId}/layout`, body).then((r) => r.data),

  movies: (page = 1) =>
    api.get<Page<MovieDetail>>('/operator/movies', { params: { page, page_size: 50 } })
      .then((r) => r.data),
  createMovie: (body: Record<string, unknown>) =>
    api.post<MovieDetail>('/operator/movies', body).then((r) => r.data),

  shows: (cinemaId: string, from: string, to: string) =>
    api.get<ShowAdmin[]>(`/operator/cinemas/${cinemaId}/shows`, {
      params: { date_from: from, date_to: to },
    }).then((r) => r.data),
  createShow: (cinemaId: string, body: Record<string, unknown>) =>
    api.post<ShowAdmin>(`/operator/cinemas/${cinemaId}/shows`, body).then((r) => r.data),
  cancelShow: (showId: string, reason: string) =>
    api.post(`/operator/shows/${showId}/cancel`, { reason }).then((r) => r.data),
  setPrices: (showId: string, prices: { seat_category_id: string; price_minor: number }[]) =>
    api.put<ShowAdmin>(`/operator/shows/${showId}/prices`, prices).then((r) => r.data),

  bookings: (cinemaId: string, page = 1) =>
    api.get<Page<OperatorBooking>>(`/operator/cinemas/${cinemaId}/bookings`, {
      params: { page, page_size: 20 },
    }).then((r) => r.data),

  revenue: (cinemaId: string, from: string, to: string, groupBy = 'day') =>
    api.get<RevenueReport>(`/operator/cinemas/${cinemaId}/reports/revenue`, {
      params: { date_from: from, date_to: to, group_by: groupBy },
    }).then((r) => r.data),
  occupancy: (cinemaId: string, from: string, to: string) =>
    api.get<OccupancyReport>(`/operator/cinemas/${cinemaId}/reports/occupancy`, {
      params: { date_from: from, date_to: to },
    }).then((r) => r.data),
}

export const PaymentActions = {
  cancel: (bookingId: string) =>
    api.post<{ status: string; retryable?: boolean }>(
      `/bookings/${bookingId}/payment/cancel`,
    ).then((r) => r.data),
  settleMock: (orderId: string, outcome: 'success' | 'failure') =>
    api.post<{ status: string }>(`/payments/mock/${orderId}/settle`, null, {
      params: { outcome },
    }).then((r) => r.data),
}

export const Admin = {
  users: (page = 1, role?: string) =>
    api.get<{
      items: UserAdmin[]
      total: number
      page: number
      page_size: number
    }>('/admin/users', { params: { page, page_size: 50, role } }).then((r) => r.data),

  setRole: (userId: string, role: 'customer' | 'cinema_operator' | 'admin') =>
    api.put<{ ok: boolean; message: string }>(`/admin/users/${userId}/role`, { role })
      .then((r) => r.data),

  cinemas: () => api.get<Cinema[]>('/admin/cinemas').then((r) => r.data),

  assignOperator: (cinemaId: string, operatorUserId: string | null) =>
    api.put<Cinema>(`/admin/cinemas/${cinemaId}/operator`, {
      operator_user_id: operatorUserId,
    }).then((r) => r.data),
}
