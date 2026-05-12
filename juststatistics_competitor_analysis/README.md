# Competitor Creative Intelligence Engine

An automated competitor research pipeline for e-commerce creative agencies. Given a set of competitor ad screenshots and customer reviews, it produces 12 ranked ad copy hooks and a structured brand intelligence report — ready to hand directly to a creative team.

## What it does

```
POST /webhook/competitor-intelligence
  { brand_name, ad_screenshots[], review_texts[] }
```

Returns:

```json
{
  "hooks": [ ...12 hooks, each with hook_text, confidence_score, source_evidence... ],
  "brand_report": "# Brand Research Report: ...",
  "google_doc_url": "https://docs.google.com/document/d/...",
  "run_stats": { "estimated_cost_usd": 0.15, "hooks_generated": 12 }
}
```

## Pipeline

```
Webhook
  └── Input Validator (Haiku 4.5)
        ├── Vision Branch
        │     Prepare Ad Items → Vision Analyst API (Sonnet 4.6)
        │     → Parse → Vision Results Merger
        │
        └── Review Branch
              Prepare Review Batches → Review Miner API (Haiku 4.5)
              → Parse → Review Aggregator
                    ↓ Merge
          Prepare Hook Request → Hook Strategist API (Sonnet 4.6)
          → Parse Hook Response
          → Prepare Report Request → Report Writer API (Sonnet 4.6)
          → Parse Report Response
          → Output Formatter
          → Create Brand Report Doc (Google Drive)
          → Save Run History (PostgreSQL)
          → Respond to Webhook
```

See [`docs/pipeline.html`](docs/pipeline.html) for a visual diagram.

## Stack

| Layer | Technology |
|---|---|
| Orchestration | [n8n](https://n8n.io) self-hosted (Docker) |
| Vision + synthesis | Claude Sonnet 4.6 (`claude-sonnet-4-6`) |
| Classification | Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) |
| Run history | PostgreSQL 15 |
| Output | Google Drive (Google Doc per run) |

## Model tiering

| Node | Model | Reason |
|---|---|---|
| Vision Analyst | Sonnet 4.6 | Vision input required |
| Hook Strategist | Sonnet 4.6 | Creative reasoning |
| Report Writer | Sonnet 4.6 | Long-form structured output |
| Review Miner | Haiku 4.5 | Classification only |
| Input Validator | Haiku 4.5 | Schema check |

## Cost

~$0.12–0.15 per run (1 image + 20 reviews). Prompt caching active on all system prompts.

## Running locally

**Prerequisites:** Docker, an Anthropic API key.

```bash
# 1. Start n8n
docker run -d --rm -p 5678:5678 \
  -e N8N_SECURE_COOKIE=false \
  -v n8n_local_data:/home/node/.n8n \
  docker.n8n.io/n8nio/n8n

# 2. Import the workflow
# Open http://localhost:5678 → Import → n8n/workflows/competitor_intelligence_main.json

# 3. Add your Anthropic API key as a Header Auth credential in n8n
#    Credentials → New → Header Auth → name: x-api-key, value: sk-ant-...

# 4. Inject a test screenshot and fire the pipeline
bash tests/inject_screenshot.sh ~/Desktop/your_ad_screenshot.png
bash tests/send_test.sh
```

## Credentials required

| Service | n8n credential type | Used by |
|---|---|---|
| Anthropic | Header Auth (`x-api-key`) | All 4 Claude API nodes |
| Google Drive | Google Drive OAuth2 | Create Brand Report Doc node |
| PostgreSQL | Postgres | Save Run History node (disable locally) |

## Repo structure

```
n8n/
  workflows/   # importable n8n workflow JSON
  code_nodes/  # JS source for all Code nodes
docs/
  pipeline.html      # visual pipeline diagram
  architecture.md
schemas/
  workflow_envelope.json  # JSON Schema for webhook input
tests/
  mock_payload.json       # 20 skincare reviews + placeholder image
  inject_screenshot.sh    # converts a PNG to base64 and injects into payload
  send_test.sh            # fires the payload at the webhook
scripts/
  init-db.sh             # creates run_history table in PostgreSQL
  backup_workflows.sh
  health_check.sh
```
