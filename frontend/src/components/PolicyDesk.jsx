import React, { useState } from 'react'
import { call } from '../api'

const SUGGESTED = [
  'How long do I have to return an item?',
  'Which courier can carry a 40 kg parcel?',
  'Do I need permission for an expensive order?',
  'Do you offer gift wrapping?'
]

export default function PolicyDesk() {
  const [q, setQ] = useState('')
  const [asked, setAsked] = useState('')
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const ask = async (question) => {
    const text = question.trim()
    if (!text) return setError('Type a question first.')
    setBusy(true); setError(''); setAsked(text); setQ(text)
    try {
      setRes(await call('/ask', { question: text }))
    } catch (e) {
      setRes(null)
      setError(e instanceof TypeError ? 'Could not reach the server.' : e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="policy" aria-labelledby="policy-title">
      <div className="policy-intro">
        <h3 id="policy-title">Shipping policy</h3>
        <p>Answers come only from the policy document, with the clause quoted. If the policy is silent, it says so.</p>
      </div>
      <form className="policy-ask" onSubmit={(e) => { e.preventDefault(); ask(q) }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask about returns, couriers, approvals…"
          aria-label="Policy question" />
        <button className="btn primary" type="submit" disabled={busy}>{busy ? 'Looking up…' : 'Ask'}</button>
      </form>
      <p className="suggested">
        {SUGGESTED.map((s) => (
          <button key={s} type="button" className="link" disabled={busy} onClick={() => ask(s)}>{s}</button>
        ))}
      </p>

      {error && <p className="field-error">{error}</p>}
      {busy && <div className="sk sk-line wide" aria-label="Looking up the policy" />}
      {!busy && res && (
        <div className={'answer' + (res.known ? '' : ' is-unknown')}>
          <p className="answer-q">{asked}</p>
          <p className="answer-text">{res.known ? res.answer : 'Not covered by the policy. The assistant does not guess.'}</p>
          {res.citations.map((c) => (
            <blockquote key={c.id}>
              <span className="clause num">§{c.id}</span>
              {c.text}
            </blockquote>
          ))}
        </div>
      )}
    </section>
  )
}
