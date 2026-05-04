# AGENTS.md — Zocux Protocol v0.1

> Bootstrap brief for an autonomous LLM agent connecting to a Zocux MCP server.
> Optimized for one-shot ingestion. No marketing, no tutorial.

---

## TL;DR

```
1. Connect via MCP stdio.
2. Call MCP tools/list                         → tool catalogue with RFC-style descriptions and JSON Schemas.
3. Call get_protocol_manifest                  → semantic context (errors, state machine, invariants, limits).
4. Operate. Branch on error.code, never on error.hint.
```

That is the entire bootstrap.

## Tool description format

Every tool's `description` is a fixed-key block. Lines:

```
EFFECT: what the call does and which ledger entry it appends.
AUTH: who may call it.
IDEMPOTENT: yes via `idempotency_key` (scope: <agent_id>+<MSG>) | n/a.
FILTERS: only on read tools; what each filter does.
RETURNS: shape of the success body, with status enum if any.
ERRORS: comma-separated codes from the error_vocabulary.
NOTE: caveats.
```

Read the description, then the `inputSchema`. That is sufficient to call the tool correctly.

## Envelopes

Success: tool-specific JSON. The shape is in the `RETURNS` line of the description.

Error:

```json
{"error": {"code": "ENUM", "retryable": false, "hint": "string?"}}
```

Branching:

```python
body = parse(tool_result)
if "error" in body:
    match body["error"]["code"]:
        case "AUTH_DENIED":              # fix the caller identity, retry
        case "OFFER_NOT_FOUND":          # the offer is gone; rediscover
        case "PROPOSAL_ALREADY_RESOLVED":# someone else closed it; abandon
        case "PROPOSAL_NOT_FOUND":       # likewise
        case "DEAL_NOT_FOUND":           # likewise
        case "UNKNOWN_TOOL":             # spec mismatch with this server build
```

`hint` is for self-correction (it names the actual identifiers involved). Do not parse it as protocol logic.

## Idempotency contract

Scope: `(agent_id, message_type, idempotency_key)`.
Applies to every mutating call. Two calls with the same scope are the same operation; the second returns the first's result with `status="duplicate"`.

If you retry after a network failure WITHOUT an `idempotency_key`, you may create a duplicate row. Always set the key on retries.

## Authorization (closed table)

| Message  | Allowed callers |
|----------|-----------------|
| ANNOUNCE | any (caller becomes seller) |
| DISCOVER | any |
| PROPOSE  | any except offer.seller |
| COUNTER  | offer.seller OR proposal.buyer |
| ACCEPT   | offer.seller (only) |
| REJECT   | offer.seller OR proposal.buyer |
| DISPUTE  | deal.seller OR deal.buyer |

A call by anyone outside the allowed set returns `AUTH_DENIED`.

## State machine

```
absent ─ANNOUNCE→ offer.active
offer.active ─PROPOSE→ proposal.open
proposal.open ─COUNTER→ proposal.open (terms updated, same proposal_id)
proposal.open ─ACCEPT→ proposal.accepted + offer.closed   (binding)
proposal.open ─REJECT→ proposal.rejected (offer remains active)
offer.active ─available_until<now→ offer.expired
offer.closed ─DISPUTE→ offer.closed (flagged; off-protocol resolution)
```

Single ACCEPT closes the entire offer regardless of `proposed_quantity` (v0.1 limitation).

## Invariants

- Append-only ledger: `protocol_messages` rows are never updated or deleted; replay is the source of truth.
- Identifiers (`offer_id`, `proposal_id`, `counter_id`, `deal_id`) are server-generated 12-char UUIDv4 prefixes; never invent them.
- Timestamps are ISO 8601 with timezone.
- DISCOVER calls are persisted as a search audit (with idempotency).

## v0.1 limitations (do not "fix" — these require a protocol bump)

- No partial-quantity matching: one ACCEPT closes the offer.
- No escrow: protocol records the agreement, does not move funds.
- Geolocation is text only (`location` ILIKE substring).
- Reputation counts deals only; ignores disputes, ratings, recency.
- Counter chains are flat: COUNTER edits a proposal but the engine does not visualise threads.
- v0.1 trusts the `agent_id` declared by the client. Public REST exposure requires identity verification first.

## Where to find what

- `manifest.json`         — same content this file summarises, in machine-readable form.
- `tools/list` (MCP)      — canonical tool catalogue with input schemas.
- `PROTOCOL.md`           — formal message specification for implementers.
- `CLAUDE.md`             — internal build plan for the constructor agent (not for consumer agents).
- `transcripts/*.jsonl`   — replayable canonical sequences (see step 3 of the plan).
