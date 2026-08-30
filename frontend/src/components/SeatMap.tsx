import clsx from 'clsx'
import { useMemo } from 'react'
import type { Seat, SeatMap as SeatMapData } from '@/api/types'
import { rupees } from '@/lib/format'

interface Props {
  data: SeatMapData
  selected: Set<string>
  onToggle: (seat: Seat) => void
  disabled?: boolean
}

const STATUS_CLASS: Record<Seat['status'], string> = {
  available: 'border-ink-700 bg-ink-800 hover:border-brand-400 hover:bg-ink-700 cursor-pointer',
  held: 'border-amber-900/70 bg-amber-950/40 text-amber-700/70 cursor-not-allowed',
  booked: 'border-ink-800 bg-ink-900 text-ink-700 cursor-not-allowed',
  blocked: 'border-ink-800 bg-ink-900 text-ink-700 cursor-not-allowed line-through',
}

export function SeatMap({ data, selected, onToggle, disabled }: Props) {
  // Rows are laid out on a shared grid keyed by column_index, not by seat
  // number. That is what makes aisles render as real gaps and keeps every row
  // aligned even when rows have different seat counts.
  const columnCount = useMemo(
    () => Math.max(...data.rows.flatMap((r) => r.seats.map((s) => s.column_index))) + 1,
    [data.rows],
  )

  return (
    <div className="space-y-6">
      <div className="mx-auto max-w-lg">
        <div className="h-2 rounded-t-[100%] bg-gradient-to-b from-ink-500/70 to-transparent" />
        <p className="mt-1 text-center text-[11px] uppercase tracking-[0.3em] text-ink-500">
          {data.layout_meta?.screen_label ?? 'Screen'}
        </p>
      </div>

      <div className="overflow-x-auto pb-2">
        <div className="mx-auto w-fit space-y-4">
          {data.categories.map((category) => {
            const rows = data.rows.filter((r) =>
              r.seats.some((s) => s.category_id === category.category_id),
            )
            if (!rows.length) return null
            return (
              <div key={category.category_id} className="space-y-1.5">
                <div className="flex items-baseline gap-2 pl-8">
                  <span className="text-xs font-semibold text-ink-300">{category.name}</span>
                  <span className="text-xs text-ink-500">
                    {rupees(category.price_minor, { compact: true })}
                  </span>
                  <span className="text-[11px] text-ink-500">
                    · {category.available} of {category.total} free
                  </span>
                </div>

                {rows.map((row) => (
                  <div key={row.row_index} className="flex items-center gap-2">
                    <span className="w-6 shrink-0 text-right text-xs font-medium text-ink-500">
                      {row.row_label}
                    </span>
                    <div
                      className="grid gap-1"
                      style={{ gridTemplateColumns: `repeat(${columnCount}, 1.65rem)` }}
                    >
                      {row.seats.map((seat) => {
                        const isSelected = selected.has(seat.seat_id)
                        const selectable = seat.status === 'available' && !disabled
                        return (
                          <button
                            key={seat.seat_id}
                            type="button"
                            style={{ gridColumnStart: seat.column_index + 1 }}
                            disabled={!selectable}
                            onClick={() => selectable && onToggle(seat)}
                            title={`${seat.label} · ${seat.category_name} · ${rupees(seat.price_minor)}${
                              seat.is_wheelchair_accessible ? ' · wheelchair accessible' : ''
                            }`}
                            aria-label={`Seat ${seat.label}, ${seat.status}`}
                            aria-pressed={isSelected}
                            className={clsx(
                              'flex size-[1.65rem] items-center justify-center rounded border text-[10px] font-medium transition-colors',
                              isSelected
                                ? 'border-brand-500 bg-brand-500 text-white'
                                : STATUS_CLASS[seat.status],
                              disabled && seat.status === 'available' && 'cursor-not-allowed opacity-60',
                            )}
                          >
                            {seat.is_wheelchair_accessible ? '♿' : seat.seat_number}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                ))}
              </div>
            )
          })}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-center gap-4 text-[11px] text-ink-500">
        {[
          ['border-ink-700 bg-ink-800', 'Available'],
          ['border-brand-500 bg-brand-500', 'Selected'],
          ['border-amber-900/70 bg-amber-950/40', 'On hold'],
          ['border-ink-800 bg-ink-900', 'Sold'],
        ].map(([cls, label]) => (
          <span key={label} className="flex items-center gap-1.5">
            <span className={clsx('size-3 rounded border', cls)} />
            {label}
          </span>
        ))}
        <span>Max {data.max_seats_per_booking} seats per booking</span>
      </div>
    </div>
  )
}
