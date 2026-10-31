import React from 'react'
import { money } from '../api'

// Single-series bar list: bar length = price. The chosen courier carries an accent bar AND a text label.
export default function CourierBids({ bids, weight, distance }) {
  if (!bids?.length) return null
  const max = Math.max(...bids.map((b) => b.price || 0), 1)
  const bidding = bids.filter((b) => b.price != null).length

  return (
    <section className="bids" aria-labelledby="bids-title">
      <header>
        <h3 id="bids-title">Courier bids</h3>
        <p className="num">{weight} kg · {distance} km · {bidding} of {bids.length} bid</p>
      </header>
      <ul>
        {bids.map((b) => (
          <li key={b.courier} className={b.winner ? 'is-winner' : b.price == null ? 'is-refused' : ''}
            title={b.price != null ? `${b.courier}: ${money(b.price)}, ${b.eta} day(s)` : `${b.courier} refused: ${b.refused}`}>
            <span className="courier">{b.courier}</span>
            <span className="track">
              {b.price != null
                ? <span className="bar" style={{ '--w': `${Math.max((b.price / max) * 100, 2)}%` }} />
                : <span className="refused">Refused · {b.refused}</span>}
            </span>
            <span className="price num">{b.price != null ? money(b.price) : '—'}</span>
            <span className="eta num">{b.price != null ? `${b.eta}d` : ''}</span>
            <span className="verdict">{b.winner ? 'Chosen' : ''}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
