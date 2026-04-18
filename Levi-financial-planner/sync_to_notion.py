#!/usr/bin/env python3
"""
sync_to_notion.py — Notion sync for Levi financial planner

Pushes a monthly (or weekly) snapshot to a Notion database:
  - Real DKK figures (income, expenses, savings rate) — from local files only
  - Claude API analysis text (category % only — no merchant names, no raw transactions)
  - Budget-status color (select: På sporet / Marginal / Overskred)

Privacy model:
  Claude API sees: category aggregates %, portfolio weights %, returns %, profile text
  Claude API never sees: absolute DKK amounts, merchant names, account IDs
  Notion sees: curated real DKK figures you choose + Claude's text output
  Neither service sees raw transactions or the full picture.

Environment variables (in .env):
  NOTION_INTEGRATION_KEY  — Notion internal integration token (secret_xxx)
  NOTION_DB_ID            — Target Notion database ID (from Notion URL)
  ANTHROPIC_API_KEY       — For Claude API analysis (~3 øre per call)

  Optional:
  NOTION_WEEKLY_DB_ID     — Separate weekly database (falls back to NOTION_DB_ID)

Cron examples:
  Monthly sync on 1st at 08:30 (after generate_report.py at 08:00):
    30 8 1 * *  /path/to/python /path/to/sync_to_notion.py --type monthly

  Weekly sync Monday 07:45:
    45 7 * * 1  /path/to/python /path/to/sync_to_notion.py --type weekly

Usage:
  python sync_to_notion.py --type monthly
  python sync_to_notion.py --type monthly --dry-run   # prints payload, no Notion call
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from nordea_parser import (
    load_all_processed, build_context, build_balance_sheet_context,
    build_portfolio_context, load_categories, recategorize,
)

BASE_DIR       = Path(__file__).parent
PROCESSED      = BASE_DIR / "data/processed"
REPORTS        = BASE_DIR / "data/reports"
CONFIG_DIR     = BASE_DIR / "config"
PROFILE_FILE   = CONFIG_DIR / "profile.json"
PORTFOLIO_FILE = CONFIG_DIR / "portfolio.json"

for d in [PROCESSED, REPORTS, CONFIG_DIR]:
    d.mkdir(parents=True, exist_ok=True)


def log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


# ── Data loading ──────────────────────────────────────────────────────────────

def load_profile() -> dict:
    if PROFILE_FILE.exists():
        with open(PROFILE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_portfolio() -> dict:
    if PORTFOLIO_FILE.exists():
        with open(PORTFOLIO_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


# ── Context helpers ───────────────────────────────────────────────────────────

def _strip_merchant_names(context: str) -> str:
    """Remove TOP 10 UDGIFTER section (individual merchant rows) before Claude API call."""
    return re.sub(r"\nTOP 10 UDGIFTER:.*?(?=\nBUDGET|\n===|\Z)", "", context, flags=re.DOTALL)


def _build_redacted_context(df, profile: dict, portfolio: dict, days: int | None = None) -> str:
    """Build AI context with data minimisation: category % only, no merchant names."""
    ctx = build_context(df, profile, days=days, budgets=profile.get("budgets") or None)
    ctx = _strip_merchant_names(ctx)          # remove merchant-level detail
    ctx += build_balance_sheet_context(profile)
    if portfolio:
        ctx += build_portfolio_context(portfolio)  # % and EUR prices only — already redaction-safe
    return ctx


# ── Claude API ────────────────────────────────────────────────────────────────

GOLDMAN_SYSTEM = """Du er Chief Wealth Strategist hos Goldman Sachs Private Wealth Management med 25 års erfaring.
Lav strukturerede, datadrevne analyser med konkrete scores og DKK-tal. Identificer finansielle gaps og kvantificér konsekvenserne.
Svar altid på dansk med professionel, direkte tone."""

MONTHLY_PROMPT = """Lav en kompakt månedlig finansiel diagnose med:
1. **Finansiel Helbredsscore denne måned (X/10)**
2. **Opsparingsstatus** — er vi på sporet mod målet?
3. **Top 3 bekymringer** med estimeret DKK-konsekvens
4. **3 konkrete handlinger til næste måned** (mærket A1, A2, A3 — med DKK-impact)
5. **Portfolio** — kort kommentar til afkast og allokering (kun hvis porteføljedata tilgængeligt)

Max 800 ord. Fokuser på handlinger, ikke historik."""

WEEKLY_PROMPT = """Lav en kort ugentlig finansiel vurdering:
1. **Ugens status** — én præcis sætning
2. **Ét bekymrende mønster** med estimeret DKK-impact
3. **3 fokuspunkter næste uge** (mærket A1, A2, A3)

