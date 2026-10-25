-- Developer access: personal access tokens (MCP and API) and community skill packs.

CREATE TABLE IF NOT EXISTS api_tokens (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users(id),
    name            text NOT NULL,
    prefix          text NOT NULL,                             -- first characters, shown in lists
    token_hash      text NOT NULL UNIQUE,                      -- sha256 of the token; the token itself is shown once
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_used_at    timestamptz,
    revoked_at      timestamptz
);
CREATE INDEX IF NOT EXISTS api_tokens_user_idx ON api_tokens (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS skill_packs (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code            text NOT NULL UNIQUE,
    owner_id        uuid NOT NULL REFERENCES users(id),
    engine          text NOT NULL,                             -- the built-in skill that renders it
    name            text NOT NULL,
    status          text NOT NULL DEFAULT 'pending',           -- pending | approved | rejected | retired
    pack            jsonb NOT NULL,
    review_note     text,
    reviewed_by     uuid REFERENCES users(id),
    reviewed_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS skill_packs_status_idx ON skill_packs (status, updated_at DESC);
