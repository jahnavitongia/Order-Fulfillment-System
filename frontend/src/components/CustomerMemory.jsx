import React, { useEffect, useState } from 'react'
import { itemName } from '../api'

// Long-term memory (per customer, SqliteStore) and short-term memory (this order's thread).
export default function CustomerMemory({ memory, current, busy, onReorder, onChangeQty }) {
  const [qty, setQty] = useState('')
  useEffect(() => setQty(''), [current?.thread_id])
  const last = memory?.last_order
  const canFollowUp = current && current.customer === memory?.customer && current.item

  return (
    <section className="memory" aria-labelledby="memory-title">
      <h3 id="memory-title">Remembered</h3>
      {!memory?.customer && <p className="hint">Type a customer name to see their last order.</p>}
      {memory?.customer && !last && <p className="hint">No past orders for {memory.customer}.</p>}
      {last && (
        <div className="memory-row">
          <p>
            <span className="memory-label">Last order · {memory.customer}</span>
            <span>{last.qty} × {itemName(last.item)} · {last.weight} kg · {last.distance} km</span>
          </p>
          <button className="btn quiet small" disabled={busy} onClick={() => onReorder(memory.customer)}>Reorder</button>
        </div>
      )}
      {canFollowUp && (
        <form className="memory-row follow-up" onSubmit={(e) => { e.preventDefault(); if (Number(qty) > 0) onChangeQty(Number(qty)) }}>
          <label>
            <span className="memory-label">Same order, new quantity</span>
            <span className="hint">Item, weight and distance come from this conversation.</span>
          </label>
          <span className="inline-input">
            <input type="number" min="1" step="1" aria-label="New quantity" value={qty}
              placeholder={String(current.qty ?? '')} onChange={(e) => setQty(e.target.value)} />
            <button className="btn quiet small" type="submit" disabled={busy || !(Number(qty) > 0)}>Update</button>
          </span>
        </form>
      )}
    </section>
  )
}
