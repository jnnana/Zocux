"""Basic e2e tests for the eight v0.1 MCP tools."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from server import zocux_server as z


def _parse(result):
    return json.loads(result[0].text)


def _in_future(hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


async def _seed_offer(seller: str = "seller-1", **overrides) -> str:
    args = {
        "agent_id": seller,
        "product": "Tomatoes",
        "quantity": 100.0,
        "unit": "kg",
        "price_min": 1.5,
        "location": "Almería",
        "available_until": _in_future(24),
        **overrides,
    }
    return _parse(await z.call_tool("announce_offer", args))["offer_id"]


async def _seed_proposal(offer_id: str, buyer: str = "buyer-1",
                         price: float = 1.4, quantity: float = 50) -> str:
    body = _parse(await z.call_tool("propose_deal", {
        "offer_id": offer_id,
        "buyer_agent_id": buyer,
        "proposed_price": price,
        "proposed_quantity": quantity,
        "proposed_delivery": _in_future(72),
        "expires_at": _in_future(24),
    }))
    return body["proposal_id"]


# ─── announce_offer ───────────────────────────────────────────────────────────

async def test_announce_returns_offer_id():
    body = _parse(await z.call_tool("announce_offer", {
        "agent_id": "seller-1",
        "product": "Tomatoes",
        "quantity": 100.0,
        "unit": "kg",
        "price_min": 1.5,
        "location": "Almería",
        "available_until": _in_future(24),
    }))
    assert body["status"] == "announced"
    assert body["offer_id"]


async def test_announce_idempotent():
    args = {
        "agent_id": "seller-1",
        "product": "Tomatoes",
        "quantity": 100.0,
        "unit": "kg",
        "price_min": 1.5,
        "location": "Almería",
        "available_until": _in_future(24),
        "idempotency_key": "abc-123",
    }
    first = _parse(await z.call_tool("announce_offer", dict(args)))
    second = _parse(await z.call_tool("announce_offer", dict(args)))
    assert first["offer_id"] == second["offer_id"]
    assert second["status"] == "duplicate"


# ─── discover_offers ──────────────────────────────────────────────────────────

async def test_discover_finds_active_offer():
    await _seed_offer(product="Olive Oil", unit="liter", price_min=8.0,
                      location="Jaén")
    body = _parse(await z.call_tool("discover_offers", {
        "agent_id": "buyer-1",
        "product": "olive",
    }))
    assert body["count"] == 1
    assert body["offers"][0]["product"] == "Olive Oil"


async def test_discover_filters_by_max_price():
    await _seed_offer(product="Wheat", unit="ton", price_min=200, location="Castilla")
    await _seed_offer(product="Wheat", unit="ton", price_min=500, location="Castilla")
    body = _parse(await z.call_tool("discover_offers", {
        "agent_id": "buyer-1",
        "product": "wheat",
        "max_price": 300,
    }))
    assert body["count"] == 1
    assert body["offers"][0]["price_min"] == 200


# ─── propose_deal ─────────────────────────────────────────────────────────────

async def test_propose_unknown_offer_errors():
    body = _parse(await z.call_tool("propose_deal", {
        "offer_id": "does-not-exist",
        "buyer_agent_id": "buyer-1",
        "proposed_price": 1.0,
        "proposed_quantity": 10,
        "proposed_delivery": _in_future(72),
        "expires_at": _in_future(24),
    }))
    assert body.get("error") == "Offer not found"


async def test_propose_creates_proposal():
    offer_id = await _seed_offer()
    body = _parse(await z.call_tool("propose_deal", {
        "offer_id": offer_id,
        "buyer_agent_id": "buyer-1",
        "proposed_price": 1.4,
        "proposed_quantity": 50,
        "proposed_delivery": _in_future(72),
        "expires_at": _in_future(24),
    }))
    assert body["status"] == "proposed"
    assert body["proposal_id"]


# ─── accept_deal ──────────────────────────────────────────────────────────────

async def test_accept_only_by_seller():
    offer_id = await _seed_offer(seller="seller-1")
    proposal_id = await _seed_proposal(offer_id, buyer="buyer-1")
    body = _parse(await z.call_tool("accept_deal", {
        "proposal_id": proposal_id,
        "accepting_agent_id": "buyer-1",
    }))
    assert "error" in body


async def test_accept_happy_path_closes_deal_and_offer():
    offer_id = await _seed_offer(seller="seller-1")
    proposal_id = await _seed_proposal(offer_id, buyer="buyer-1", price=1.4, quantity=50)
    body = _parse(await z.call_tool("accept_deal", {
        "proposal_id": proposal_id,
        "accepting_agent_id": "seller-1",
    }))
    assert body["status"] == "deal_closed"
    assert body["agreement"]["final_price"] == 1.4
    assert body["agreement"]["final_quantity"] == 50

    # Offer is no longer active after the accept.
    discover = _parse(await z.call_tool("discover_offers", {
        "agent_id": "buyer-2",
        "product": "tomato",
    }))
    assert discover["count"] == 0


async def test_accept_twice_blocked():
    offer_id = await _seed_offer(seller="seller-1")
    proposal_id = await _seed_proposal(offer_id, buyer="buyer-1")
    await z.call_tool("accept_deal", {
        "proposal_id": proposal_id,
        "accepting_agent_id": "seller-1",
    })
    body = _parse(await z.call_tool("accept_deal", {
        "proposal_id": proposal_id,
        "accepting_agent_id": "seller-1",
    }))
    assert "error" in body


# ─── reject_deal ──────────────────────────────────────────────────────────────

async def test_reject_by_buyer_ok():
    offer_id = await _seed_offer(seller="seller-1")
    proposal_id = await _seed_proposal(offer_id, buyer="buyer-1")
    body = _parse(await z.call_tool("reject_deal", {
        "proposal_id": proposal_id,
        "rejecting_agent_id": "buyer-1",
        "reason": "changed mind",
    }))
    assert body["status"] == "rejected"


async def test_reject_by_outsider_blocked():
    offer_id = await _seed_offer(seller="seller-1")
    proposal_id = await _seed_proposal(offer_id, buyer="buyer-1")
    body = _parse(await z.call_tool("reject_deal", {
        "proposal_id": proposal_id,
        "rejecting_agent_id": "stranger",
        "reason": "no",
    }))
    assert "error" in body


# ─── counter_propose ──────────────────────────────────────────────────────────

async def test_counter_by_seller_ok():
    offer_id = await _seed_offer(seller="seller-1")
    proposal_id = await _seed_proposal(offer_id, buyer="buyer-1", price=1.4)
    body = _parse(await z.call_tool("counter_propose", {
        "proposal_id": proposal_id,
        "agent_id": "seller-1",
        "counter_price": 1.6,
        "counter_quantity": 50,
        "counter_delivery": _in_future(72),
        "expires_at": _in_future(24),
    }))
    assert body["status"] == "countered"


async def test_counter_by_outsider_blocked():
    offer_id = await _seed_offer(seller="seller-1")
    proposal_id = await _seed_proposal(offer_id, buyer="buyer-1")
    body = _parse(await z.call_tool("counter_propose", {
        "proposal_id": proposal_id,
        "agent_id": "stranger",
        "counter_price": 2.0,
        "counter_quantity": 50,
        "counter_delivery": _in_future(72),
        "expires_at": _in_future(24),
    }))
    assert "error" in body


# ─── dispute_deal ─────────────────────────────────────────────────────────────

async def test_dispute_by_party_ok():
    offer_id = await _seed_offer(seller="seller-1")
    proposal_id = await _seed_proposal(offer_id, buyer="buyer-1")
    deal = _parse(await z.call_tool("accept_deal", {
        "proposal_id": proposal_id,
        "accepting_agent_id": "seller-1",
    }))
    body = _parse(await z.call_tool("dispute_deal", {
        "deal_id": deal["deal_id"],
        "disputing_agent_id": "buyer-1",
        "reason": "did not deliver",
    }))
    assert body["status"] == "disputed"


async def test_dispute_by_outsider_blocked():
    offer_id = await _seed_offer(seller="seller-1")
    proposal_id = await _seed_proposal(offer_id, buyer="buyer-1")
    deal = _parse(await z.call_tool("accept_deal", {
        "proposal_id": proposal_id,
        "accepting_agent_id": "seller-1",
    }))
    body = _parse(await z.call_tool("dispute_deal", {
        "deal_id": deal["deal_id"],
        "disputing_agent_id": "stranger",
        "reason": "x",
    }))
    assert "error" in body


# ─── get_market_stats ─────────────────────────────────────────────────────────

async def test_market_stats_empty():
    body = _parse(await z.call_tool("get_market_stats", {}))
    assert body["stats"]["deals_closed"] == 0
    assert body["stats"]["active_offers"] == 0


async def test_market_stats_after_deal():
    offer_id = await _seed_offer(seller="seller-1")
    proposal_id = await _seed_proposal(offer_id, buyer="buyer-1", price=2.0, quantity=10)
    await z.call_tool("accept_deal", {
        "proposal_id": proposal_id,
        "accepting_agent_id": "seller-1",
    })
    body = _parse(await z.call_tool("get_market_stats", {}))
    assert body["stats"]["deals_closed"] == 1
    assert body["stats"]["total_volume_eur"] == 20.0
