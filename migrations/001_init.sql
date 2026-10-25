-- Claude Blooded initial schema. Runs inside the schema from config (database.schema) via search_path.
-- Needs PostgreSQL 13+ (gen_random_uuid is built in).

CREATE TABLE IF NOT EXISTS users (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email           text NOT NULL UNIQUE,
    name            text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_login_at   timestamptz
);

CREATE TABLE IF NOT EXISTS otp_codes (
    id              bigserial PRIMARY KEY,
    email           text NOT NULL,
    code_hash       text NOT NULL,
    attempts        int NOT NULL DEFAULT 0,
    expires_at      timestamptz NOT NULL,
    consumed_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS otp_codes_email_idx ON otp_codes (email, created_at DESC);

-- Snapshot of config/app.yaml plans, upserted at startup so orders keep a stable reference.
CREATE TABLE IF NOT EXISTS plans (
    code            text PRIMARY KEY,
    name            text NOT NULL,
    price_paise     int NOT NULL,
    videos          int NOT NULL,
    max_seconds     int NOT NULL,
    tier            text NOT NULL,
    public          boolean NOT NULL DEFAULT true,
    sort            int NOT NULL DEFAULT 0,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS orders (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             uuid NOT NULL REFERENCES users(id),
    plan_code           text NOT NULL REFERENCES plans(code),
    amount_paise        int NOT NULL,
    currency            text NOT NULL,
    gateway             text NOT NULL,
    gateway_order_id    text UNIQUE,
    gateway_payment_id  text,
    status              text NOT NULL DEFAULT 'created',   -- created | paid | failed
    created_at          timestamptz NOT NULL DEFAULT now(),
    paid_at             timestamptz
);
CREATE INDEX IF NOT EXISTS orders_user_idx ON orders (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS credit_packs (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users(id),
    order_id        uuid UNIQUE REFERENCES orders(id),         -- null for the sign-up grant
    plan_code       text NOT NULL REFERENCES plans(code),
    tier            text NOT NULL,
    max_seconds     int NOT NULL,
    total           int NOT NULL,
    remaining       int NOT NULL CHECK (remaining >= 0),
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS credit_packs_user_idx ON credit_packs (user_id) WHERE remaining > 0;
CREATE UNIQUE INDEX IF NOT EXISTS credit_packs_one_signup_grant ON credit_packs (user_id) WHERE order_id IS NULL;

CREATE TABLE IF NOT EXISTS jobs (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users(id),
    pack_id         uuid NOT NULL REFERENCES credit_packs(id),
    status          text NOT NULL DEFAULT 'queued',            -- queued | running | done | failed | expired
    stage           text NOT NULL DEFAULT 'queued',
    progress        real NOT NULL DEFAULT 0,
    request         jsonb NOT NULL,                            -- problem, details, voice prompt, language, skill, theme, seconds
    tier            text NOT NULL,
    max_seconds     int NOT NULL,
    title           text,
    duration_s      real,
    publish_pack    jsonb,
    error           text,
    attempts        int NOT NULL DEFAULT 0,
    locked_by       text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    started_at      timestamptz,
    finished_at     timestamptz,
    expires_at      timestamptz
);
CREATE INDEX IF NOT EXISTS jobs_queue_idx ON jobs (created_at) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS jobs_user_idx ON jobs (user_id, created_at DESC);

-- One row per stage of a job, with what that stage spent (tokens, characters, money).
CREATE TABLE IF NOT EXISTS job_events (
    id              bigserial PRIMARY KEY,
    job_id          uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    stage           text NOT NULL,
    message         text,
    input_tokens    int NOT NULL DEFAULT 0,
    output_tokens   int NOT NULL DEFAULT 0,
    characters      int NOT NULL DEFAULT 0,
    cost_inr        numeric(10,2) NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS job_events_job_idx ON job_events (job_id, id);

-- Every paid call to a provider (LLM or TTS), for cost reporting.
CREATE TABLE IF NOT EXISTS usage_ledger (
    id              bigserial PRIMARY KEY,
    job_id          uuid REFERENCES jobs(id) ON DELETE SET NULL,
    kind            text NOT NULL,                             -- llm | tts
    provider        text NOT NULL,
    model           text NOT NULL,
    role            text,
    input_tokens    int NOT NULL DEFAULT 0,
    output_tokens   int NOT NULL DEFAULT 0,
    cache_read      int NOT NULL DEFAULT 0,
    cache_write     int NOT NULL DEFAULT 0,
    characters      int NOT NULL DEFAULT 0,
    cost_usd        numeric(12,6) NOT NULL DEFAULT 0,
    cost_inr        numeric(10,2) NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS usage_ledger_created_idx ON usage_ledger (created_at);

CREATE TABLE IF NOT EXISTS payment_events (
    id              bigserial PRIMARY KEY,
    gateway         text NOT NULL,
    event_id        text NOT NULL,
    event_type      text NOT NULL,
    payload         jsonb NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (gateway, event_id)
);

CREATE TABLE IF NOT EXISTS trend_digests (
    id              bigserial PRIMARY KEY,
    niche           text NOT NULL,
    digest          jsonb NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS trend_digests_niche_idx ON trend_digests (niche, created_at DESC);
