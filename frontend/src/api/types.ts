/** Response shapes mirroring the FastAPI schemas. Kept hand-written and small:
 *  generating them from OpenAPI is the right move once the API stabilises. */

export interface ApiError {
  error: { code: string; message: string; details: Record<string, unknown> }
  request_id: string | null
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
  has_next: boolean
}

export interface City {
  id: string
  name: string
  slug: string
  state: string | null
  timezone: string
}

export interface Cinema {
  id: string
  name: string
  slug: string
  brand: string | null
  address_line: string
  locality: string | null
  city_id: string
  amenities: string[]
  latitude: number | null
  longitude: number | null
}

export interface Genre { id: string; name: string; slug: string }
export interface Language { id: string; code: string; name: string; native_name: string | null }

export interface MovieCard {
  id: string
  title: string
  slug: string
  tagline: string | null
  runtime_minutes: number
  certification: string | null
  release_date: string | null
  status: string
  poster_url: string | null
  rating_average: number | null
  rating_count: number
  genres: Genre[]
  languages: Language[]
}

export interface Person { id: string; name: string; photo_url: string | null }
export interface Credit {
  person: Person
  credit_type: string
  character_name: string | null
  job: string | null
}

export interface MovieDetail extends MovieCard {
  synopsis: string
  backdrop_url: string | null
  trailer_url: string | null
  popularity_score: number
  ai_summary: string | null
  ai_attributes: Record<string, unknown>
  credits: Credit[]
}

export interface ShowCard {
  id: string
  starts_at: string
  ends_at: string
  show_date: string
  format_code: string
  format_name: string
  audio_language: string
  subtitle_language: string | null
  screen_name: string
  status: string
  available_seats: number
  total_seats: number
  min_price_minor: number
  availability_band: 'available' | 'filling_fast' | 'almost_full' | 'sold_out'
  is_bookable: boolean
}

export interface CinemaShows {
  cinema_id: string
  cinema_name: string
  brand: string | null
  locality: string | null
  amenities: string[]
  shows: ShowCard[]
}

export interface ShowtimeBoard {
  movie_id: string
  movie_title: string
  city_id: string
  city_name: string
  show_date: string
  available_dates: string[]
  cinemas: CinemaShows[]
}

export interface Seat {
  show_seat_id: string
  seat_id: string
  label: string
  row_label: string
  row_index: number
  seat_number: number
  column_index: number
  category_id: string
  category_code: string
  category_name: string
  price_minor: number
  status: 'available' | 'held' | 'booked' | 'blocked'
  is_aisle: boolean
  is_wheelchair_accessible: boolean
}

export interface SeatRow { row_label: string; row_index: number; seats: Seat[] }

export interface SeatCategorySummary {
  category_id: string
  code: string
  name: string
  price_minor: number
  available: number
  total: number
}

export interface SeatMap {
  show_id: string
  screen_name: string
  cinema_name: string
  movie_title: string
  starts_at: string
  rows: SeatRow[]
  categories: SeatCategorySummary[]
  available_seats: number
  total_seats: number
  max_seats_per_booking: number
  layout_meta: { aisles_after_columns?: number[]; screen_label?: string }
}

export interface Hold {
  hold_id: string
  show_id: string
  seat_ids: string[]
  seat_labels: string[]
  seat_count: number
  expires_at: string
  seconds_remaining: number
  subtotal_minor: number
  is_kept: boolean
}

export interface PriceLine { label: string; amount_minor: number; kind: string }

export interface PriceQuote {
  ticket_subtotal_minor: number
  fnb_subtotal_minor: number
  discount_minor: number
  convenience_fee_minor: number
  tax_minor: number
  total_minor: number
  currency: string
  lines: PriceLine[]
  offer_code: string | null
  offer_label: string | null
  offer_error: string | null
}

export interface FnbItem {
  id: string
  name: string
  description: string | null
  category: string
  price_minor: number
  image_url: string | null
  is_vegetarian: boolean
}

export interface ShowSummary {
  show_id: string
  movie_title: string
  movie_poster_url: string | null
  certification: string | null
  cinema_name: string
  screen_name: string
  city_name: string
  format_code: string
  language: string
  starts_at: string
  ends_at: string
}

export type BookingStatus =
  | 'draft' | 'payment_pending' | 'confirmed' | 'payment_failed'
  | 'expired' | 'cancelled' | 'refunded' | 'revoked'

export interface Refund {
  id: string
  amount_minor: number
  status: 'pending' | 'succeeded' | 'failed'
  reason: string
  created_at: string
  completed_at: string | null
}

