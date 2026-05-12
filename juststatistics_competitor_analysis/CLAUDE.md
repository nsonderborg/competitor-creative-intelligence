# CLAUDE.md — Competitor Creative Intelligence Engine

## Project Purpose

Automate the JustStatics pre-production research workflow.
Target: end-to-end pipeline per brand.

Output per run:
- `hooks[]` — 12 ad copy angle "hooks" ranked by confidence score
- `brand_report` — structured markdown brand intelligence report

## Architecture Overview

```
[Webhook / Manual Trigger]
        │
        ▼
[Input Validator]          ← Haiku 4.5 — schema check, fail fast
        │
        ├──────────────────────────────────────┐
        ▼                                      ▼
[Vision Analyst × N images]          [Review Fetcher]
 Sonnet 4.6 (vision)                  HTTP scraping node
 Parallel via SplitInBatches                   │
        │                                      ▼
[Vision Results Merger]             [Review Miner (batches of 20)]
 Code node                            Haiku 4.5 (classification)
        │                                      │
        └──────────────────┬───────────────────┘
                           ▼
                [Hook Strategist]
                 Sonnet 4.6 (synthesis)
                 Prompt-cached system prompt
                           │
                           ▼
                [Report Writer]
                 Sonnet 4.6 (synthesis)
                           │
                           ▼
                [Output Formatter]
                 Assembles FinalOutput envelope
                 Writes row to run_history (PostgreSQL)
                           │
                           ▼
                [Webhook Response / File Save]
```

## Stack

- **Orchestration:** n8n self-hosted (Docker, VPS)
- **Database:** PostgreSQL 15 (n8n state + run_history)
- **Vision + Synthesis:** Claude Sonnet 4.6 (`claude-sonnet-4-6`)
- **Classification:** Claude Haiku 4.5 (`claude-haiku-4-5-20251001`)
- **Data sources:** Meta Ads Library screenshots (images), Trustpilot/Amazon via scraping APIs
- **No external logging:** All prompt content stays within VPS + Anthropic API only

## Model Tiering — Hard Rules

NEVER use Sonnet where Haiku suffices.

| Task | Model | Reason |
|------|-------|--------|
| Image deconstruction (vision) | Sonnet 4.6 | Only Sonnet supports vision |
| Final synthesis (hooks) | Sonnet 4.6 | Creative reasoning required |
| Final report generation | Sonnet 4.6 | Long-form structured output |
| Review classification | Haiku 4.5 | Binary/label classification, no reasoning needed |
| Input validation | Haiku 4.5 | Schema checking, deterministic |
| Sentiment scoring | Haiku 4.5 | Simple numeric output |

Model IDs are **hardcoded** per node in n8n — never dynamic, never overridable via input.

## Prompt Caching Strategy

Use `cache_control: {"type": "ephemeral"}` on the `system` array for all four agent nodes.
In n8n HTTP Request body:

```json
{
  "system": [
    {
      "type": "text",
      "text": "<full system prompt>",
      "cache_control": {"type": "ephemeral"}
    }
  ]
}
```

Add header: `anthropic-beta: prompt-caching-2024-07-31`

Cache saves:
- Vision Analyst: ~900 token system prompt cached after image 1 — saves ~$0.009/run
- Review Miner: ~700 token system prompt cached after batch 1 — saves ~$0.001/run
- Hook Strategist / Report Writer: single calls per run — cache benefit on retries only

## Cost Estimate

| Node | Model | Est. Cost/Run |
|------|-------|--------------|
| Input Validator | Haiku 4.5 | ~$0.001 |
| Vision Analyst × 5 images | Sonnet 4.6 | ~$0.052 |
| Review Miner × 3 batches | Haiku 4.5 | ~$0.009 |
| Hook Strategist | Sonnet 4.6 | ~$0.021 |
| Report Writer | Sonnet 4.6 | ~$0.033 |
| **Total** | | **~$0.12/run** |

At 100 runs/month: ~$12/month. At 500 runs/month: ~$60/month.

## Data Sovereignty

