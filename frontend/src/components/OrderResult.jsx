import React from 'react'
import { itemName, money, STATUS } from '../api'
import CourierBids from './CourierBids'

const SAMPLES = [
  { label: '5 wireless mice, 15 km away', note: 'Normal order', order: { item: 'wireless_mouse', qty: 5, weight: 1.2, distance: 15 } },
  { label: '40 wireless mice', note: '$1,000, goes to the approval queue', order: { item: 'wireless_mouse', qty: 40, weight: 3, distance: 30 } },
  { label: '10 keyboards, stale stock cache', note: 'The guard catches a wrong stock answer', order: { item: 'mechanical_keyboard', qty: 10, weight: 8, distance: 40, stale_cache: true } },
  { label: 'One 40 kg monitor, 800 km', note: 'Only one courier can take it', order: { item: 'monitor', qty: 1, weight: 40, distance: 800 } }
]

const AGENT = { supervisor: 'Supervisor', inventory_agent: 'Inventory', guard_agent: 'Guard', shipping_agent: 'Shipping',
  order_agent: 'Order', policy_agent: 'Policy', resume: 'Resume' }

function headline(r) {
  const what = `${r.qty ?? '?'} × ${itemName(r.item)}`
  switch (r.status) {
    case 'confirmed': return `${what} confirmed for ${r.customer}`
    case 'awaiting_approval': return `${what} is waiting for a manager`
    case 'failed': return `${what} is on hold`
    case 'need_info': return 'This order needs more details'
    default: return `${what} could not be fulfilled`
  }
}

function DecisionLog({ trace }) {
  if (!trace?.length) return null
  const steps = trace.filter((l) => !l.startsWith('[supervisor]')).length
  return (
    <details className="decision-log">
      <summary>How this was decided <span className="num">{steps} agent steps</span></summary>
      <ol>
        {trace.map((line, i) => {
          const m = line.match(/^\[(\w+)\]\s*(.*)$/)
          const who = m ? m[1] : ''
          return (
            <li key={i} className={who === 'supervisor' ? 'is-route' : ''}>
              <span className="who">{AGENT[who] || who}</span>
              <span className="what">{m ? m[2] : line}</span>
            </li>
          )
        })}
      </ol>
    </details>
  )
}

export default function OrderResult({ result, busy, onSample, onDecide, onRetry }) {
  if (busy && !result) {
    return (
      <div className="result skeleton" aria-busy="true" aria-label="Processing order">
        <div className="sk sk-tag" /><div className="sk sk-title" /><div className="sk sk-line" />
        <div className="sk-grid">{[0, 1, 2, 3].map((i) => <div key={i} className="sk sk-fact" />)}</div>
        {[0, 1, 2, 3].map((i) => <div key={i} className="sk sk-bar" />)}
      </div>
    )
  }

  if (!result) {
    return (
      <div className="result empty">
        <p className="eyebrow">No order on the desk</p>
        <h2>Place an order, or start from one of these.</h2>
        <ul className="samples">
          {SAMPLES.map((s) => (
            <li key={s.label}>
              <button type="button" onClick={() => onSample(s.order)} disabled={busy}>
                <span className="sample-label">{s.label}</span>
                <span className="sample-note">{s.note}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    )
  }

  const st = STATUS[result.status] || { label: result.status, tone: 'bad' }
  const facts = [
    ['Goods value', money(result.goods_value), true],
    ['Courier', result.courier || '—', false],
    ['Delivery', result.eta ? `${result.eta} working day${result.eta > 1 ? 's' : ''}` : '—', false],
    ['Shipping', money(result.price), true]
  ]

  return (
    <article className={'result' + (busy ? ' is-busy' : '')} aria-busy={busy}>
      <p className={`tag tone-${st.tone}`}><span className="dot" aria-hidden="true" />{st.label}</p>
      <h2>{headline(result)}</h2>
      {result.message && <p className="message">{result.message}</p>}

      {result.status === 'awaiting_approval' && (
        <div className="callout">
          <p>Orders of $500 or more need a manager. Nothing leaves stock until someone decides.</p>
          <div className="actions">
            <button className="btn primary" disabled={busy} onClick={() => onDecide(result.thread_id, 'approved')}>Approve</button>
            <button className="btn quiet" disabled={busy} onClick={() => onDecide(result.thread_id, 'rejected')}>Reject</button>
          </div>
        </div>
      )}
      {result.status === 'failed' && (
        <div className="callout">
          <p>Stock check and verification are saved. Retrying continues from the courier step.</p>
          <div className="actions">
            <button className="btn primary" disabled={busy} onClick={() => onRetry(result.thread_id)}>Retry from saved step</button>
          </div>
        </div>
      )}

      <dl className="facts">
        {facts.map(([k, v, isNum]) => (
          <div key={k}><dt>{k}</dt><dd className={isNum ? 'num' : ''}>{v}</dd></div>
        ))}
      </dl>

      <CourierBids bids={result.bids} weight={result.weight} distance={result.distance} />
      <p className="order-id">Order <span className="num">{result.thread_id}</span></p>
      <DecisionLog trace={result.trace} />
    </article>
  )
}
