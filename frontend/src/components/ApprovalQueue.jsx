import React from 'react'
import { itemName, money } from '../api'

export default function ApprovalQueue({ pending, threshold, busy, onDecide, onOpen }) {
  return (
    <section className="panel" aria-labelledby="queue-title">
      <header className="panel-head">
        <h3 id="queue-title">Waiting for approval</h3>
        <span className={'count num' + (pending.length ? ' has-items' : '')}>{pending.length}</span>
      </header>
      {pending.length === 0 ? (
        <p className="hint">Nothing waiting. Orders of {money(threshold)} or more land here.</p>
      ) : (
        <ul className="queue">
          {pending.map((p) => (
            <li key={p.thread_id}>
              <button type="button" className="queue-main" onClick={() => onOpen(p)}>
                <span className="queue-what">{p.qty} × {itemName(p.item)}</span>
                <span className="queue-meta">{p.customer} · {p.courier} {money(p.price)}</span>
              </button>
              <span className="queue-value num">{money(p.goods_value)}</span>
              <span className="queue-actions">
                <button className="btn primary small" disabled={busy} onClick={() => onDecide(p.thread_id, 'approved')}>Approve</button>
                <button className="btn quiet small" disabled={busy} onClick={() => onDecide(p.thread_id, 'rejected')}>Reject</button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
