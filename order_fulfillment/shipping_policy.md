# Shipping Policy

This document is the knowledge base for the policy lookup (RAG) step. Every clause has an id such as 1.1.

## 1. Couriers and eligibility

**1.1 BudgetPost.** BudgetPost carries parcels up to 30 kg over distances up to 500 km. Delivery takes 5 business days. It is usually the cheapest courier for light parcels.

**1.2 SpeedyExpress.** SpeedyExpress carries parcels up to 50 kg over distances up to 2000 km. Delivery is next day (1 business day). It is the only courier that can carry parcels heavier than 30 kg or travel further than 500 km.

**1.3 EcoShip.** EcoShip carries parcels up to 15 kg over distances up to 300 km. Delivery takes 4 business days. EcoShip uses low-emission vehicles.

**1.4 LocalBike.** LocalBike carries parcels up to 5 kg over distances up to 20 km. Delivery is within 1 business day. It is intended for small local deliveries only.

## 2. Courier selection

**2.1 Bidding.** For every order that passes the inventory check, all couriers are invited to bid. Each courier either submits a price and delivery time or refuses because the parcel is outside its weight or distance limits. The cheapest eligible bid wins. If two bids have the same price, the faster delivery wins, then the courier name in alphabetical order.

**2.2 No eligible courier.** If every courier refuses, for example because the parcel is heavier than 50 kg, the order is declined and no stock is deducted.

## 3. High-value orders

**3.1 Approval threshold.** An order whose goods value is 500.00 USD or more needs human approval before it can be confirmed. Goods value is quantity times unit price; the shipping cost is not included.

**3.2 Approval outcome.** The approver can approve or reject. A rejection declines the order. While an order waits for a decision it is held and no stock is deducted.

## 4. Stock and confirmation

**4.1 When stock is deducted.** Stock is deducted only when the order is confirmed, in one atomic database step that refuses to take stock below zero.

**4.2 Stock changed.** If the stock is no longer sufficient at confirmation time, for example because another order was confirmed first, the order is declined.

## 5. Delivery

**5.1 Business days.** Delivery times count business days (Monday to Friday) starting from the day the order is confirmed.

**5.2 Tracking.** A tracking reference is created when the courier is booked, which happens at confirmation.

## 6. Returns and damage

**6.1 Returns.** Unopened items can be returned within 14 days of delivery for a full refund of the goods value.

**6.2 Damaged or lost parcels.** Damage or loss must be reported within 7 days of the expected delivery date. The courier handles the claim.
