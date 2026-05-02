-- Troca Protocol — PostgreSQL schema v0.1
--
-- Idempotent: safe to run on a fresh database. The protocol_messages table is
-- append-only; never UPDATE, never DELETE. Reconstruct any view of the market
-- by replaying these rows.

-- ─── Registro inmutable de mensajes ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS protocol_messages (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    type            VARCHAR(20)  NOT NULL CHECK (type IN (
                        'ANNOUNCE','DISCOVER','PROPOSE','COUNTER',
                        'ACCEPT','REJECT','DISPUTE'
                    )),
    payload         JSONB        NOT NULL,
    agent_id        VARCHAR(100) NOT NULL,
    idempotency_key VARCHAR(120),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    -- Two calls with the same (agent_id, type, idempotency_key) are the same
    -- operation. NULL idempotency_key is treated as distinct (PostgreSQL default).
    UNIQUE (agent_id, type, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_messages_type    ON protocol_messages(type);
CREATE INDEX IF NOT EXISTS idx_messages_agent   ON protocol_messages(agent_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON protocol_messages(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_payload ON protocol_messages USING GIN(payload);

-- ─── Vista de ofertas activas ───────────────────────────────────────────────
-- Regular VIEW (no materializada) — siempre refleja estado actual sin REFRESH.

CREATE OR REPLACE VIEW active_offers AS
SELECT
    payload->>'offer_id'                          AS offer_id,
    payload->>'agent_id'                          AS agent_id,
    payload->>'product'                           AS product,
    (payload->>'quantity')::float                 AS quantity,
    payload->>'unit'                              AS unit,
    (payload->>'price_min')::float                AS price_min,
    payload->>'price_currency'                    AS currency,
    payload->>'location'                          AS location,
    (payload->>'available_until')::timestamptz    AS available_until,
    created_at
FROM protocol_messages m
WHERE type = 'ANNOUNCE'
  AND (payload->>'available_until')::timestamptz > NOW()
  AND NOT EXISTS (
        SELECT 1 FROM protocol_messages a
        WHERE a.type = 'ACCEPT'
          AND a.payload->>'offer_id' = m.payload->>'offer_id'
  );

-- ─── Acuerdos cerrados ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS closed_deals (
    deal_id          UUID            PRIMARY KEY,
    offer_id         VARCHAR(100)    NOT NULL,
    proposal_id      VARCHAR(100)    NOT NULL,
    seller_agent_id  VARCHAR(100)    NOT NULL,
    buyer_agent_id   VARCHAR(100)    NOT NULL,
    final_price      DECIMAL(12,2)   NOT NULL,
    final_quantity   DECIMAL(12,4)   NOT NULL,
    currency         VARCHAR(10)     NOT NULL,
    product          VARCHAR(200)    NOT NULL,
    accepted_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_deals_seller  ON closed_deals(seller_agent_id);
CREATE INDEX IF NOT EXISTS idx_deals_buyer   ON closed_deals(buyer_agent_id);
CREATE INDEX IF NOT EXISTS idx_deals_product ON closed_deals(product);

-- ─── Reputación de agentes ──────────────────────────────────────────────────
-- Calculada, no modificable manualmente. Reescrita con UNION ALL para
-- evitar la sintaxis frágil de CROSS JOIN LATERAL sobre VALUES.

CREATE OR REPLACE VIEW agent_reputation AS
WITH participants AS (
    SELECT seller_agent_id AS agent_id, accepted_at FROM closed_deals
    UNION ALL
    SELECT buyer_agent_id  AS agent_id, accepted_at FROM closed_deals
)
SELECT
    agent_id,
    COUNT(*)         AS deals_completed,
    MIN(accepted_at) AS first_deal,
    MAX(accepted_at) AS last_deal
FROM participants
GROUP BY agent_id;