export interface Booking {
  id: string
  booking_reference: string
  status: BookingStatus
  seat_count: number
  show: ShowSummary
  seats: { seat_label: string; seat_category_name: string; price_minor: number }[]
  fnb_items: { item_name: string; quantity: number; unit_price_minor: number; total_minor: number }[]
  ticket_subtotal_minor: number
  fnb_subtotal_minor: number
  discount_minor: number
  convenience_fee_minor: number
  tax_minor: number
  total_minor: number
  currency: string
  price_breakdown: Record<string, unknown>
  offer_code: string | null
  contact_email: string
  contact_phone: string | null
  payment_deadline_at: string | null
  confirmed_at: string | null
  cancelled_at: string | null
  qr_payload: string | null
  created_at: string
  refunds: Refund[]
  refunded_minor: number
  cancellation: CancellationQuote | null
}

export interface StartPayment {
  payment_id: string
  booking_id: string
  gateway: string
  gateway_order_id: string
  checkout_url: string | null
  amount_minor: number
  currency: string
  expires_at: string | null
}

export interface CancellationQuote {
  refundable: boolean
  refund_minor: number
  forfeited_minor: number
  reason: string
}

export interface User {
  id: string
  email: string
  full_name: string
  phone: string | null
  role: 'customer' | 'cinema_operator' | 'admin'
  is_active: boolean
  default_city_id: string | null
  preferences: Record<string, unknown>
  created_at: string
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
  expires_at: string
}

export interface AuthResponse { user: User; tokens: TokenPair }

// --- browse by cinema / price comparison ---------------------------------

export interface CinemaMovie {
  movie_id: string
  title: string
  slug: string
  poster_url: string | null
  certification: string | null
  runtime_minutes: number
  rating_average: number | null
  genres: string[]
  languages: string[]
  formats: string[]
  show_count: number
  next_show_at: string | null
  min_price_minor: number
  max_price_minor: number
  available_dates: string[]
}

export interface CinemaMovies {
  cinema_id: string
  cinema_name: string
  brand: string | null
  locality: string | null
  city_name: string
  amenities: string[]
  show_date: string | null
  movies: CinemaMovie[]
}

export interface CinemaPrice {
  cinema_id: string
  cinema_name: string
  brand: string | null
  locality: string | null
  amenities: string[]
  distance_km: number | null
  show_count: number
  earliest_show_at: string
  latest_show_at: string
  min_price_minor: number
  max_price_minor: number
  formats: string[]
  languages: string[]
  total_available_seats: number
}

export interface MoviePriceComparison {
  movie_id: string
  movie_title: string
  poster_url: string | null
  city_id: string
  city_name: string
  show_date: string
  available_dates: string[]
  cheapest_minor: number | null
  dearest_minor: number | null
  cinemas: CinemaPrice[]
}

// --- operator -------------------------------------------------------------

export interface SeatCategoryAdmin {
  id: string
  code: string
  name: string
  description: string | null
  default_price_minor: number
  display_order: number
  color_hex: string | null
}

export interface ScreenAdmin {
  id: string
  name: string
  screen_number: number
  supported_formats: string[]
  sound_system: string | null
  total_seats: number
}

export interface LayoutRowInput {
  row_label: string
  seat_count: number
  category_code: string
  aisles_after: number[]
  wheelchair_seats: number[]
}

export interface LayoutPreview {
  screen_id: string
  total_seats: number
  rows: { row_label: string; seats: number; category: string }[]
  by_category: Record<string, number>
}

export interface ShowAdmin {
  id: string
  movie_id: string
  movie_title: string
  screen_id: string
  screen_name: string
  cinema_id: string
  format_code: string
  audio_language: string
  starts_at: string
  ends_at: string
  show_date: string
  status: string
  total_seats: number
  available_seats: number
  booked_seats: number
  occupancy_percent: number
  gross_minor: number
  prices: { seat_category_id: string; category: string; price_minor: number }[]
}

export interface RevenueRow {
  bucket: string
  bookings: number
  tickets: number
  gross_minor: number
  discount_minor: number
  fees_minor: number
  tax_minor: number
  net_minor: number
  refunded_minor: number
}

export interface RevenueReport {
  cinema_id: string | null
  cinema_name: string | null
  date_from: string
  date_to: string
  group_by: string
  totals: RevenueRow
  rows: RevenueRow[]
}

export interface OccupancyRow {
  show_id: string
  movie_title: string
  screen_name: string
  starts_at: string
  total_seats: number
  booked_seats: number
  held_seats: number
  occupancy_percent: number
  gross_minor: number
}

export interface OccupancyReport {
  cinema_id: string
  cinema_name: string
  date_from: string
  date_to: string
  average_occupancy_percent: number
  total_seats: number
  booked_seats: number
  rows: OccupancyRow[]
}

export interface OperatorBooking {
  id: string
  booking_reference: string
  status: string
  created_at: string
  contact_email: string
  seat_count: number
  seat_labels: string[]
  total_minor: number
  movie_title: string
  screen_name: string
  starts_at: string
  checked_in_seats: number
}

export interface UserAdmin {
  id: string
  email: string
  full_name: string
  role: 'customer' | 'cinema_operator' | 'admin'
  is_active: boolean
  created_at: string
  managed_cinemas: number
}
