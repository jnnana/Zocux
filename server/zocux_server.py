"""Zocux Protocol — reference MCP server (v0.1).

Append-only ledger of protocol messages plus a derived view of closed deals.
Schema lives in db/schema.sql. Authorisation rules and idempotency semantics
are documented in PROTOCOL.md and CLAUDE.md.
"""

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone

import asyncpg
import redis.asyncio as aioredis
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

app = Server("zocux-market")

db_pool = None
redis_client = None

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zocux:zocux@localhost/zocux")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


# ─── Connection helpers ───────────────────────────────────────────────────────

async def get_db():
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
    return db_pool


async def get_redis():
    global redis_client
    if redis_client is None:
        redis_client = await aioredis.from_url(REDIS_URL)
    return redis_client


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def text_result(obj: dict) -> list:
    return [TextContent(type="text", text=json.dumps(obj))]


# ─── Append-only ledger with idempotency ──────────────────────────────────────

async def log_message(msg_type: str, payload: dict, agent_id: str,
                      idempotency_key: str | None = None):
    """Insert a message; if (agent_id, type, idempotency_key) already exists,
    return the prior payload and was_dup=True. Never UPDATE."""
    pool = await get_db()
    async with pool.acquire() as conn:
        if idempotency_key is not None:
            existing = await conn.fetchrow(
                "SELECT payload FROM protocol_messages "
                "WHERE agent_id=$1 AND type=$2 AND idempotency_key=$3",
                agent_id, msg_type, idempotency_key,
            )
            if existing:
                return json.loads(existing["payload"]), True
        try:
            await conn.execute(
                "INSERT INTO protocol_messages (type, payload, agent_id, idempotency_key) "
                "VALUES ($1, $2, $3, $4)",
                msg_type, json.dumps(payload), agent_id, idempotency_key,
            )
        except asyncpg.exceptions.UniqueViolationError:
            existing = await conn.fetchrow(
                "SELECT payload FROM protocol_messages "
                "WHERE agent_id=$1 AND type=$2 AND idempotency_key=$3",
                agent_id, msg_type, idempotency_key,
            )
            return json.loads(existing["payload"]), True
        return payload, False


# ─── Loaders / authorisation helpers ──────────────────────────────────────────

async def _load_offer(conn, offer_id: str):
    row = await conn.fetchrow(
        "SELECT payload FROM protocol_messages "
        "WHERE type='ANNOUNCE' AND payload->>'offer_id'=$1",
        offer_id,
    )
    return json.loads(row["payload"]) if row else None


async def _load_proposal(conn, proposal_id: str):
    r = await get_redis()
    cached = await r.get(f"proposal:{proposal_id}")
    if cached:
        return json.loads(cached)
    row = await conn.fetchrow(
        "SELECT payload FROM protocol_messages "
        "WHERE type='PROPOSE' AND payload->>'proposal_id'=$1",
        proposal_id,
    )
    return json.loads(row["payload"]) if row else None


async def _proposal_resolved(conn, proposal_id: str) -> bool:
    row = await conn.fetchrow(
        "SELECT 1 FROM protocol_messages "
        "WHERE type IN ('ACCEPT','REJECT') AND payload->>'proposal_id'=$1 LIMIT 1",
        proposal_id,
    )
    return row is not None


