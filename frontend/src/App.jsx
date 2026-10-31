import React, { useCallback, useEffect, useState } from 'react'
import { call } from './api'
import OrderForm from './components/OrderForm'
import CustomerMemory from './components/CustomerMemory'
import OrderResult from './components/OrderResult'
import ApprovalQueue from './components/ApprovalQueue'
import StockList from './components/StockList'
import PolicyDesk from './components/PolicyDesk'
import RecentOrders from './components/RecentOrders'

const FIRST_CUSTOMER = 'Priya Raman'

export default function App() {
  const [online, setOnline] = useState(null)            // null = checking
  const [desk, setDesk] = useState({ inventory: [], pending: [], orders: [], threshold: 500 })
  const [current, setCurrent] = useState(null)
  const [customer, setCustomer] = useState(FIRST_CUSTOMER)
  const [memory, setMemory] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    try {
      setDesk(await call('/state'))
      setOnline(true)
    } catch {
      setOnline(false)
    }
  }, [])

  const loadMemory = useCallback(async (name) => {
    if (!name) return setMemory(null)
    try { setMemory(await call('/customer?name=' + encodeURIComponent(name))) } catch { /* shown by the banner */ }
  }, [])

  useEffect(() => { refresh(); loadMemory(FIRST_CUSTOMER) }, [refresh, loadMemory])

  // Every action: one request, show the result, then re-read the desk (stock, queue, recent orders).
  const run = async (path, body, who) => {
    setBusy(true); setError('')
    try {
      const res = await call(path, body)
      setCurrent(res)
      await refresh()
      await loadMemory(who || res.customer)
    } catch (e) {
      if (e instanceof TypeError) setOnline(false)
      setError(e instanceof TypeError ? 'Could not reach the server.' : e.message)
    } finally {
      setBusy(false)
    }
  }

  const place = (order) => run('/order', { customer, ...order }, order.customer || customer)
  const onCustomer = (name) => { setCustomer(name || FIRST_CUSTOMER); loadMemory(name) }

  const reset = async () => {
    setBusy(true); setError('')
    try { setDesk(await call('/reset', {})); setCurrent(null) } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  return (
    <>
      <a className="skip-link" href="#main">Skip to the order desk</a>
      <header className="topbar">
        <div className="brand">
          <span className="mark" aria-hidden="true" />
          <div>
            <h1>Order desk</h1>
            <p>Orders, approvals and courier bids in one place</p>
          </div>
        </div>
        <div className="topbar-right">
          <p className={'conn' + (online ? ' is-on' : online === false ? ' is-off' : '')} role="status">
            <span className="dot" aria-hidden="true" />
            {online ? 'Connected · qwen2.5:3b' : online === false ? 'Server offline' : 'Connecting…'}
          </p>
          <button className="btn quiet small" onClick={reset} disabled={busy || !online}>Restock and clear</button>
        </div>
      </header>

      {online === false && (
        <div className="banner" role="alert">
          <strong>The order server is not running.</strong> Start Ollama, then run <code>python ta2/server.py</code> from the project folder.
          <button className="btn quiet small" onClick={refresh}>Try again</button>
        </div>
      )}
      {error && online !== false && <div className="banner" role="alert">{error}</div>}

      <main id="main" className="desk">
        <aside className="col-order">
          <section className="panel raised" aria-labelledby="new-title">
            <header className="panel-head"><h3 id="new-title">New order</h3></header>
            <OrderForm inventory={desk.inventory} threshold={desk.threshold} busy={busy || !online}
              onSubmit={(o) => run('/order', o, o.customer)} onCustomer={onCustomer} />
          </section>
          <CustomerMemory memory={memory} current={current} busy={busy || !online}
            onReorder={(name) => run('/order', { customer: name, request: 'reorder' }, name)}
            onChangeQty={(qty) => run('/order', { customer: current.customer, thread_id: current.thread_id, qty }, current.customer)} />
        </aside>

        <section className="col-result" aria-label="Current order">
          <OrderResult result={current} busy={busy} onSample={place}
            onDecide={(id, d) => run('/approve', { thread_id: id, decision: d })}
            onRetry={(id) => run('/resume', { thread_id: id })} />
        </section>

        <aside className="col-side">
          <ApprovalQueue pending={desk.pending} threshold={desk.threshold} busy={busy}
            onDecide={(id, d) => run('/approve', { thread_id: id, decision: d })} onOpen={setCurrent} />
          <StockList inventory={desk.inventory} />
        </aside>

        <div className="col-policy"><PolicyDesk /></div>
        <div className="col-recent"><RecentOrders orders={desk.orders} /></div>
      </main>

      <footer className="foot">
        <p>LangGraph supervisor with five agents · SQLite thread and customer memory · Chroma policy search · Ollama, running locally</p>
      </footer>
    </>
  )
}