Max 300 ord."""


def ask_claude(prompt: str, system: str, context: str) -> str:
    """Call Claude API (non-streaming) and return the full response text."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY mangler i .env")
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic-pakken mangler — kør: pip install anthropic")

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=system,
        messages=[{"role": "user", "content": f"Her er mine finansielle data:\n\n{context}\n\n{prompt}"}],
    )
    return msg.content[0].text


def _extract_actions(analysis: str) -> str:
    """Pull A1/A2/A3 action lines from the Claude analysis."""
    lines = [l.strip() for l in analysis.splitlines() if re.search(r"\bA[123]\b", l)]
    return "\n".join(lines) if lines else ""


# ── Notion helpers ────────────────────────────────────────────────────────────

def _rich_text(text: str) -> list:
    """Split text into ≤2000-char Notion rich_text content blocks."""
    blocks = []
    while text:
        blocks.append({"text": {"content": text[:2000]}})
        text = text[2000:]
    return blocks


def _budget_status(df, profile: dict) -> str:
    """Return 'På sporet', 'Marginal', or 'Overskred' from current-month budget data."""
    import pandas as pd
    budgets = profile.get("budgets", {})
    active = {c: v for c, v in budgets.items() if v > 0}
    if not active:
        return "Ingen budget"
    now = pd.Timestamp.now()
    real = df[~df["reserveret"]] if "reserveret" in df.columns else df
    this_month = real[real["dato"].dt.year.eq(now.year) & real["dato"].dt.month.eq(now.month)]
    by_cat = this_month[this_month["beløb"] < 0].groupby("kategori")["beløb"].sum().abs()
    over = sum(1 for cat, limit in active.items() if float(by_cat.get(cat, 0)) > limit)
    near = sum(1 for cat, limit in active.items() if 0.8 * limit <= float(by_cat.get(cat, 0)) <= limit)
    if over > 0:
        return "Overskred"
    elif near > 0:
        return "Marginal"
    return "På sporet"


def push_to_notion(properties: dict, db_id: str, notion_key: str, dry_run: bool = False):
    """Create a new page in the Notion database with the given properties."""
    if dry_run:
        log("DRY RUN — ville have sendt følgende til Notion:")
        print(json.dumps(properties, indent=2, ensure_ascii=False, default=str))
        return

    try:
        from notion_client import Client
    except ImportError:
        raise RuntimeError("notion-client mangler — kør: pip install notion-client")

    notion = Client(auth=notion_key)
    notion.pages.create(
        parent={"database_id": db_id},
        properties=properties,
    )
    log("✅ Notion-side oprettet")


# ── Sync functions ────────────────────────────────────────────────────────────

def sync_monthly(df, profile: dict, portfolio: dict, dry_run: bool = False):
    import pandas as pd
    log("Bygger månedlig Notion-side...")

    real    = df[~df["reserveret"]] if "reserveret" in df.columns else df
    income  = float(real[real["beløb"] > 0]["beløb"].sum())
    expense = float(real[real["beløb"] < 0]["beløb"].sum())
    savings_rate = round((income + expense) / income * 100, 1) if income > 0 else 0.0
    budget_status = _budget_status(df, profile)

    # Claude API call with redacted context (no merchant names, % only)
    log("Kalder Claude API (kategorier og %-data — ingen handelsnavne)...")
    try:
        context  = _build_redacted_context(df, profile, portfolio, days=35)
        analysis = ask_claude(MONTHLY_PROMPT, GOLDMAN_SYSTEM, context)
        log(f"Claude-analyse modtaget ({len(analysis)} tegn)")
    except Exception as e:
        log(f"⚠ Claude API fejl: {e} — fortsætter uden analyse")
        analysis = f"(Analyse ikke tilgængelig: {e})"
    actions = _extract_actions(analysis)

    now = datetime.now()
    properties = {
        "Måned":         {"date":   {"start": now.strftime("%Y-%m-01")}},
        "Indkomst":      {"number": round(income, 0)},
        "Udgifter":      {"number": round(abs(expense), 0)},
        "Opsparingsrate":{"number": savings_rate},
        "Budget-status": {"select": {"name": budget_status}},
        "Claude-analyse":{"rich_text": _rich_text(analysis)},
        "Handlinger":    {"rich_text": _rich_text(actions)},
    }

    # Investment figures — portfolio YTD return (%)
    if portfolio and portfolio.get("total_return_pct") is not None:
        properties["Afkast YTD"] = {"number": portfolio["total_return_pct"]}

    # Portfolio value in DKK — from manually entered profile.assets.investments_dkk
    inv_dkk = (profile.get("assets") or {}).get("investments_dkk")
    if inv_dkk:
        properties["Porteføljeværdi"] = {"number": int(inv_dkk)}

    notion_key = os.getenv("NOTION_INTEGRATION_KEY")
    db_id      = os.getenv("NOTION_DB_ID")
    if not notion_key or not db_id:
        raise RuntimeError("NOTION_INTEGRATION_KEY og NOTION_DB_ID skal sættes i .env")

    push_to_notion(properties, db_id, notion_key, dry_run=dry_run)

    # Save analysis locally too
    rpath = REPORTS / f"notion_monthly_{now.strftime('%Y%m')}.md"
    rpath.write_text(
        f"# Notion Monthly Sync — {now.strftime('%B %Y')}\n"
        f"Genereret: {now.strftime('%d/%m/%Y %H:%M')}\n\n"
        f"## Goldman Sachs Analyse\n{analysis}\n\n"
        f"## Handlinger\n{actions if actions else '(ingen A1/A2/A3-linjer fundet)'}",
        encoding="utf-8",
    )
    log(f"Analyse gemt lokalt: {rpath.name}")


