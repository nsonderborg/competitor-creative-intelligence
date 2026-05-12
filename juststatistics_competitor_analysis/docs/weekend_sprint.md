# Weekend Sprint — Competitor Intelligence MVP
**Target: first full pipeline run by Sunday evening**
**Date: 2026-05-02 (Sat) → 2026-05-03 (Sun)**

---

## Saturday — Infrastructure + First Working Node

### Session 1 — VPS + n8n Live (~3h)
- [ ] Buy Hostinger KVM 2 (Ubuntu 22.04 LTS)
- [ ] SSH in, install Docker + Docker Compose v2
  ```bash
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker $USER
  ```
- [ ] Clone repo to `/opt/juststatistics_competitor_analysis/`
- [ ] `cp .env.example .env` — fill all values
  - Generate keys: `openssl rand -hex 16` (encryption key), `openssl rand -base64 24` (passwords)
  - Add `ANTHROPIC_API_KEY`
- [ ] `docker compose up -d`
- [ ] Verify: `docker compose ps` (both running), `curl http://localhost:5678/healthz`
- [ ] Either: point domain DNS A record → VPS IP, OR test on raw IP for now
- [ ] Run `run_history` DDL (copy from `CLAUDE.md`)
- [ ] Set cron for `health_check.sh`

**Done when:** n8n UI opens in browser, PostgreSQL connected.

---

### Session 2 — Import Workflow + Paste Prompts (~2h)
- [ ] Open n8n → Import from file → `n8n/workflows/competitor_intelligence_main.json`
- [ ] Settings → Environment Variables → add `ANTHROPIC_API_KEY`
- [ ] Paste system prompts into the 4 Code nodes (each marked with ⚠️):
  - `Prepare Ad Items` → Agent 1: Vision Analyst (from `PROMPTS.md`)
  - `Prepare Review Batches` → Agent 2: Review Miner
  - `Prepare Hook Request` → Agent 3: Hook Strategist
  - `Prepare Report Request` → Agent 4: Report Writer
- [ ] Create Postgres credential in n8n (host: `postgres`, port: `5432`, db/user/pass from `.env`)
- [ ] Update `Save Run History` node → select the credential
- [ ] **First smoke test** — fire the mock payload (reviews only, no real image):
  ```bash
  ./tests/send_test.sh
  ```
- [ ] Check n8n execution log — Review Miner → Aggregator should complete
- [ ] Check `run_history` table has a row:
  ```bash
  docker compose exec postgres psql -U n8n_admin -d n8n -c "SELECT brand_name, status, estimated_cost_usd FROM run_history;"
  ```

**Done when:** Review chain runs end-to-end, row in `run_history`.

---

## Sunday — Vision + Full Pipeline

### Session 3 — Vision Analyst Live (~2h)
- [ ] Take a real Meta Ads Library screenshot (any competitor brand)
- [ ] Inject it into the test payload:
  ```bash
  ./tests/inject_screenshot.sh ~/Desktop/competitor_ad.png
  ```
- [ ] Fire full payload:
  ```bash
  ./tests/send_test.sh
  ```
- [ ] Inspect Vision Analyst output in n8n execution log — verify JSON structure matches schema
- [ ] If Vision Analyst fails: check image is valid base64, check `ANTHROPIC_API_KEY` env var is set
- [ ] Run with 3–5 real ad screenshots from the same brand

**Done when:** Vision Analyst returns valid structured JSON for at least one real ad.

---

### Session 4 — Full End-to-End Run (~2h)
- [ ] Grab 20–40 real Trustpilot reviews for a brand (copy-paste into `mock_payload.json` → `review_texts`)
- [ ] Use 3–5 real Meta Ads Library screenshots for the same brand
- [ ] Fire full pipeline — watch execution log in real time
- [ ] Review output:
  - `hooks[]` — are they specific and grounded in the reviews?
  - `brand_report` — does it read like a usable agency doc?
  - `run_stats.estimated_cost_usd` — should be ~$0.10–0.20
  - `run_stats.duration_seconds` — check execution time is reasonable
- [ ] Paste the `brand_report` markdown into Notion or a `.md` file to review formatting
- [ ] Fix any issues, re-run

**Done when:** Full pipeline runs for a real brand, hooks and report look usable.

---

### Session 5 — Polish (~1h, optional)
- [ ] Configure `.mcp.json` to connect Claude Code to the live n8n instance
  ```json
  {
    "mcpServers": {
      "n8n": {
        "command": "npx",
        "args": ["-y", "n8n-mcp"],
        "env": {
          "N8N_API_URL": "https://your-domain.com",
          "N8N_API_KEY": "your-n8n-api-key"
        }
      }
    }
  }
  ```
- [ ] Export the working workflow from n8n → overwrite `n8n/workflows/competitor_intelligence_main.json`
- [ ] Commit everything to git

---

## Fallback — If VPS Takes Time

If DNS propagation is slow or VPS setup runs over, do Session 2 locally:
- Docker is already installed on your Mac
- Run n8n locally: `docker run -it --rm -p 5678:5678 -v n8n_local_data:/home/node/.n8n docker.n8n.io/n8nio/n8n`
- Import the workflow, paste prompts, run smoke test locally
- Migrate to VPS once it's ready — workflow exports cleanly

---

## Success Criteria

| Metric | Target |
|--------|--------|
| Pipeline runtime | Reasonable for async research task |
| Cost per run | < $0.20 |
| Hooks generated | 12, each with confidence score |
| Report length | 800–1200 words |
| run_history row | present with cost estimate |
