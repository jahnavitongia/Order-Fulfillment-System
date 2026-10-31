Order Fulfillment AI - Frontend

Files created:
- package.json
- index.html
- src/main.jsx
- src/App.jsx
- src/styles.css
- src/components/OrderForm.jsx
- src/components/Workflow.jsx
- src/components/WorkflowNode.jsx
- src/components/ResultCard.jsx
- src/components/ExecutionTrace.jsx

Run locally:
1) cd frontend
2) npm install
3) npm run dev

Change backend URL:
- Edit `API_URL` at the top of `src/App.jsx` (default: http://localhost:8000/place_order)

Mock/demo mode:
- The frontend attempts to POST to the API. If the request fails or times out, the UI falls back to an internal `mockProcess()` which simulates the Python/LangGraph behavior and returns the expected response shape.

Connect to Python LangGraph backend:
- Implement a POST `/place_order` endpoint that accepts the JSON order and returns the response with fields: `status`, `item`, `requested_qty`, `stock`, `shipping_cost` (if confirmed), `message`, `trace`.
- Run the frontend and backend simultaneously; ensure CORS or proxy is configured (or run backend on localhost:8000 as default).

Notes:
- No external UI libraries used; simple React + Vite.
- The workflow visualization emphasizes node state transitions and an execution trace matching the demo requirements.
