# Checkpoint — 26 Oct 2026

Where the project stands, what was asked, what is done, and what is left. Product name is set by `BRAND_NAME` (currently "Reel Studio").

## Live

| | |
|---|---|
| Site | http://3.6.195.46 (Lightsail `nano_3_1`, Mumbai, static IP, ports 22/80/443) |
| Hosting cost | $5/month (≈ ₹440): 512 MB RAM, 20 GB SSD, IPv4, Postgres on the same box |
| Deployed commit | `7946f1b`: new design, Design Director, 9:16 + 16:9, MCP at `/mcp/` (deployed 26 Oct, 00:15 IST) |
| Server env | `/etc/claude-blooded.env`. `ADMIN_EMAILS`, `MEGALLM_API_KEY`, `MEGA_LLM_MODEL_ID=claude-sonnet-4-6` set; the MegaLLM key is still rejected, so reels can't run yet |
| SSH | `ssh -i ~/.ssh/claude-blooded.pem ec2-user@3.6.195.46` |
| Domain later | point it at the IP, then `sudo bash deploy/enable_https.sh <domain> <email>` |

## LLM keys (blocker)

The router tries providers in order: Anthropic API → Bedrock → MegaLLM → fake (`config/app.yaml`, `llm.profiles`). The first one with a key serves the call.

| Key | Status |
|---|---|
| `MEGALLM_API_KEY` (local `.env`) | Rejected by `ai.megallm.io` with "Invalid API key" on `/v1/messages` and `/v1/chat/completions`, with every auth header. The gateway does list `claude-opus-5-5`, so a fresh key from the MegaLLM dashboard should work with **no code change**. |
| Hireish AWS keys → Bedrock | "Operation not allowed": Claude isn't enabled on that account |
| `ANTHROPIC_API_KEY` | none |
| ElevenLabs | works, on the server |

Note: live web research (Design Director, researcher) needs the direct Anthropic API, which is the only provider with `capabilities: [web_search, web_fetch]`. On MegaLLM or Bedrock the Design Director still runs, but works from established design practice and says so in its findings (`web_research: false`).

## What was asked → status

| Request | Status | Where |
|---|---|---|
| Product repo with model router, agents, skills, workflows; factory pattern; service/DAO layers; no hardcoded business values | Done | `app/llm`, `app/agents`, `app/skills`, `app/workflows`, `app/services`, `app/dao`, `config/app.yaml` |
| Skills repo (skills only, generic) | `reel-tutor-01` pushed to `hireish/automations-marketing`; **`reel-kinetic-01` not pushed** (untracked locally, plus local edits to reel-tutor-01) | `../automations-marketing/instagram/` |
| Login, 1 free reel, packs ₹100/3×30s, ₹200/3×60s, ₹500/4×2min, ₹1000/7×3min | Done; Razorpay keys empty on the server (mock gateway in dev) | `plans:` in `config/app.yaml`, `app/payments` |
| Remove "Hireish" everywhere | Done | — |
| Nano host, least cost, public IP | Done (Lightsail nano; EC2 was blocked by the vCPU limit) | `deploy/provision_lightsail.sh` |
| Design Director agent: senior brand designer, internet research, 60-30-10 for colour **and** type, findings stored | Done (committed `34e7759`) | `app/agents/agents.py` (`DesignDirector`), `app/prompts/design_director.md`, `app/design/`, `app/services/design_service.py`, tables `design_briefs`, `research_findings` |
| "Agentic now, analysis infra later" | Briefs and findings with source URLs are stored per job (`design_briefs`, `research_findings`), ready for later analysis; the agent uses tool calls (`contrast_check`, web search) with a repair loop | `migrations/002_design.sql` |
| 9:16 and 16:9 with designs | Done: every skill renders both; 16 previews in `web/assets/previews`; format picker with live preview on the dashboard (this checkpoint) | `formats:` in config, `tools/make_previews.py` |
| MCP so creators, developers (and us) can add skills | Done: server at `/mcp/` with personal access tokens; dashboard token panel added (this checkpoint) | `app/mcp/server.py`, `app/services/developer*.py`, `migrations/003_developers.sql` |
| Landing page revamp: premium, simple, 60-30-10 palette, not-too-edgy fonts | Done (this checkpoint) | `web/index.html`, `web/assets/site.css` |
| Product name ideas for a domain | Not done | — |
| Hermes agent workflow | Only in the earlier plan doc; nothing in code | — |

