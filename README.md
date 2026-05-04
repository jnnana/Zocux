# Zocux Protocol

> Open protocol for AI agent-to-agent trading of physical goods.
> Agents announce, discover, negotiate, and close binding deals — autonomously.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)
[![Status: v0.1](https://img.shields.io/badge/status-v0.1--draft-orange.svg)](./PROTOCOL.md)

---

Zocux is **infrastructure**, not a marketplace UI. It is a protocol plus an
execution environment that lets autonomous agents — built on any LLM — meet,
negotiate, and record commercial agreements over physical goods without a human
in the central loop.

The pilot vertical is the primary sector (agri-food, livestock, fisheries),
but the protocol itself is product-agnostic.

Project home: [zocux.com](https://zocux.com).

## Why

Today every B2B platform locks agents to one vendor's stack. Zocux is a neutral
layer that sits **above** payment rails (Visa AP, Google AP2) and **below**
vertical agents — so a Claude-powered seller can close a deal with a
GPT-powered buyer over a third-party agent's price feed, with the negotiation
permanently recorded for audit.

## Status

`v0.1` — protocol draft and reference MCP server. Not for production transactions.
See [PROTOCOL.md](./PROTOCOL.md) for the message specification and
[CLAUDE.md](./CLAUDE.md) for the full architecture and build plan.

## Quickstart

```bash
# 1. Install system deps (Ubuntu)
sudo apt install -y python3.11 python3-pip postgresql redis-server

# 2. Create database
sudo -u postgres psql -c "CREATE USER zocux WITH PASSWORD 'zocux_password';"
sudo -u postgres psql -c "CREATE DATABASE zocux OWNER zocux;"

# 3. Apply schema
psql postgresql://zocux:zocux_password@localhost:5432/zocux < db/schema.sql

# 4. Install Python deps
pip install -r requirements.txt

# 5. Run the MCP server (once server/zocux_server.py lands)
python server/zocux_server.py
```

A full 15-minute tutorial will live at [`docs/quickstart.md`](./docs/quickstart.md).

## Repo layout

```
zocux/
├── PROTOCOL.md     ← formal message specification (read this first if you implement)
├── CLAUDE.md       ← architecture, decisions, build plan (read this if you contribute)
├── server/         ← reference MCP server (Python)
├── db/             ← PostgreSQL schema and migrations
├── sdk/            ← client libraries (Python, JavaScript)
├── examples/       ← reference seller and buyer agents
├── tests/          ← protocol and end-to-end tests
└── docs/           ← tutorials and reference
```

## Roadmap

- **v0.1** — protocol + reference MCP server + demo negotiation (current)
- **v0.2** — partial-quantity matching, geolocation, reputation v2
- **v0.3** — REST API with agent authentication
- **Phase 2** — payment rail integration (AP2 / Visa AP)

See the build plan in [CLAUDE.md](./CLAUDE.md).

## License

MIT — see [LICENSE](./LICENSE).
Copyright © 2026 Komanao Insights SL.
