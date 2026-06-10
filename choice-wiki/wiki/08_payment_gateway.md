# Payment Gateway & IC++ Explained

**Notion:** https://app.notion.com/p/1d617886534380cbbb81f53eb5548d37

## Overview
Choice uses **Adyen** as the payment gateway for all online payments (QR, delivery, takeaway). The pricing model is **IC++ (Interchange++)** — the standard transparent model used across the market, including on regular payment terminals.

---

## IC++ Model Explained

IC++ separates the fee into three components:

| Component | Goes to | Typical amount |
|-----------|---------|----------------|
| **Interchange** | Issuing bank (e.g. bank of the cardholder) | 0.2% debit / 0.3% credit (EU regulated) |
| **Scheme fee** | Card association (Visa / Mastercard) | ~0.05–0.15% |
| **Acquirer fee** | Choice (payment processor) | 0.99% or 1.3% + fixed fee |

This is the same model used on standard POS terminals. Restaurants already familiar with IC++ on their terminals will recognize it immediately.

---

## Choice Payment Fees

| Transaction type | Fee |
|-----------------|-----|
| QR payments / QR orders | **0.99% + 2.50 CZK** (CZ) / **0.99% + €0.10** (EUR) |
| Delivery & Takeaway | **1.3% + 2.50 CZK** (CZ) / **1.3% + €0.10** (EUR) |

**Why is QR lower than delivery?**
QR payments are in-house transactions — simpler process, fewer steps, lower risk of chargebacks. Delivery involves more steps (order, preparation, courier handoff, delivery), possible integrations (Wolt Drive split), and higher chargeback risk.

**Why is there a fixed fee?**
The fixed fee goes to Adyen (not to Choice) and is what allows the % rate to be so low (0.99%). It covers processing costs and transaction security.

---

## Old vs New Model Comparison

| Model | Fee |
|-------|-----|
| Old model | 1.5% + 1.5 CZK (all-in) |
| New IC++ model — QR | 0.99% + 2.50 CZK + IC++ |
| New IC++ model — Delivery | 1.3% + 2.50 CZK + IC++ |

**For comparison: Qerko charges 1.35% + 2.90 CZK + MIF++**

### Example calculation (1,000 CZK order)
| Model | Total fee |
|-------|-----------|
| Old (1.5% + 1.5 CZK) | **16.50 CZK** |
| New QR (0.99% + 2.50 CZK + IC++ ~3–4 CZK) | **~15–16 CZK** |

Result: similar or often **less than before** at higher order values.

---

## IC++ Breakdown by Card Type

| Card type | Typical IC + Scheme range |
|-----------|--------------------------|
| Standard domestic debit | ~0.25–0.35% |
| Standard EU credit | ~0.35–0.45% |
| Corporate / premium / foreign | ~0.7–2% |

Premium/corporate/foreign cards are not EU-regulated — they can be 1–2%.

---

## Service Fee (optional)

The restaurant can choose to pass the fixed fee to the end customer:

| Option | Rate |
|--------|------|
| Fixed fee (paid by restaurant) | 2.50 CZK / €0.10 per transaction |
| Service fee (paid by customer) | 1–1.5%, min 2.50 CZK / €0.10, max 26 CZK / €1.00 |

**Important:** Never combine fixed fee and service fee simultaneously. The restaurant chooses one or the other.

Customers are used to service fees — Wolt charges over 5%. Framing: *"We have a 1.5% service fee, minimum 2.50 CZK and maximum 26 CZK — customers are used to it."*

---

## How to Explain to Clients

Simple version:
> "Our QR commission is 0.99% + 2.50 CZK in the IC++ scheme — you're certainly familiar with this model from your own terminal."

If they ask about the fixed fee:
> "I understand it may seem like a lot, but that's exactly what keeps our % so low. Either way, we can eliminate that fixed fee — we have a new service fee where the customer pays it (1.5%, min 2.50 CZK, max 26 CZK). People are used to it and it saves you the fixed fee."

---

## Payout
- Funds paid to restaurant's bank account within **48 hours**
- Payment processor: **Adyen**
- Supported methods: bank cards, **Apple Pay**, **Google Pay**, cash (Smart/Pro)
