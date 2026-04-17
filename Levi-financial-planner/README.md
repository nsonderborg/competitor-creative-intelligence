# Nordea Finansiel Cockpit

> **Claude Code handoff document.** This README is written so Claude Code can clone this repo, understand the full system, generate test data, run all components, and verify correctness — without access to real bank data.

---

## What this is

A 100% local AI-powered personal finance dashboard for Nordea bank data. No cloud. No API keys. Data never leaves the machine. Two entry points:

- `app.py` — Streamlit web dashboard (upload files, chat with AI, view charts)
- `generate_report.py` — CLI script for cron-scheduled reports

AI inference runs via [Ollama](https://ollama.com) (local LLM server). The app works without Ollama running — it just degrades gracefully on the AI chat features.

---

## Repository layout

```
nordea_suite/
├── app.py                  ← Streamlit dashboard (main entry point)
├── generate_report.py      ← Cron CLI (shares parser logic with app.py)
├── README.md               ← This file
├── data/
│   ├── inbox/              ← Drop new files here; scan moves them to processed/
│   ├── processed/          ← Parsed and deduplicated source files (do not edit)
│   └── reports/            ← AI-generated .md reports written here
└── config/
    └── profile.json        ← User financial profile (created on first save)
```

All directories are created automatically on first run. Nothing breaks if they are empty.

---

## Input data schema

The app accepts two file formats, both describing the same schema.

### Format A — Apple Numbers (.numbers)

Exported directly from the Numbers mockup. The parser uses `numbers-parser` to read the first sheet, first table. Headers are in row 0.

### Format B — CSV (.csv or .txt)

Semicolon-separated (`;`), Danish encoding (latin-1 or UTF-8). Exported from Nordea Netbank via the CSV button on the Transactions page.

### Canonical column names (both formats)

| Raw header (Nordea) | Internal name | Type | Notes |
|---------------------|--------------|------|-------|
| `Bogføringsdato` | `dato` | date | Format `YYYY/MM/DD` or `YYYY-MM-DD`. The literal string `"Reserveret"` marks a pending transaction not yet booked. |
| `Beløb` | `beløb` | float | Danish number format: thousands separator `.`, decimal separator `,`. Negative = debit (money out). Positive = credit (money in). |
| `Afsender` | `afsender` | str | Populated when money is received (sender's name/account). Empty on debits. |
| `Modtager` | `modtager` | str | Populated when money is sent (recipient's name/account). Empty on credits. |
| `Navn` | `navn` | str | Merchant or counterparty display name. Primary categorisation signal. |
| `Beskrivelse` | `beskrivelse` | str | Transaction description. Often same as Navn. Secondary categorisation signal. |
| `Saldo` | `saldo` | float | Running account balance after transaction. Same Danish number format as Beløb. |
| `Valuta` | `valuta` | str | Always `DKK` in practice. |
| `Afstemt` | `afstemt` | str | Reconciliation flag. **Not populated in the observation period.** Always empty/null in current data — do not rely on it. |

### Derived columns (added by the parser)

| Column | Values | Description |
|--------|--------|-------------|
| `reserveret` | bool | True when `Bogføringsdato == "Reserveret"` |
| `type` | `"Indkomst"` / `"Udgift"` | Derived from sign of `beløb` |
| `label` | str | Best display name: `navn` → `beskrivelse` → `modtager`/`afsender` |
| `kategori` | str | Rule-based category from keyword matching on `navn + beskrivelse + modtager + afsender` |

### Edge cases the parser must handle

1. **Reserveret rows** — `Bogføringsdato` = literal string `"Reserveret"`, `Beløb` is NaN (amount not yet confirmed). Tag with `reserveret=True`, set `dato=NaT`, exclude from all financial calculations but keep in dataframe for display.
2. **Trailing empty column** — the Numbers export has an unnamed 10th column (`col_9`). Ignore it.
3. **Danish number formatting** — `1.234,56` must parse to `1234.56`. The cleaner strips `.` (thousands) then replaces `,` with `.` (decimal).
4. **Multiple files** — processed/ may contain multiple files covering overlapping periods. Deduplication key is `(dato, beløb, label)`.
5. **Encoding** — try `utf-8` first, then `latin-1`, `cp1252`, `iso-8859-1`. Most Nordea exports are latin-1.
6. **Afstemt column** — always null in current data. Parser must not fail if it is missing entirely.

---

## Generating synthetic test data

Claude Code should generate a synthetic `.numbers`-compatible CSV for testing without real bank data. Create `data/inbox/test_data.csv` with this structure:

```python
# generate_test_data.py — run this to create synthetic test data
import csv
import random
from datetime import date, timedelta
from pathlib import Path

Path("data/inbox").mkdir(parents=True, exist_ok=True)

merchants = [
    ("REMA 1000 AMAGER", "Dagligvarer", -350),
    ("DSB", "Transport", -98),
    ("Netflix", "Abonnementer", -109),
    ("Spotify", "Abonnementer", -109),
    ("FLEXII", "Abonnementer", -199),     # this one also appears as Reserveret
    ("Vinted", "Shopping", -0),           # Vinted can be income (selling) or expense
    ("ROEDE KORS BUTIK", "Shopping", -85),
    ("TIPSTER.DK", "Shopping", -199),
    ("Zone Fitness", "Sundhed & Fitness", -299),
    ("MobilePay", "MobilePay", -500),
    ("Løn Kereby Aps", "Løn & Indkomst", 35000),
    ("Netto Amager", "Dagligvarer", -220),
    ("Starbucks", "Restaurant & Café", -65),
    ("Uber", "Transport", -145),
    ("Amazon", "Shopping", -399),
]

rows = []
# Header
rows.append(["Bogføringsdato", "Beløb", "Afsender", "Modtager", "Navn", "Beskrivelse", "Saldo", "Valuta", "Afstemt", ""])

# One Reserveret row
rows.append(["Reserveret", "", "", "", "", "FLEXII", "", "DKK", "", ""])

# ~50 transactions from 2026-02-27 to today
saldo = 42000.0
start = date(2026, 2, 27)
end   = date(2026, 4, 17)
delta = (end - start).days

for i in range(50):
    d = start + timedelta(days=random.randint(0, delta))
    navn, _, base_amount = random.choice(merchants)
    # Randomise amount slightly
    amount = round(base_amount * random.uniform(0.8, 1.2), 2)
    saldo  = round(saldo + amount, 2)
    afsender = "Nikolas Nogueira" if amount > 0 else ""
    modtager = navn if amount < 0 else ""
    # Format as Danish: 1234.56 → "1.234,56"
    def fmt(n):
        return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    rows.append([
        d.strftime("%Y/%m/%d"),
        fmt(amount),
        afsender,
        modtager,
        navn,
        navn,
        fmt(saldo),
        "DKK",
        "",
        ""
    ])

with open("data/inbox/test_data.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f, delimiter=";")
    writer.writerows(rows)

print(f"Written {len(rows)-2} transactions + 1 Reserveret row to data/inbox/test_data.csv")
```

Run with: `python generate_test_data.py`

---

## Installation

```bash
# Requires Python 3.11+ (for the X | Y union type syntax in type hints)
python3 --version

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate          # macOS/Linux
# venv\Scripts\activate           # Windows

# Install all dependencies
pip install streamlit pandas requests numbers-parser

# Verify imports work
python3 -c "import streamlit, pandas, requests; from numbers_parser import Document; print('OK')"
```

### Ollama (required for AI features, optional for testing the parser/dashboard)

```bash
# Install Ollama (macOS)
brew install ollama
# or: curl -fsSL https://ollama.com/install.sh | sh

# Start server (keep this terminal open or run as background service)
ollama serve

# Pull a model — qwen2.5:7b is recommended for Danish + numbers
ollama pull qwen2.5:7b

# Verify
curl http://localhost:11434/api/tags
```

The dashboard and CLI degrade gracefully if Ollama is not running — the parser, charts, and transaction table work without it. Only the AI Chat tab and report generation require it.

---

## Running the app

```bash
# Activate venv first
source venv/bin/activate

# Start dashboard
streamlit run app.py
# Opens at http://localhost:8501

# Run CLI report generator
python generate_report.py --type scan      # move inbox files to processed/
python generate_report.py --type monthly   # generate monthly .md report
python generate_report.py --type weekly    # generate weekly .md report
python generate_report.py --type all       # scan + weekly + monthly
python generate_report.py --model qwen2.5:7b --type monthly  # specify model explicitly
```

---

## Acceptance criteria for Claude Code

When testing, verify these behaviours:

### Parser
- [ ] `parse_any("data/inbox/test_data.csv", "test_data.csv")` returns a DataFrame with columns: `dato`, `beløb`, `afsender`, `modtager`, `navn`, `beskrivelse`, `saldo`, `valuta`, `afstemt`, `reserveret`, `type`, `label`, `kategori`
- [ ] The `Reserveret` row has `reserveret=True` and `dato=NaT`
- [ ] All non-reserved rows have `dato` as proper `datetime64`
- [ ] `beløb` is `float64`, correctly signed (negative for debits)
- [ ] `type` == `"Indkomst"` for positive beløb, `"Udgift"` for negative
- [ ] `kategori` is populated for known merchants (e.g. "Netflix" → "Abonnementer", "REMA 1000" → "Dagligvarer")
- [ ] `label` is non-null for all rows
- [ ] Danish amounts like `"1.234,56"` parse to `1234.56`
- [ ] Uploading the same file twice does not double-count (deduplication on `dato + beløb + label`)

### Dashboard (manual verification)
- [ ] Uploading `test_data.csv` via the file uploader shows a success message with correct transaction count
- [ ] Dashboard tab shows 5 metric cards with valid numbers (no NaN, no divide-by-zero)
- [ ] Reserveret row appears in the info banner, not in financial totals
- [ ] Category bar chart renders without error
- [ ] Transaction tab filter by "Reserveret" shows only the reserved row
- [ ] Transaction tab search for "Netflix" returns only Netflix rows

### CLI
- [ ] `python generate_report.py --type scan` with test_data.csv in inbox/ moves the file to processed/ and logs success
- [ ] `python generate_report.py --type monthly` (with Ollama running) writes a .md file to `data/reports/`
- [ ] `python generate_report.py --type monthly` (without Ollama) exits with a clear error message, not a crash
- [ ] `python generate_report.py --type all` runs scan + weekly + monthly in sequence

### Profile
- [ ] Saving a profile writes `config/profile.json` with correct keys: `age`, `income`, `net_worth`, `family`, `career`, `goals`, `freedom`
- [ ] Profile is loaded and appended to the context string sent to Ollama

---

## Cron setup (macOS)

macOS cron does not inherit your shell environment. Always use absolute paths.

```bash
# Find your venv Python path
which python   # while venv is active — copy this exact path

# Edit crontab
crontab -e
```

Add these lines (replace `/Users/nikolas/projects/nordea_suite` with your actual path):

```cron
# Daily inbox scan — 09:00
0 9 * * * /Users/nikolas/projects/nordea_suite/venv/bin/python /Users/nikolas/projects/nordea_suite/generate_report.py --type scan >> /Users/nikolas/projects/nordea_suite/data/reports/cron.log 2>&1

# Weekly summary — Monday 07:30
30 7 * * 1 /Users/nikolas/projects/nordea_suite/venv/bin/python /Users/nikolas/projects/nordea_suite/generate_report.py --type weekly >> /Users/nikolas/projects/nordea_suite/data/reports/cron.log 2>&1

# Monthly report — 1st of month 08:00
0 8 1 * * /Users/nikolas/projects/nordea_suite/venv/bin/python /Users/nikolas/projects/nordea_suite/generate_report.py --type monthly >> /Users/nikolas/projects/nordea_suite/data/reports/cron.log 2>&1
```

**macOS-specific gotcha:** macOS requires explicit Full Disk Access for cron on Ventura/Sonoma. Go to System Settings → Privacy & Security → Full Disk Access → add `/usr/sbin/cron`.

Test a cron entry manually before relying on the schedule:

```bash
# Simulate exactly what cron would run (no venv activation, no shell aliases)
/Users/nikolas/projects/nordea_suite/venv/bin/python /Users/nikolas/projects/nordea_suite/generate_report.py --type scan
```

---

## Exporting from Nordea Netbank

1. Log in at netbank.nordea.dk
2. Go to **Transaktioner & detaljer** for the account
3. Click the **CSV** button next to Udskriv
4. Save the file to `data/inbox/`
5. Either click "Scan inbox-mappe" in the sidebar, or run `python generate_report.py --type scan`

Repeat for each account separately. The deduplication logic handles overlapping date ranges across multiple files.

The `.numbers` format from the mockup is also accepted directly — drag and drop into the upload widget.

---

## AI personas

### 🔬 Finansanalytiker (default)
System prompt focuses on short-term analysis: identifies overspending, flags anomalies, gives concrete DKK-denominated savings suggestions.

### 🏦 BlackRock Chief Financial Planning Officer
System prompt focuses on decade-scale planning: net worth milestones at age 30/40/50/60/70, financial independence number (using 3.5-4% SWR), investment evolution from aggressive growth to preservation, Danish pension context (folkepension ~14.000 DKK/md from age 67, ATP, arbejdsmarkedspension).

Switch between personas in the sidebar. The BlackRock persona is also used for the Livs-Roadmap tab which generates a full written roadmap saved to `data/reports/`.

---

## Privacy

- All inference runs locally via Ollama — no data leaves the machine
- Streamlit's telemetry can be disabled: add `[browser]\ngatherUsageStats = false` to `~/.streamlit/config.toml`
- All files written to `data/` — nothing in system temp or cloud sync paths
- Verify Ollama is not exposed externally: `curl http://YOUR_LOCAL_IP:11434/api/tags` should fail

---

## Known limitations and future work

- **Single account view** — no multi-account aggregation UI yet (files are merged in the backend but there is no per-account breakdown in the dashboard)
- **No budget targets** — the dashboard shows actuals only; no way to set monthly category budgets and track against them
- **Category editor** — categories are hardcoded keyword lists in both files; a UI to add/edit/reassign categories would be useful
- **Afstemt field** — currently ignored; could be used to mark transactions as reconciled against receipts or invoices
- **`.numbers` write-back** — the app reads `.numbers` files but cannot write back (e.g. to populate the Afstemt column)

---

## Dependency versions (tested)

```
python        >= 3.11
streamlit     >= 1.32
pandas        >= 2.0
requests      >= 2.31
numbers-parser >= 4.2
ollama        >= 0.1.9  (server, not Python package)
```