- n8n logs written to PostgreSQL on the same VPS — never to n8n cloud
- `N8N_DIAGNOSTICS_ENABLED: false` — no telemetry to n8n servers
- Prompts and responses are NOT logged to disk beyond PostgreSQL execution history
- Anthropic API calls go directly from VPS to `api.anthropic.com` — no intermediary
- `.env` contains all secrets — never committed to git
- PostgreSQL data is on a named Docker volume mounted to VPS disk
- PostgreSQL port **not exposed** externally — internal Docker network only

## Conventions

- All n8n workflows exported as JSON and committed to `n8n/workflows/`
- Schema validation at Input Validator node — fail fast, don't pass invalid envelopes downstream
- All Claude API calls go through n8n HTTP Request nodes with Try/Catch error handling
- Error responses from Claude API must surface as workflow failures, not silent empties
- Every run writes a row to `run_history` in PostgreSQL: see schema below
- Costs are estimated post-run using token counts from API response `usage` field

## run_history Table DDL

Run once via n8n Execute Query node or direct psql:

```sql
CREATE TABLE IF NOT EXISTS run_history (
    run_id UUID PRIMARY KEY,
    brand_name TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running',
    ads_analysed INTEGER,
    reviews_processed INTEGER,
    hooks_generated INTEGER,
    total_input_tokens INTEGER,
    total_output_tokens INTEGER,
    estimated_cost_usd NUMERIC(10, 4),
    sonnet_calls INTEGER,
    haiku_calls INTEGER,
    error_message TEXT
);
```

## Environment Variables

```bash
# Claude API
ANTHROPIC_API_KEY=sk-ant-...

# PostgreSQL (n8n state)
POSTGRES_DB=n8n
POSTGRES_USER=n8n_admin
POSTGRES_PASSWORD=<strong-random>
POSTGRES_NON_ROOT_USER=n8n_app
POSTGRES_NON_ROOT_PASSWORD=<strong-random>

# n8n
N8N_BASIC_AUTH_USER=admin
N8N_BASIC_AUTH_PASSWORD=<strong-random>
N8N_ENCRYPTION_KEY=<32-char-hex: openssl rand -hex 16>
N8N_HOST=<your-vps-domain>
N8N_PORT=5678
N8N_PROTOCOL=https
WEBHOOK_URL=https://<your-domain>/

# Monitoring
HEARTBEAT_URL=https://uptime.betterstack.com/api/v1/heartbeat/<token>

# Scraping APIs (optional)
BRIGHTDATA_API_KEY=
APIFY_API_TOKEN=
```

## Commands

```bash
# Start full stack
docker compose up -d

# Start with nginx (SSL termination)
docker compose --profile nginx up -d

# View n8n logs
docker compose logs -f n8n

# Backup all workflows
./scripts/backup_workflows.sh

# Manual health check
./scripts/health_check.sh

# Connect to PostgreSQL
docker compose exec postgres psql -U n8n_admin -d n8n

# Restart n8n only (after workflow edits)
docker compose restart n8n

# Generate strong passwords
openssl rand -base64 24
openssl rand -hex 16
```

## Implementation Roadmap

### Step 1 — Infrastructure (Day 1, ~3h)
- [ ] `docker compose up -d` on VPS
- [ ] n8n accessible via domain + basic auth
- [ ] PostgreSQL healthy, `run_history` table created
- [ ] Health check cron running, heartbeat URL configured

### Step 2 — Vision Analyst Node (Day 2–3)
- [ ] HTTP Request node: base64 image → Sonnet 4.6 → Vision Analyst JSON
- [ ] Prompt caching active (`anthropic-beta` header set)
- [ ] Token counts captured from response `usage` field
- [ ] Error handling via Try/Catch node

### Step 3 — Full Pipeline (Day 4–7, ~8h)
- [ ] Review Miner (Haiku) → Review Aggregator (Code node)
- [ ] Hook Strategist (Sonnet) → Report Writer (Sonnet)
- [ ] Output Formatter → run_history INSERT
- [ ] Parallel Vision Analyst via SplitInBatches
- [ ] Webhook trigger live
- [ ] End-to-end test: 1 brand, 5 ads, 40 reviews
- [ ] Target: <$0.20 cost per run
