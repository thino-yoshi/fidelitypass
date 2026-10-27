-- ══════════════════════════════════════════════════════════════
-- SCHEMA QARTA — Neon PostgreSQL
-- Créé le 2026-10-27 — migration depuis Supabase
-- ══════════════════════════════════════════════════════════════

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── 1. users ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email               TEXT NOT NULL,
    name                TEXT NOT NULL DEFAULT '',
    user_type           TEXT NOT NULL DEFAULT 'client',  -- 'client' | 'merchant'
    password_hash       TEXT NOT NULL DEFAULT 'SUPABASE_AUTH',
    fcm_token           TEXT,
    profile_picture_url TEXT,
    notif_push          BOOLEAN DEFAULT TRUE,
    notif_offres        BOOLEAN DEFAULT TRUE,
    notif_visites       BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- ── 2. merchants ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS merchants (
    id                      UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    business_name           TEXT NOT NULL,
    category                TEXT NOT NULL DEFAULT '',
    stamps_required         INT NOT NULL DEFAULT 10,
    reward_description      TEXT NOT NULL DEFAULT '',
    program_type            TEXT NOT NULL DEFAULT 'stamps',  -- 'stamps' | 'points'
    points_per_euro         INT NOT NULL DEFAULT 10,
    points_required         INT NOT NULL DEFAULT 100,
    address                 TEXT DEFAULT '',
    phone                   TEXT DEFAULT '',
    website                 TEXT DEFAULT '',
    opening_hours           TEXT DEFAULT '',
    opening_days            TEXT DEFAULT '',
    description             TEXT DEFAULT '',
    static_qr_token         TEXT UNIQUE,
    inactive_threshold_days INT DEFAULT 30,
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

-- ── 3. merchant_card_designs ──────────────────────────────────
CREATE TABLE IF NOT EXISTS merchant_card_designs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id UUID NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    card_design JSONB,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mcd_merchant ON merchant_card_designs(merchant_id);

-- ── 4. merchant_rewards ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS merchant_rewards (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id     UUID NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    stamps_required INT NOT NULL,
    description     TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── 5. loyalty_cards ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS loyalty_cards (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    merchant_id   UUID NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    stamps_count  INT NOT NULL DEFAULT 0,
    points_count  INT NOT NULL DEFAULT 0,
    qr_token      TEXT NOT NULL UNIQUE DEFAULT gen_random_uuid()::TEXT,
    merchant_note TEXT DEFAULT '',
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(client_id, merchant_id)
);

CREATE INDEX IF NOT EXISTS idx_lc_client   ON loyalty_cards(client_id);
CREATE INDEX IF NOT EXISTS idx_lc_merchant ON loyalty_cards(merchant_id);

-- ── 6. scan_history ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scan_history (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id    UUID NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    client_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    card_id        UUID NOT NULL REFERENCES loyalty_cards(id) ON DELETE CASCADE,
    stamps_count   INT NOT NULL DEFAULT 0,
    reward_reached BOOLEAN NOT NULL DEFAULT FALSE,
    manual         BOOLEAN NOT NULL DEFAULT FALSE,
    scanned_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sh_merchant  ON scan_history(merchant_id);
CREATE INDEX IF NOT EXISTS idx_sh_client    ON scan_history(client_id);
CREATE INDEX IF NOT EXISTS idx_sh_card      ON scan_history(card_id);
CREATE INDEX IF NOT EXISTS idx_sh_scanned   ON scan_history(scanned_at DESC);

-- ── 7. rewards ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rewards (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id   UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    merchant_id UUID NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    description TEXT NOT NULL DEFAULT '',
    earned_at   TIMESTAMPTZ DEFAULT NOW(),
    redeemed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_rewards_client   ON rewards(client_id);
CREATE INDEX IF NOT EXISTS idx_rewards_merchant ON rewards(merchant_id);

-- ── 8. client_notifications ──────────────────────────────────
CREATE TABLE IF NOT EXISTS client_notifications (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    merchant_id   UUID REFERENCES merchants(id) ON DELETE SET NULL,
    merchant_name TEXT NOT NULL DEFAULT '',
    title         TEXT NOT NULL,
    body          TEXT NOT NULL DEFAULT '',
    type          TEXT NOT NULL DEFAULT 'general',
    read          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cn_client     ON client_notifications(client_id);
CREATE INDEX IF NOT EXISTS idx_cn_created    ON client_notifications(created_at DESC);

-- ── 9. scheduled_notifications ───────────────────────────────
CREATE TABLE IF NOT EXISTS scheduled_notifications (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id  UUID NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    message      TEXT NOT NULL,
    scheduled_at TIMESTAMPTZ NOT NULL,
    filter_type  TEXT NOT NULL DEFAULT 'broadcast',
    filter_value INT,
    sent         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sn_merchant ON scheduled_notifications(merchant_id);
CREATE INDEX IF NOT EXISTS idx_sn_due      ON scheduled_notifications(scheduled_at) WHERE sent = FALSE;

-- ── 10. merchant_codes ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS merchant_codes (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code       TEXT NOT NULL UNIQUE,
    email      TEXT NOT NULL,
    used       BOOLEAN NOT NULL DEFAULT FALSE,
    used_at    TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
