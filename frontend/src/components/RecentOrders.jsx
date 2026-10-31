import React from 'react'
import { itemName, money, STATUS } from '../api'

export default function RecentOrders({ orders }) {
  return (
    <section className="panel" aria-labelledby="recent-title">
      <header className="panel-head">
        <h3 id="recent-title">Recent orders</h3>
      </header>
      {orders.length === 0 ? (
        <p className="hint">Finished orders show up here.</p>
      ) : (
        <ul className="recent">
          {orders.slice(0, 8).map((o) => {
            const st = STATUS[o.status] || { label: o.status, tone: 'bad' }
            return (
              <li key={o.thread_id + o.status}>
                <span className={`tag small tone-${st.tone}`}><span className="dot" aria-hidden="true" />{st.label}</span>
                <span className="recent-what">{o.qty} × {itemName(o.item)} <span className="muted">· {o.customer}</span></span>
                <span className="num">{money(o.goods_value)}</span>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
