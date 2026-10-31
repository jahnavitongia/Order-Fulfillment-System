import React, { useState } from 'react'
import { itemName, money } from '../api'

export default function OrderForm({ inventory, threshold, busy, onSubmit, onCustomer }) {
  const [customer, setCustomer] = useState('Priya Raman')
  const [item, setItem] = useState('wireless_mouse')
  const [qty, setQty] = useState(5)
  const [weight, setWeight] = useState(1.2)
  const [distance, setDistance] = useState(15)
  const [staleCache, setStaleCache] = useState(false)
  const [quoteFailures, setQuoteFailures] = useState(0)
  const [touched, setTouched] = useState(false)

  const row = inventory.find((r) => r.item === item)
  const value = row && qty > 0 ? qty * row.price : 0
  const errors = {
    customer: !customer.trim() && 'Enter a customer name.',
    qty: !(Number.isInteger(Number(qty)) && Number(qty) > 0) && 'Quantity must be a whole number, 1 or more.',
    weight: !(Number(weight) > 0) && 'Weight must be above 0.',
    distance: !(Number(distance) > 0) && 'Distance must be above 0.'
  }
  const invalid = Object.values(errors).some(Boolean)

  const submit = (e) => {
    e.preventDefault()
    setTouched(true)
    if (invalid) return
    onSubmit({ customer: customer.trim(), item, qty: Number(qty), weight: Number(weight), distance: Number(distance),
      stale_cache: staleCache, quote_failures: quoteFailures })
  }

  const err = (k) => touched && errors[k] && <span className="field-error">{errors[k]}</span>

  return (
    <form className="order-form" onSubmit={submit} noValidate>
      <label className="field">
        <span>Customer</span>
        <input value={customer} onChange={(e) => setCustomer(e.target.value)}
          onBlur={() => onCustomer(customer.trim())} autoComplete="off" />
        {err('customer')}
      </label>

      <label className="field">
        <span>Item</span>
        <select value={item} onChange={(e) => setItem(e.target.value)}>
          {inventory.map((r) => (
            <option key={r.item} value={r.item}>
              {itemName(r.item)} · {money(r.price)} · {r.stock} left
            </option>
          ))}
        </select>
      </label>

      <div className="field-row">
        <label className="field">
          <span>Quantity</span>
          <input type="number" min="1" step="1" inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value)} />
        </label>
        <label className="field">
          <span>Parcel kg</span>
          <input type="number" min="0.1" step="0.1" inputMode="decimal" value={weight} onChange={(e) => setWeight(e.target.value)} />
        </label>
        <label className="field">
          <span>Distance km</span>
          <input type="number" min="1" step="1" inputMode="numeric" value={distance} onChange={(e) => setDistance(e.target.value)} />
        </label>
      </div>
      {err('qty') || err('weight') || err('distance')}

      <p className={'value-line' + (value >= threshold ? ' needs-approval' : '')}>
        Goods value <strong className="num">{money(value)}</strong>
        <span>{value >= threshold ? `needs a manager (≥ ${money(threshold)})` : 'approved automatically'}</span>
      </p>

      <details className="test-controls">
        <summary>Test a failure</summary>
        <label className="check">
          <input type="checkbox" checked={staleCache} onChange={(e) => setStaleCache(e.target.checked)} />
          Inventory agent reads a stale cache (+100 units)
        </label>
        <label className="check">
          Courier price service times out
          <select value={quoteFailures} onChange={(e) => setQuoteFailures(Number(e.target.value))}>
            <option value={0}>never</option>
            <option value={1}>once (retried)</option>
            <option value={2}>twice (order paused)</option>
          </select>
        </label>
      </details>

      <button className="btn primary block" type="submit" disabled={busy}>
        {busy ? 'Working…' : 'Place order'}
      </button>
    </form>
  )
}
