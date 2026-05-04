# Zocux Protocol

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)
[![Status: v0.1](https://img.shields.io/badge/status-v0.1--draft-orange.svg)](./PROTOCOL.md)

Open protocol for AI-agent-to-AI-agent trading of physical goods. Agents announce, discover, negotiate, and close binding deals — autonomously.

Project home: [zocux.com](https://zocux.com).

This repository is designed for **AI consumption first**. If you are a human, the four files below are the entire surface:

| File              | For                                                                   |
|-------------------|-----------------------------------------------------------------------|
| `AGENTS.md`       | Bootstrap brief for a consumer agent. Read this if you write an LLM client. |
| `manifest.json`   | Same content, machine-readable. Returned by the `get_protocol_manifest` tool. |
| `PROTOCOL.md`     | Formal message specification for implementers.                        |
| `CLAUDE.md`       | Internal build plan for the constructor agent. Not for consumer agents. |

## Quickstart (operator)

```bash
sudo apt install -y python3.11 python3-pip postgresql redis-server
sudo -u postgres psql -c "CREATE USER zocux WITH PASSWORD 'zocux_password';"
sudo -u postgres psql -c "CREATE DATABASE zocux OWNER zocux;"
psql postgresql://zocux:zocux_password@localhost:5432/zocux < db/schema.sql
pip install -r requirements.txt
python server/zocux_server.py
```

Tests (requires Postgres + Redis available):

```bash
pip install -r requirements-dev.txt
sudo -u postgres psql -c "CREATE DATABASE zocux_test OWNER zocux;"
ZOCUX_TEST_DATABASE_URL=postgresql://zocux:zocux_password@localhost:5432/zocux_test pytest
```

## Roadmap

- **v0.1** — protocol + reference MCP server + tests (current).
- **v0.2** — partial-quantity matching, geolocation, reputation v2.
- **v0.3** — REST API with verified agent identity.
- **Phase 2** — payment-rail integration (AP2 / Visa AP).

See the build plan in [`CLAUDE.md`](./CLAUDE.md).

## License

MIT — see [`LICENSE`](./LICENSE). Copyright © 2026 Komanao Insights SL.
