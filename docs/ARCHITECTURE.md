# Architecture

## Principles

1. **Config over code.** Prices, plans, models, effort levels, provider order, voices, themes, workflow order, limits and retention come from `config/app.yaml`. Secrets come only from the environment (`${VAR}` placeholders). `config/app.<APP_ENV>.yaml` overlays per environment.
2. **Factories everywhere a vendor could change.** One generic `Registry[T]` (`app/core/registry.py`). Implementations register by name; config names the one to build.

   | Registry | Implementations | Chosen by |
   |---|---|---|
   | `PROVIDERS` (LLM) | `anthropic`, `bedrock`, `anthropic_compatible`, `fake` | `llm.providers.*.kind` |
   | `TTS` | `elevenlabs`, `fake` | `tts.provider` |
   | `GATEWAYS` | `razorpay`, `mock` | `payments.gateway` |
   | `MAILERS` | `smtp`, `console` | `mail.provider` |
   | `STORES` | `local` | `storage.provider` |
   | `SKILLS` | `reel-tutor-01`, `reel-kinetic-01` | `skills.enabled` + the user's pick |
   | `AGENTS` | moderator, researcher, planner, voice_director, publisher, trend_scout | `llm.roles` |
   | `STEPS` | moderate, research, plan, voice, render, mix, publish | `workflows.reel` |

3. **Strict layers.** Routes parse HTTP and call one service method. Services hold the business rules and transactions. DAOs hold SQL and nothing else. No layer reaches past the one below it.
4. **One composition root.** `app/core/container.py` builds everything once and wires dependencies by constructor. Nothing calls a constructor of another layer by itself, which keeps every piece swappable in tests.

## Request lifecycle

```
POST /api/jobs ─► JobService.create
                    ├─ validate against the user's credit (length, tier) and limits
                    └─ in one transaction: CreditDAO.reserve (FOR UPDATE SKIP LOCKED) + JobDAO.insert(queued)

worker loop ─► JobDAO.claim_next (FOR UPDATE SKIP LOCKED, status → running)
             ─► Workflow.run(steps from config)
                   each step: progress span → job_events row; cost scope → usage_ledger rows
             ─► success: JobDAO.finish(duration, files) │ failure: refund credit, friendly error, delete workdir
maintenance ─► delete outputs past retention, fail jobs stuck past job_timeout, daily Trend Scout
```

The dashboard polls `GET /api/jobs/{id}` for status, stage messages, progress and (for admins) cost so far.

## Model router

* **Profiles**: `premium` (Opus, medium effort) and `economy` (Haiku, low effort). Each lists providers in fallback order.
* **Roles**: each agent maps to a profile, or to `tier`, meaning "whatever the job's tier uses". Free jobs plan on Haiku and paid jobs plan on Opus.
* **Availability**: a provider is available when its key is set (or `enabled` for `fake`). `ModelRouter.available()` is logged at startup.
* **Failover**: on a retryable `ProviderError` (rate limit, overload, 5xx, connection), the router moves to the next provider in the profile. A `Conversation` pins the provider that served its first turn, so the planner's repair and shorten turns go back to the same model.
* **Calls**: streaming, adaptive thinking, `output_config.effort` from the profile, and a cached system prompt. On the direct Anthropic API, server-side fallbacks are enabled (`fallbacks="default"`).
* **Cost**: every response's usage goes through `CostService.record_llm`. That service prices the tokens from `llm.prices_usd_per_mtok`, converts at `money.usd_inr`, and writes `usage_ledger` attached to the current job and step.

## Agents

Agents are thin: a system prompt file in `app/prompts/<role>.md`, a JSON contract, and one repair turn if the JSON doesn't parse or validate.

| Agent | Input | Output |
|---|---|---|
| Moderator | request text | allow / reason (regional slang allowed; hate, harassment of real people, sexual content refused) |
| Researcher | request + latest trend digest | angle, hook, key facts, audience |
| Planner | skill guide + research + length budget | skill spec (scenes or beats with voice lines) |
| Voice Director | request + voice catalog | voice code per speaker role |
| Publisher | final spec | Instagram caption and hashtags, YouTube title, description and tags, LinkedIn post, posting time |
| Trend Scout | YouTube most-popular (IN, Science & Tech) | daily digest used by the Researcher |

## Skills

A skill (`app/skills/base.py`) owns a visual style end to end:

* `guide(...)`: the planning instructions and JSON schema handed to the Planner, filled with the length budget.
* `validate(spec)`, `lines(spec)`, `apply_line_edits(...)`: how the voice step reads and shortens the script.
* `music_spec(spec)`: the music bed's sections.
* `render(workdir, spec, theme, progress, processes)`: writes `video_silent.mp4` timed to `timeline.json`.

Shared pieces: `audio.py` (ElevenLabs synthesis per line, cached by content hash, word timing), `timing.py` (voice-activity word timing), `music.py` (synthesized bed). Adding a style means one new package and adding it to `skills.enabled`.

## Data model (schema `studio`)

| Table | Purpose |
|---|---|
| `users` | email, name, created_at, last_login_at |
| `otp_codes` | HMAC-hashed login codes, attempts, expiry |
| `plans` | synced from config at startup (code, price, videos, max_seconds, tier) |
| `orders` | one row per checkout; `gateway_order_id` unique |
| `credit_packs` | credits granted per order or sign-up; `order_id` unique, one sign-up grant per user |
| `jobs` | request, status, progress, stage, error, outputs, expiry |
| `job_events` | stage-by-stage log shown on the dashboard |
| `usage_ledger` | every LLM and TTS call: provider, model, tokens or chars, USD, INR |
| `payment_events` | webhook dedupe (gateway + event id unique) |
| `trend_digests` | daily Trend Scout output |

## Payments

1. `POST /api/checkout {plan}` creates an `orders` row and a Razorpay order, and returns the key and order id to the browser.
2. Razorpay Checkout runs in the browser. On success the browser posts the signature to `/api/checkout/confirm`, which verifies the HMAC of `order_id|payment_id` with the key secret.
3. Razorpay also calls `/api/webhooks/razorpay`, which verifies the body HMAC with the webhook secret and dedupes on `payment_events`.
4. Both paths call the same `_fulfil`. It marks the order paid and grants the credit pack in one transaction, guarded by unique keys, so a double delivery grants once.

Prices are GST-inclusive. The admin page shows revenue, net after 18% GST and a 2% gateway fee, API spend by provider, and margin.

## Security

* Login is an email OTP (HMAC-hashed, 5 attempts, rate-limited per email), then a 72-hour JWT in an httpOnly, SameSite=Lax cookie (`Secure` once HTTPS is on).
* The mock gateway refuses to load when `APP_ENV=production`.
* Output files are served only to their owner, and only by whitelisted names.
* Security headers on every response; nginx hides its version and limits request bodies to 1 MB.

## Scaling path

| Pressure | Change |
|---|---|
| Renders queue up | bigger instance + `RENDER_PROCESSES`; the worker claim is already safe for many workers |
| More than one box | add an `s3` store to `STORES` (outputs currently sit on the box's disk), then run workers on separate instances |
| LLM rate limits | add keys/providers to a profile; the router fails over in order |
| New gateway / mailer / voice vendor | one class + `register(...)` + a config line |
