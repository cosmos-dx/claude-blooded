-- Design briefs and research findings, kept per job for later analysis (which palettes, fonts and sources
-- show up for which topics, and later how they perform).

CREATE TABLE IF NOT EXISTS design_briefs (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          uuid NOT NULL UNIQUE REFERENCES jobs(id) ON DELETE CASCADE,
    skill           text NOT NULL,
    format          text NOT NULL,                             -- 9:16 | 16:9
    research_mode   text NOT NULL,                             -- web | offline
    dominant_hex    text NOT NULL,
    secondary_hex   text NOT NULL,
    accent_hex      text NOT NULL,
    display_font    text NOT NULL,
    text_font       text NOT NULL,
    accent_font     text NOT NULL,
    brief           jsonb NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS design_briefs_created_idx ON design_briefs (created_at DESC);

CREATE TABLE IF NOT EXISTS research_findings (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          uuid REFERENCES jobs(id) ON DELETE CASCADE,
    agent           text NOT NULL,                             -- researcher | design_director | ...
    topic           text NOT NULL,
    insight         text NOT NULL,
    source_url      text,
    source_title    text,
    confidence      text NOT NULL DEFAULT 'medium',
    verified        boolean NOT NULL DEFAULT false,            -- the URL was actually retrieved during research
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS research_findings_agent_idx ON research_findings (agent, created_at DESC);
CREATE INDEX IF NOT EXISTS research_findings_url_idx ON research_findings (source_url) WHERE source_url IS NOT NULL;
