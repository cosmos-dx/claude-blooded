# Hireish Reels (claude-blooded)

Type a topic, get a finished vertical reel: a script researched and planned by Claude, an Indian-accent voiceover from ElevenLabs, a rendered 1080×1920 video with music, captions and a posting pack for Instagram, YouTube and LinkedIn.

The landing page sells credit packs through Razorpay; every new account gets one free 30-second reel.

| Plan | Price (GST incl.) | Videos | Length each |
|---|---|---|---|
| Free (on sign-up) | ₹0 | 1 | 30 s, watermarked, economy models |
| Spark | ₹100 | 3 | 30 s |
| Boost | ₹200 | 3 | 60 s |
| Pro | ₹500 | 4 | 2 min |
| Studio | ₹1000 | 7 | 3 min |

Plans, models, voices, themes, the workflow order and every limit live in [`config/app.yaml`](config/app.yaml). Changing a price or adding a plan is a config edit, not a code change.

## How it works

```
browser ──► nginx ──► FastAPI (app/api) ──► services ──► DAOs ──► Postgres (schema "studio")
                                                │
                                   jobs table (queued)
                                                │
                       worker (app/workers) claims with FOR UPDATE SKIP LOCKED
                                                │
     moderate → research → plan → voice → render → mix → publish      (config: workflows.reel)
        │          │        │       │        │       │       │
     Moderator Researcher Planner VoiceDirector Skill  ffmpeg Publisher       ← agents call the ModelRouter
                                    ElevenLabs                                ← TTS factory
```

* **Model router** (`app/llm/router.py`): each agent role maps to a profile (`premium` = Claude Opus 5.5, `economy` = Claude Haiku 5.5). A profile lists providers in order: Anthropic API → Amazon Bedrock → MegaLLM. The first one with a key serves the call. If it fails with a retryable error, the next one takes over. Every call's tokens and cost are written to `usage_ledger`.
* **Factories**: LLM providers, TTS providers, payment gateways, mailers, storage, skills, agents and workflow steps all register by name in a `Registry` (`app/core/registry.py`). Config picks the implementation. Adding Gemini, Cashfree or S3 means writing one class and registering it.
* **Skills** (`app/skills/`) are the visual styles. `reel-tutor-01` is the black point-cloud explainer style. `reel-kinetic-01` is the bold color-block poster style. A skill tells the planner what spec to write, then renders that spec against the voice timeline.
* **Credits**: a job reserves one credit inside the same transaction that creates it. A failed job refunds the credit. Payment fulfilment is idempotent: the confirm callback and the webhook can both arrive without granting twice.
* **Retention**: finished videos are deleted 30 minutes after they're done (`storage.retention_minutes`); the dashboard says so.

More detail is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Run it locally

Needs Python 3.12+, ffmpeg and Postgres 13+.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # then set the values (see below)
sh deploy/fetch_fonts.sh ./var/fonts
.venv/bin/python -m app.db.migrate
APP_ENV=development .venv/bin/uvicorn app.main:app --port 8000     # web
APP_ENV=development .venv/bin/python -m app.workers.worker          # renders, in a second terminal
```

For a fully offline run, set `LLM_FAKE=true`, `TTS_PROVIDER=fake`, `PAYMENT_GATEWAY=mock` and `MAIL_PROVIDER=console`: login codes print in the API log and checkout completes without paying.

## Environment

| Variable | Needed for |
|---|---|
| `DATABASE_URL` | everything except the landing page |
| `JWT_SECRET` | login sessions (bootstrap generates one on the server) |
| `ANTHROPIC_API_KEY`, `AWS_BEDROCK_API_KEY_ANTHROPIC`, `MEGALLM_API_KEY` | at least one, for scripts |
| `ELEVEN_LABS_API_KEY` | voiceovers |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` | taking payments; point a Razorpay webhook (`payment.captured`, `order.paid`) at `/api/webhooks/razorpay` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL` | sending login codes |
| `ADMIN_EMAILS` | who can open `/admin` (revenue, spend, margin) |
| `PUBLIC_BASE_URL`, `COOKIE_SECURE` | set `COOKIE_SECURE=false` until HTTPS is on |

The full list is in [.env.example](.env.example). Comments in env files must be on their own line, because systemd keeps everything after `=` as the value.

## Deploy (AWS, one small box)

```bash
SUBNET_ID=subnet-… SECURITY_GROUP_ID=sg-… ./deploy/provision_ec2.sh
```

The script launches a `t4g.nano` (Graviton, Amazon Linux 2023), creates an SSH key in `~/.ssh/claude-blooded.pem` and runs [`deploy/bootstrap.sh`](deploy/bootstrap.sh). Bootstrap adds 2 GB swap and installs Python, nginx and static ffmpeg, the fonts, two systemd services (`claude-blooded-api`, `claude-blooded-worker`) and nginx on port 80. Re-run `bootstrap.sh` on the server to deploy a new commit.

Then on the server:

```bash
sudo nano /etc/claude-blooded.env
sudo systemctl restart claude-blooded-api claude-blooded-worker
```

For HTTPS, point a domain at the instance and run `sudo bash deploy/enable_https.sh reels.example.com you@example.com`. That uses Let's Encrypt, so running it accepts their subscriber agreement.

### Hosting cost (ap-south-1, on-demand, from the AWS Pricing API)

| Item | Rate | Per month |
|---|---|---|
| t4g.nano instance (2 vCPU burst, 0.5 GB RAM) | $0.0028/hr | $2.04 |
| Public IPv4 address | $0.005/hr | $3.65 |
| 12 GB gp3 disk | $0.0912/GB-month | $1.09 |
| Data out | first 100 GB/month free, then $0.109/GB | $0 at launch volumes |
| **Total** | | **≈ $6.80 ≈ ₹600** |

The database is the existing Postgres, so it adds nothing. The instance launches with standard CPU credits, so it can never bill for burst; it slows down instead.

**What a nano can do:** it renders one reel at a time. It earns 144 CPU credits a day, about 70 minutes of both cores at full speed; after that it drops to 5% of a core until credits refill. Short kinetic reels are light. Long point-cloud reels (2–3 min) are the heaviest jobs and will be slow on 0.5 GB of RAM plus swap. When demand grows, change the instance type to `t4g.small` (2 GB RAM, $8.18/month, total ≈ $12.90 ≈ ₹1,140) and set `RENDER_PROCESSES=2`. Nothing else changes.

## Project layout

```
app/core        config, registry, DI container, errors, security, ffmpeg
app/db          connection pool, migration runner
app/dao         SQL only (users, otp, plans, orders, credits, jobs, events, usage, trends)
app/services    business rules (auth, plans, payments, jobs, costs, admin)
app/llm         providers (anthropic, bedrock, anthropic_compatible, fake) + router
app/tts         ElevenLabs + fake
app/payments    Razorpay + mock
app/agents      moderator, researcher, planner, voice director, publisher, trend scout
app/prompts     agent system prompts
app/skills      reel-tutor-01, reel-kinetic-01, shared audio/timing/music
app/workflows   pipeline steps and runner
app/workers     job worker + maintenance (expiry, stale jobs, daily trends)
app/api         HTTP routes
web/            landing page, dashboard, admin
migrations/     SQL schema
deploy/         EC2, bootstrap, systemd, nginx, HTTPS
```
