const API = 'http://localhost:8000'

// GET when body is undefined, POST otherwise. Network failure throws TypeError; HTTP errors carry the server's message.
export async function call(path, body) {
  const init = body === undefined ? {} : {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }
  const res = await fetch(API + path, init)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`)
  return data
}

export const NAMES = {
  wireless_mouse: 'Wireless mouse',
  mechanical_keyboard: 'Mechanical keyboard',
  usb_c_hub: 'USB-C hub',
  laptop: 'Laptop',
  monitor: 'Monitor'
}

export const itemName = (sku) => NAMES[sku] || sku || 'Unknown item'

export const money = (n) =>
  n == null ? '—' : '$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export const STATUS = {
  confirmed: { label: 'Confirmed', tone: 'ok' },
  awaiting_approval: { label: 'Waiting for approval', tone: 'wait' },
  declined: { label: 'Declined', tone: 'bad' },
  failed: { label: 'Courier prices unavailable', tone: 'bad' },
  need_info: { label: 'Details missing', tone: 'wait' },
  hop_limit: { label: 'Stopped at hop limit', tone: 'bad' }
}