def sync_weekly(df, profile: dict, portfolio: dict, dry_run: bool = False):
    import pandas as pd
    log("Bygger ugentlig Notion-side...")

    now  = datetime.now()
    real = df[~df["reserveret"]] if "reserveret" in df.columns else df
    week_start = pd.Timestamp.now() - pd.Timedelta(days=7)
    week_df = real[real["dato"] >= week_start]
    income  = float(week_df[week_df["beløb"] > 0]["beløb"].sum())
    expense = float(week_df[week_df["beløb"] < 0]["beløb"].sum())

    log("Kalder Claude API (ugentlig kontekst — seneste 8 dage)...")
    try:
        context  = _build_redacted_context(df, profile, portfolio, days=8)
        analysis = ask_claude(WEEKLY_PROMPT, GOLDMAN_SYSTEM, context)
        log(f"Claude-analyse modtaget ({len(analysis)} tegn)")
    except Exception as e:
        log(f"⚠ Claude API fejl: {e} — fortsætter uden analyse")
        analysis = f"(Analyse ikke tilgængelig: {e})"
    actions = _extract_actions(analysis)

    db_id      = os.getenv("NOTION_WEEKLY_DB_ID") or os.getenv("NOTION_DB_ID")
    notion_key = os.getenv("NOTION_INTEGRATION_KEY")
    if not notion_key or not db_id:
        raise RuntimeError("NOTION_INTEGRATION_KEY og NOTION_DB_ID skal sættes i .env")

    properties = {
        "Måned":         {"date":   {"start": now.strftime("%Y-%m-%d")}},
        "Indkomst":      {"number": round(income, 0)},
        "Udgifter":      {"number": round(abs(expense), 0)},
        "Budget-status": {"select": {"name": _budget_status(df, profile)}},
        "Claude-analyse":{"rich_text": _rich_text(analysis)},
        "Handlinger":    {"rich_text": _rich_text(actions)},
    }

    push_to_notion(properties, db_id, notion_key, dry_run=dry_run)

    rpath = REPORTS / f"notion_weekly_{now.strftime('%Y_W%V')}.md"
    rpath.write_text(
        f"# Notion Weekly Sync — uge {now.isocalendar()[1]}, {now.year}\n"
        f"Genereret: {now.strftime('%d/%m/%Y %H:%M')}\n\n"
        f"## Goldman Sachs Analyse\n{analysis}\n\n"
        f"## Handlinger\n{actions if actions else '(ingen A1/A2/A3-linjer fundet)'}",
        encoding="utf-8",
    )
    log(f"Analyse gemt lokalt: {rpath.name}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Levi → Notion sync: push finansielle data + Claude-analyse til Notion"
    )
    parser.add_argument(
        "--type", choices=["monthly", "weekly"], default="monthly",
        help="Synktype (default: monthly)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Vis hvad der ville blive sendt til Notion — ingen faktisk API-kald"
    )
    args = parser.parse_args()

    profile   = load_profile()
    portfolio = load_portfolio()

    df = load_all_processed(PROCESSED)
    if df is None or len(df) == 0:
        log("FEJL: Ingen behandlede data. Upload filer til data/processed/ først.")
        sys.exit(1)

    cat_data = load_categories(CONFIG_DIR)
    df = recategorize(df, cat_data["rules"], cat_data.get("overrides", {}))

    real = df[~df["reserveret"]] if "reserveret" in df.columns else df
    log(
        f"Data: {len(real)} bogførte posteringer "
        f"fra {real['dato'].min().strftime('%d/%m/%Y')} "
        f"til {real['dato'].max().strftime('%d/%m/%Y')}"
    )

    if args.type == "monthly":
        sync_monthly(df, profile, portfolio, dry_run=args.dry_run)
    else:
        sync_weekly(df, profile, portfolio, dry_run=args.dry_run)

    log("Færdig.")


if __name__ == "__main__":
    main()