# ─── Tool catalogue ───────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="announce_offer",
            description="Announce availability of a product to the Zocux market",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "product": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit": {"type": "string", "enum": ["kg", "ton", "unit", "liter", "box"]},
                    "price_min": {"type": "number"},
                    "price_currency": {"type": "string", "default": "EUR"},
                    "location": {"type": "string"},
                    "available_from": {"type": "string"},
                    "available_until": {"type": "string"},
                    "certifications": {"type": "array", "items": {"type": "string"}, "default": []},
                    "notes": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["agent_id", "product", "quantity", "unit", "price_min", "location", "available_until"],
            },
        ),
        Tool(
            name="discover_offers",
            description="Search active offers in the Zocux market matching criteria",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "product": {"type": "string"},
                    "quantity_needed": {"type": "number"},
                    "max_price": {"type": "number"},
                    "location": {"type": "string"},
                    "certification_required": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["agent_id", "product"],
            },
        ),
        Tool(
            name="propose_deal",
            description="Submit a deal proposal on an active offer",
            inputSchema={
                "type": "object",
                "properties": {
                    "offer_id": {"type": "string"},
                    "buyer_agent_id": {"type": "string"},
                    "proposed_price": {"type": "number"},
                    "proposed_quantity": {"type": "number"},
                    "proposed_delivery": {"type": "string"},
                    "expires_at": {"type": "string", "description": "ISO8601 deadline for seller response"},
                    "notes": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["offer_id", "buyer_agent_id", "proposed_price", "proposed_quantity",
                             "proposed_delivery", "expires_at"],
            },
        ),
        Tool(
            name="counter_propose",
            description="Counter an existing proposal with new terms (seller or buyer of that proposal)",
            inputSchema={
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "counter_price": {"type": "number"},
                    "counter_quantity": {"type": "number"},
                    "counter_delivery": {"type": "string"},
                    "expires_at": {"type": "string"},
                    "notes": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["proposal_id", "agent_id", "counter_price", "counter_quantity",
                             "counter_delivery", "expires_at"],
            },
        ),
        Tool(
            name="accept_deal",
            description="Accept a proposal. Must be called by the seller of the underlying offer.",
            inputSchema={
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string"},
                    "accepting_agent_id": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["proposal_id", "accepting_agent_id"],
            },
        ),
        Tool(
            name="reject_deal",
            description="Reject a proposal. Must be called by seller or buyer of the proposal.",
            inputSchema={
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string"},
                    "rejecting_agent_id": {"type": "string"},
                    "reason": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["proposal_id", "rejecting_agent_id", "reason"],
            },
        ),
        Tool(
            name="dispute_deal",
            description="Raise a dispute on a closed deal (seller or buyer of the deal).",
            inputSchema={
                "type": "object",
                "properties": {
                    "deal_id": {"type": "string"},
                    "disputing_agent_id": {"type": "string"},
                    "reason": {"type": "string"},
                    "evidence": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["deal_id", "disputing_agent_id", "reason"],
            },
        ),
        Tool(
            name="get_market_stats",
            description="Get aggregated market statistics, optionally filtered by product",
            inputSchema={
                "type": "object",
                "properties": {"product": {"type": "string"}},
            },
        ),
    ]


# ─── Tool dispatcher ──────────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    pool = await get_db()
    idem = arguments.pop("idempotency_key", None)

    if name == "announce_offer":
        offer_id = str(uuid.uuid4())[:12]
        payload = {"offer_id": offer_id, "created_at": now_iso(), **arguments}
        stored, was_dup = await log_message("ANNOUNCE", payload, arguments["agent_id"], idem)
        return text_result({
            "status": "duplicate" if was_dup else "announced",
            "offer_id": stored["offer_id"],
            "message": f"Offer {stored['offer_id']} is live in the Zocux market",
        })

    if name == "discover_offers":
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT payload FROM protocol_messages m
                WHERE type='ANNOUNCE'
                  AND payload->>'product' ILIKE $1
                  AND (payload->>'available_until')::timestamptz > NOW()
                  AND NOT EXISTS (
                        SELECT 1 FROM protocol_messages a
                        WHERE a.type='ACCEPT'
                          AND a.payload->>'offer_id' = m.payload->>'offer_id'
                  )
            """, f"%{arguments['product']}%")
            offers = [json.loads(r["payload"]) for r in rows]
            if arguments.get("max_price") is not None:
                offers = [o for o in offers if float(o.get("price_min", 9e18)) <= arguments["max_price"]]
            if arguments.get("location"):
                loc = arguments["location"].lower()
                offers = [o for o in offers if loc in o.get("location", "").lower()]
            if arguments.get("certification_required"):
                req = arguments["certification_required"].lower()
                offers = [o for o in offers
                          if any(req == c.lower() for c in o.get("certifications", []))]
        await log_message("DISCOVER",
                          {"created_at": now_iso(), **arguments},
                          arguments["agent_id"], idem)
        return text_result({"offers": offers, "count": len(offers),
                            "market": "zocux-protocol-v0.1"})

    if name == "propose_deal":
        async with pool.acquire() as conn:
            offer = await _load_offer(conn, arguments["offer_id"])
        if offer is None:
            return text_result({"error": "Offer not found"})
        proposal_id = str(uuid.uuid4())[:12]
        payload = {"proposal_id": proposal_id, "created_at": now_iso(), **arguments}
        stored, was_dup = await log_message("PROPOSE", payload,
                                            arguments["buyer_agent_id"], idem)
        r = await get_redis()
        await r.setex(f"proposal:{stored['proposal_id']}", 86400, json.dumps(stored))
        return text_result({
            "status": "duplicate" if was_dup else "proposed",
            "proposal_id": stored["proposal_id"],
            "message": "Proposal submitted. Waiting for seller response.",
        })

    if name == "counter_propose":
        async with pool.acquire() as conn:
            original = await _load_proposal(conn, arguments["proposal_id"])
            if original is None:
                return text_result({"error": "Proposal not found"})
            if await _proposal_resolved(conn, arguments["proposal_id"]):
                return text_result({"error": "Proposal already accepted or rejected"})
            offer = await _load_offer(conn, original["offer_id"])
        seller_id = (offer or {}).get("agent_id")
        buyer_id = original.get("buyer_agent_id")
        if arguments["agent_id"] not in (seller_id, buyer_id):
            return text_result({"error": "Counter must come from seller or buyer of the proposal"})
        counter_id = str(uuid.uuid4())[:12]
        payload = {"counter_id": counter_id, "created_at": now_iso(), **arguments}
        stored, was_dup = await log_message("COUNTER", payload, arguments["agent_id"], idem)
        return text_result({
            "status": "duplicate" if was_dup else "countered",
            "counter_id": stored["counter_id"],
        })

    if name == "accept_deal":
        async with pool.acquire() as conn:
            proposal = await _load_proposal(conn, arguments["proposal_id"])
            if proposal is None:
                return text_result({"error": "Proposal not found"})
            if await _proposal_resolved(conn, arguments["proposal_id"]):
                return text_result({"error": "Proposal already resolved"})
            offer = await _load_offer(conn, proposal["offer_id"])
            if offer is None:
                return text_result({"error": "Underlying offer not found"})
            if arguments["accepting_agent_id"] != offer.get("agent_id"):
                return text_result({"error": "Only the seller of the offer can accept"})

            deal_id = str(uuid.uuid4())[:12]
            accept_payload = {
                "deal_id": deal_id,
                "proposal_id": arguments["proposal_id"],
                "accepting_agent_id": arguments["accepting_agent_id"],
                "offer_id": proposal["offer_id"],
                "final_price": proposal["proposed_price"],
                "final_quantity": proposal["proposed_quantity"],
                "final_delivery": proposal["proposed_delivery"],
                "accepted_at": now_iso(),
            }
            stored, was_dup = await log_message("ACCEPT", accept_payload,
                                                arguments["accepting_agent_id"], idem)
            if not was_dup:
                await conn.execute("""
                    INSERT INTO closed_deals
                    (deal_id, offer_id, proposal_id, seller_agent_id, buyer_agent_id,
                     final_price, final_quantity, currency, product, accepted_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                    ON CONFLICT (deal_id) DO NOTHING
                """,
                    stored["deal_id"], proposal["offer_id"], arguments["proposal_id"],
                    offer["agent_id"], proposal["buyer_agent_id"],
                    proposal["proposed_price"], proposal["proposed_quantity"],
                    offer.get("price_currency", "EUR"), offer["product"],
                    datetime.now(timezone.utc),
                )
        r = await get_redis()
        await r.delete(f"proposal:{arguments['proposal_id']}")
        return text_result({
            "status": "duplicate" if was_dup else "deal_closed",
            "deal_id": stored["deal_id"],
            "agreement": stored,
            "message": "Deal recorded. Agreement is binding.",
        })

    if name == "reject_deal":
        async with pool.acquire() as conn:
            proposal = await _load_proposal(conn, arguments["proposal_id"])
            if proposal is None:
                return text_result({"error": "Proposal not found"})
            if await _proposal_resolved(conn, arguments["proposal_id"]):
                return text_result({"error": "Proposal already resolved"})
            offer = await _load_offer(conn, proposal["offer_id"])
        seller_id = (offer or {}).get("agent_id")
        buyer_id = proposal.get("buyer_agent_id")
        if arguments["rejecting_agent_id"] not in (seller_id, buyer_id):
            return text_result({"error": "Only seller or buyer of the proposal can reject"})
        payload = {"rejected_at": now_iso(), **arguments}
        stored, was_dup = await log_message("REJECT", payload,
                                            arguments["rejecting_agent_id"], idem)
        r = await get_redis()
        await r.delete(f"proposal:{arguments['proposal_id']}")
        return text_result({
            "status": "duplicate" if was_dup else "rejected",
            "reason": arguments.get("reason"),
        })

    if name == "dispute_deal":
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT seller_agent_id, buyer_agent_id FROM closed_deals WHERE deal_id=$1",
                arguments["deal_id"],
            )
        if row is None:
            return text_result({"error": "Deal not found"})
        if arguments["disputing_agent_id"] not in (row["seller_agent_id"], row["buyer_agent_id"]):
            return text_result({"error": "Only seller or buyer of the deal can dispute"})
        payload = {"created_at": now_iso(), **arguments}
        stored, was_dup = await log_message("DISPUTE", payload,
                                            arguments["disputing_agent_id"], idem)
        return text_result({"status": "duplicate" if was_dup else "disputed"})

    if name == "get_market_stats":
        async with pool.acquire() as conn:
            if arguments.get("product"):
                pf = f"%{arguments['product']}%"
                total_deals = await conn.fetchval(
                    "SELECT COUNT(*) FROM closed_deals WHERE product ILIKE $1", pf)
                total_volume = await conn.fetchval(
                    "SELECT COALESCE(SUM(final_price * final_quantity), 0) "
                    "FROM closed_deals WHERE product ILIKE $1", pf)
                active_offers = await conn.fetchval(
                    "SELECT COUNT(*) FROM active_offers WHERE product ILIKE $1", pf)
            else:
                total_deals = await conn.fetchval("SELECT COUNT(*) FROM closed_deals")
                total_volume = await conn.fetchval(
                    "SELECT COALESCE(SUM(final_price * final_quantity), 0) FROM closed_deals")
                active_offers = await conn.fetchval("SELECT COUNT(*) FROM active_offers")
        return text_result({
            "market": "zocux-protocol-v0.1",
            "stats": {
                "deals_closed": int(total_deals),
                "total_volume_eur": float(total_volume),
                "active_offers": int(active_offers),
            },
        })

    return text_result({"error": f"Unknown tool: {name}"})


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