## Design Director, in short

1. Gets the topic, the researcher's angle, the trend digest, the format and the style.
2. Researches (web search/fetch when the provider supports it): what performs for this audience, category conventions, colour meanings for Indian audiences.
3. Answers with a strict JSON brief: palette (dominant/secondary/accent with reasons), type (display/text/accent from an 11-font catalog), type-scale ratio, layout per format, do/don't, findings with sources.
4. `DesignSystem.finalize` validates the brief against `design:` in config: WCAG contrast (text ≥ 7:1, accent ≥ 3:1, auto-fixed by the smallest lightness change), allowed fonts and roles, allowed scale ratios. Each fix is listed in `adjustments`. A brief that can't be repaired gets one repair turn.
5. `app/design/ratio.py` spreads the 60-30-10 colours over screen time, beat by beat (accent on punchlines).
6. Theme `auto` (default) renders with the brief's palette; named themes (mono, ocean, poster, …) still work.

## MCP server (`/mcp/`)

Auth: `Authorization: Bearer rk_…` (create one in the studio under "developer access · MCP"; only the hash is stored, and tokens can be revoked). Foreign `Host` headers are rejected.

```json
{ "mcpServers": { "reels": { "url": "http://3.6.195.46/mcp/", "headers": { "Authorization": "Bearer rk_…" } } } }
```

| Tool | Who | What |
|---|---|---|
| `list_skills`, `get_skill` | anyone with a token | styles, themes, formats, languages; a skill's guide and spec schema |
| `design_rules`, `check_contrast` | anyone | 60-30-10 splits, contrast floors, fonts; contrast check with suggested fixes |
| `validate_skill_pack`, `submit_skill_pack`, `my_skill_packs` | creators | a pack is themes (3 colours) + fonts (display/text/accent) + writing notes on an existing engine; a code belongs to its first creator |
| `review_skill_packs`, `review_skill_pack` | admins (`ADMIN_EMAILS`) | approve/reject/retire; approved packs show in everyone's style list |
| `create_reel`, `get_reel` | anyone | make reels with your own credits, poll status and download links |

Tested end to end over HTTP: bad pack rejected with a fix suggestion, fixed pack accepted, ownership enforced, admin approval makes `chai-minimal-01` appear, bad/missing token and foreign host → 401.

## Landing page revamp (this checkpoint)

- **Palette, 60-30-10:** Midnight `#0B0B0F` (dominant: backgrounds), Bone `#F3EFE7` (secondary: text, light elements), Volt `#D4FF3F` (accent: CTAs, the italic keyword in each headline, ticks). One soft violet glow behind the hero for depth. Every text pair is ≥ 7:1, checked with `app/design/color.py` (lowest: muted grey on cards 7.17:1).
- **Type, 60-30-10:** Inter for reading, DM Serif Display for headlines (from the Design Director's catalog: "high-contrast serif, editorial, premium"), JetBrains Mono for small labels.
- **Sections:** hero with real rendered previews cycling in a phone frame → how it works (4 steps incl. design direction) → styles gallery with a 9:16 / 16:9 toggle → design principles (60·30·10, 7:1, 11 fonts) → pricing (from `/api/catalog`) → creators/MCP with a connect snippet → FAQ.
- Respects `prefers-reduced-motion`, has visible focus rings, and works on mobile (checked at 390 px).
- The studio and admin pages share the stylesheet, so they get the same look.
- **Dashboard fixes:** the Style dropdown was printing `[object Object]` after community packs were added (the API now returns objects); it now shows names and marks community packs. Added the Format picker with a live preview, and the token panel. Job cards show the format.

## Not done / next

1. Get a working LLM key (fresh MegaLLM key, or Anthropic/Bedrock). Put it in `/etc/claude-blooded.env`, `sudo systemctl restart claude-blooded-api claude-blooded-worker`, make one test reel.
2. Push `reel-kinetic-01` to `hireish/automations-marketing`.
3. Product name ideas with domain availability.
4. Razorpay live keys. (Login email works: SMTP via the Hireish GoDaddy mailbox official@hireish.in, sender shown as "Reel Studio".)
5. Hermes agent workflow, if still wanted.
6. README: add the Design Director, formats and MCP sections.
