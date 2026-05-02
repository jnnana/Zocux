# Troca Protocol — v0.1

> Formal message specification for implementers.
> The reference server lives in [`server/`](./server). Architecture and rationale live in [`CLAUDE.md`](./CLAUDE.md).

This document is **stable within a major version**. Any breaking change ships under a new version (`v0.2`, etc.) and the prior version remains supported for at least one minor release.

---

## Wire format

All messages are JSON objects exchanged over the [Model Context Protocol (MCP)](https://modelcontextprotocol.io). Each message has a `type` discriminator. Unknown fields MUST be ignored by receivers (forward compatibility).

Timestamps are **ISO 8601 with timezone** (e.g. `2026-05-02T19:10:34Z`).
Identifiers (`offer_id`, `proposal_id`, `counter_id`, `deal_id`) are server-generated 12-character strings derived from a UUIDv4. Clients never invent them.

## Idempotency

Every **mutating** call (`ANNOUNCE`, `PROPOSE`, `COUNTER`, `ACCEPT`, `REJECT`, `DISPUTE`) accepts an optional client-supplied `idempotency_key: string` (≤100 chars). The server guarantees that two calls with the same `(agent_id, type, idempotency_key)` produce the same effect: the second returns the result of the first without creating a duplicate.

Clients SHOULD set this key when retrying after a network failure. Without it, retries may create duplicate records.

## Authorization model

| Message  | Who may send it                                                  |
|----------|------------------------------------------------------------------|
| ANNOUNCE | Any agent (the agent becomes the seller of the new offer)        |
| DISCOVER | Any agent                                                        |
| PROPOSE  | Any agent that is not the seller of the offer                    |
| COUNTER  | Seller or buyer of the proposal being countered                  |
| ACCEPT   | **Only** the seller of the offer underlying the proposal         |
| REJECT   | Seller or buyer of the proposal                                  |
| DISPUTE  | Seller or buyer of the closed deal                               |

In `v0.1` over MCP stdio, the server trusts the `agent_id` declared by the client. See `CLAUDE.md` § "Seguridad y autenticación" for the requirements before exposing a public REST API.

---

## Messages

### ANNOUNCE — a seller publishes availability

```json
{
  "type": "ANNOUNCE",
  "offer_id": "uuid",
  "agent_id": "string",
  "product": "string",
  "quantity": "float",
  "unit": "string (kg|ton|unit|liter|box)",
  "price_min": "float",
  "price_currency": "string (EUR|USD)",
  "location": "string",
  "available_from": "ISO8601",
  "available_until": "ISO8601",
  "certifications": ["string"],
  "notes": "string|null",
  "created_at": "ISO8601"
}
```

### DISCOVER — a buyer searches for offers

```json
{
  "type": "DISCOVER",
  "agent_id": "string",
  "product": "string",
  "quantity_needed": "float",
  "unit": "string",
  "max_price": "float|null",
  "location_radius_km": "int|null",
  "location_center": "string|null",
  "needed_by": "ISO8601|null",
  "certifications_required": ["string"]
}
```

> Note: `location_radius_km` and `location_center` are reserved for `v0.2`. The `v0.1` server matches `location` as case-insensitive substring only.

### PROPOSE — a buyer proposes terms on an offer

```json
{
  "type": "PROPOSE",
  "proposal_id": "uuid",
  "offer_id": "string",
  "buyer_agent_id": "string",
  "proposed_price": "float",
  "proposed_quantity": "float",
  "proposed_delivery": "ISO8601",
  "expires_at": "ISO8601",
  "notes": "string|null"
}
```

### COUNTER — either party amends an open proposal

```json
{
  "type": "COUNTER",
  "counter_id": "uuid",
  "proposal_id": "string",
  "agent_id": "string",
  "counter_price": "float",
  "counter_quantity": "float",
  "counter_delivery": "ISO8601",
  "expires_at": "ISO8601",
  "notes": "string|null"
}
```

### ACCEPT — the seller closes the deal

Irreversible except via subsequent `DISPUTE`.

```json
{
  "type": "ACCEPT",
  "deal_id": "uuid",
  "proposal_id": "string",
  "accepting_agent_id": "string",
  "offer_id": "string",
  "final_price": "float",
  "final_quantity": "float",
  "final_delivery": "ISO8601",
  "accepted_at": "ISO8601"
}
```

### REJECT — proposal cancelled by either party

```json
{
  "type": "REJECT",
  "proposal_id": "string",
  "rejecting_agent_id": "string",
  "reason": "string",
  "rejected_at": "ISO8601"
}
```

### DISPUTE — non-fulfilment of a closed deal

Filing a dispute does not reverse the agreement; it flags it for off-protocol resolution and affects reputation.

```json
{
  "type": "DISPUTE",
  "deal_id": "string",
  "disputing_agent_id": "string",
  "reason": "string",
  "evidence": "string|null",
  "created_at": "ISO8601"
}
```

---

## State machine of an offer

```
ANNOUNCE ──► (active)
              │
              ├─► PROPOSE ──► (open proposal)
              │                 │
              │                 ├─► COUNTER ──► (open proposal, new terms)
              │                 ├─► ACCEPT  ──► (deal closed) ──► DISPUTE? (off-protocol)
              │                 └─► REJECT  ──► (proposal closed; offer remains active)
              │
              └─► (expires_at reached without ACCEPT) ──► (expired, no deal)
```

In `v0.1`, a single `ACCEPT` closes the **entire offer**, regardless of whether `proposed_quantity < quantity`. Partial fulfilment is `v0.2`.

---

## Versioning policy

- Patch (`v0.1.x`) — clarifications, typo fixes; no schema change.
- Minor (`v0.x`) — additive fields with sensible defaults; existing clients keep working.
- Major (`vX.0`) — breaking changes; both versions supported for ≥1 minor release.

A new field is **always** optional in the minor that introduces it. It only becomes required in a subsequent major.
