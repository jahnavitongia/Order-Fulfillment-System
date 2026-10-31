import React from 'react'
import { itemName, money } from '../api'

// Meter per item: bar = stock / starting stock. Low and empty rows get a text label, not colour alone.
export default function StockList({ inventory }) {
  return (
    <section className="panel" aria-labelledby="stock-title">
      <header className="panel-head">
        <h3 id="stock-title">Stock</h3>
      </header>
      <ul className="stock">
        {inventory.map((r) => {
          const ratio = r.start ? r.stock / r.start : 0
          const state = r.stock <= 0 ? 'out' : ratio < 0.25 ? 'low' : ''
          return (
            <li key={r.item} className={state && `is-${state}`} title={`${r.stock} of ${r.start} left · ${money(r.price)} each`}>
              <span className="stock-name">{itemName(r.item)}</span>
              <span className="stock-qty num">{r.stock}</span>
              <span className="stock-flag">{state === 'out' ? 'Out' : state === 'low' ? 'Low' : ''}</span>
              <span className="meter" aria-hidden="true"><span style={{ width: `${Math.min(ratio, 1) * 100}%` }} /></span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
