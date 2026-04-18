"""
nordea_parser.py — shared parser, normaliser, categoriser, and context builder.

Imported by both app.py (Streamlit dashboard) and generate_report.py (CLI cron).
Entry-point-specific constants (BASE_DIR, INBOX, PROCESSED, REPORTS, PROFILE_FILE)
remain in each entry point; pass PROCESSED explicitly to load_all_processed().
"""

import io
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# ── Nordea column schema ──────────────────────────────────────────────────────
NORDEA_COLS = {
    "bogføringsdato": "dato",
    "bogforingsdato": "dato",
    "beløb":          "beløb",
    "belob":          "beløb",
    "amount":         "beløb",
    "afsender":       "afsender",
    "modtager":       "modtager",
    "navn":           "navn",
    "beskrivelse":    "beskrivelse",
    "tekst":          "beskrivelse",   # old CSV format fallback
    "text":           "beskrivelse",
    "saldo":          "saldo",
    "balance":        "saldo",
    "valuta":         "valuta",
    "currency":       "valuta",
    "afstemt":        "afstemt",
}

CATEGORIES = {
    "Dagligvarer":       ["netto", "rema", "bilka", "fakta", "superbrugsen", "lidl", "aldi", "meny", "føtex", "irma", "spar", "coop", "365discount"],
    "Transport":         ["dsb", "metro", "movia", "rejsekort", "taxa", "uber", "circle k", "shell", "q8", "esso", "parking", "parkering", "7-eleven"],
    "Restaurant & Café": ["restaurant", "café", "pizza", "burger", "sushi", "mcdonalds", "kfc", "starbucks", "joe and", "bar ", "pub", "takeaway", "just eat"],
    "Abonnementer":      ["netflix", "spotify", "hbo", "disney", "apple.com", "google", "youtube", "adobe", "dropbox", "github", "openai", "flexii", "tdc", "yousee", "3 dk"],
    "Sundhed & Fitness": ["apotek", "læge", "tandlæge", "fitness", "gym", "crossfit", "thai boxing", "bjj", "zone fitness"],
    "Bolig":             ["husleje", "el ", "vand ", "varme", "internet", "bredbånd", "forsikring", "ejendom", "andels"],
    "Shopping":          ["zalando", "zara", "h&m", "asos", "amazon", "ebay", "magasin", "illum", "vinted", "roede kors", "tipster"],
    "MobilePay":         ["mobilepay", "mp "],
    "Overførsler":       ["overf", "transfer"],
    "Løn & Indkomst":    ["løn", "salary", "dagpenge", "su ", "honorar", "konsulent", "faktura", "a-kasse"],
    "Børn & Familie":    ["legetøj", "kids", "børn", "bleer", "sfo", "vuggestue", "dagpleje"],
    "Andet":             [],
}


# ── Core parser functions ─────────────────────────────────────────────────────

def _clean_amount(val):
    if val is None or str(val).strip() in ("", "None"):
        return None
    s = str(val).strip().replace("\xa0", "").replace(" ", "")
    # Danish format: 1.234,56 → strip thousands dot, replace comma decimal
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _override_key(row) -> str:
    """Build the stable key used for per-transaction category overrides."""
    dato = row.get("dato")
    dato_str = dato.strftime("%Y-%m-%d") if pd.notna(dato) else "NaT"
    return f"{dato_str}||{row.get('beløb', '')}||{row.get('label', '')}"


def categorize(row, rules: dict, overrides: dict | None = None) -> str:
    """Categorise a transaction row. Overrides take precedence over keyword rules."""
    if overrides:
        key = _override_key(row)
        if key in overrides:
            return overrides[key]
    text = " ".join(filter(None, [
        str(row.get("navn") or ""),
        str(row.get("beskrivelse") or ""),
        str(row.get("modtager") or ""),
        str(row.get("afsender") or ""),
    ])).lower()
    for cat, kws in rules.items():
        if cat == "Andet":
            continue
        if any(kw in text for kw in kws):
            return cat
    return "Andet"


def recategorize(df: pd.DataFrame, rules: dict, overrides: dict | None = None) -> pd.DataFrame:
    """Re-apply category rules and overrides to an already-parsed DataFrame."""
    df = df.copy()
    df["kategori"] = df.apply(lambda r: categorize(r, rules, overrides), axis=1)
    return df


def load_categories(config_dir: Path) -> dict:
    """Load category rules and overrides from JSON, seeding from CATEGORIES on first run."""
    cat_file = config_dir / "categories.json"
    if cat_file.exists():
        with open(cat_file, encoding="utf-8") as f:
            return json.load(f)
    return {"rules": dict(CATEGORIES), "overrides": {}}


def save_categories(config_dir: Path, data: dict):
    """Persist category rules and overrides to config/categories.json."""
    cat_file = config_dir / "categories.json"
    config_dir.mkdir(parents=True, exist_ok=True)
    with open(cat_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _normalise(df: pd.DataFrame) -> pd.DataFrame | None:
    """Map raw Nordea columns → canonical schema, handle Reserveret rows, parse types."""
    rename = {}
    for col in df.columns:
        key = str(col).strip().lower()
        if key in NORDEA_COLS:
            rename[col] = NORDEA_COLS[key]
    df = df.rename(columns=rename)

    if "dato" not in df.columns or "beløb" not in df.columns:
        return None

    # Tag "Reserveret" rows (pending transactions — not yet booked)
    df["reserveret"] = df["dato"].astype(str).str.strip().str.lower() == "reserveret"

    # Parse dates on non-reserved rows
    date_str = df.loc[~df["reserveret"], "dato"].astype(str).str.replace("/", "-")
    df.loc[~df["reserveret"], "dato"] = pd.to_datetime(date_str, dayfirst=False, errors="coerce")
    df.loc[df["reserveret"], "dato"] = pd.NaT

    # Parse amounts
    df["beløb"] = df["beløb"].apply(_clean_amount)
    if "saldo" in df.columns:
        df["saldo"] = df["saldo"].apply(_clean_amount)

    # Drop rows without a usable amount
    df = df.dropna(subset=["beløb"])

    # Ensure all schema columns exist
    for col in ["afsender", "modtager", "navn", "beskrivelse", "valuta", "afstemt", "saldo"]:
        if col not in df.columns:
            df[col] = None

    # Direction
    df["type"] = df["beløb"].apply(lambda x: "Indkomst" if x > 0 else "Udgift")

    # Best display label: Navn > Beskrivelse > Modtager/Afsender
    def best_label(r):
        return (r.get("navn") or r.get("beskrivelse") or
                (r.get("modtager") if r["type"] == "Udgift" else r.get("afsender")) or "–")
    df["label"] = df.apply(best_label, axis=1)

    # Categorise using defaults — callers can recategorize() with custom rules afterwards
    df["kategori"] = df.apply(lambda r: categorize(r, CATEGORIES), axis=1)

    return df.sort_values("dato", ascending=False, na_position="first").reset_index(drop=True)


def parse_numbers_file(path) -> pd.DataFrame | None:
    try:
        from numbers_parser import Document
    except ImportError:
        subprocess.run(["pip", "install", "numbers-parser", "--break-system-packages", "-q"], check=True)
        from numbers_parser import Document

    doc   = Document(str(path))
    sheet = doc.sheets[0]
    table = sheet.tables[0]

    rows = [[cell.value for cell in row] for row in table.iter_rows()]
    if not rows:
        return None

    headers = [str(h).strip() if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
    records = [dict(zip(headers, row)) for row in rows[1:] if any(v is not None for v in row)]

    return _normalise(pd.DataFrame(records)) if records else None


def parse_csv_file(path_or_buffer) -> pd.DataFrame | None:
    """Parse a Nordea CSV. Accepts a file path (Path/str) or a file-like object (Streamlit UploadedFile)."""
    if hasattr(path_or_buffer, "read"):
        content = path_or_buffer.read()
    else:
        content = Path(path_or_buffer).read_bytes()

    text = None
    for enc in ["utf-8", "latin-1", "cp1252", "iso-8859-1"]:
        try:
            text = content.decode(enc)
            break
        except Exception:
            continue
    if text is None:
        return None

    lines = text.strip().split("\n")
    sep   = ";" if lines and lines[0].count(";") >= lines[0].count(",") else ","
    df    = pd.read_csv(io.StringIO(text), sep=sep, encoding_errors="replace")
    df.columns = df.columns.str.strip()
    return _normalise(df)


def _save_tmp(buffer, filename) -> Path:
    tmp = Path("/tmp") / filename
    buffer.seek(0)
    tmp.write_bytes(buffer.read())
    return tmp


def parse_any(path_or_buffer, filename: str) -> pd.DataFrame | None:
    """Auto-detect file format and parse. filename is used for extension detection."""
    ext = Path(filename).suffix.lower()
    if ext == ".numbers":
        p = path_or_buffer if not hasattr(path_or_buffer, "read") else _save_tmp(path_or_buffer, filename)
        return parse_numbers_file(p)
    elif ext in (".csv", ".txt"):
        return parse_csv_file(path_or_buffer)
    return None


def load_all_processed(processed_dir: Path) -> pd.DataFrame | None:
    """Load and deduplicate all processed files from processed_dir."""
    frames = []
    for pattern in ["*.csv", "*.numbers"]:
        for f in sorted(processed_dir.glob(pattern)):
            df = parse_any(f, f.name)
            if df is not None:
                frames.append(df)
    if not frames:
        return None
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["dato", "beløb", "label"])
    return combined.sort_values("dato", ascending=False, na_position="first")


# ── AI context builder ────────────────────────────────────────────────────────

def build_context(df: pd.DataFrame, profile: dict | None = None, days: int | None = None, budgets: dict | None = None) -> str:
    """Build a financial summary string for Ollama context.

    Args:
        df:      Full transaction DataFrame (including reserveret rows).
        profile: Optional user profile dict from config/profile.json.
        days:    If set, filter to only the last N days (used by CLI reports).
        budgets: Optional monthly budget limits per category {cat: dkk}.
    """
    if days:
        cutoff = datetime.now() - timedelta(days=days)
        df = df[df["dato"].isna() | (df["dato"] >= pd.Timestamp(cutoff))]

    real     = df[~df["reserveret"]] if "reserveret" in df.columns else df
    reserved = df[df["reserveret"]]  if "reserveret" in df.columns else pd.DataFrame()

    if len(real) == 0:
        return "Ingen bogførte transaktioner i perioden."

    income  = real[real["beløb"] > 0]["beløb"].sum()
    expense = real[real["beløb"] < 0]["beløb"].sum()
    net     = income + expense
    months  = real["dato"].dropna().dt.to_period("M").nunique()

    by_cat  = real[real["beløb"] < 0].groupby("kategori")["beløb"].sum().sort_values()
    cat_str = "\n".join([f"  {c}: {abs(v):,.0f} DKK" for c, v in by_cat.items()])

    top_exp = real[real["beløb"] < 0].nsmallest(10, "beløb")
    top_str = "\n".join([
        f"  {r['dato'].strftime('%d/%m/%y') if pd.notna(r['dato']) else 'Reserv.'}"
        f" | {str(r['label'])[:38]:<38} | {r['beløb']:>10,.0f} DKK | {r['kategori']}"
        for _, r in top_exp.iterrows()
    ])

    res_str = ""
    if len(reserved) > 0:
        res_str = "\nRESERVEREDE (ikke bogført endnu):\n"
        for _, r in reserved.iterrows():
            res_str += (
                f"  {r['label']}: {r['beløb']:+,.0f} DKK\n"
                if pd.notna(r.get("beløb"))
                else f"  {r['label']}: beløb mangler\n"
            )

    ctx = f"""=== FINANSIEL DATA ===
Periode: {real['dato'].min().strftime('%d/%m/%Y')} — {real['dato'].max().strftime('%d/%m/%Y')}
Bogførte transaktioner: {len(real)} | Reserverede: {len(reserved)} | Måneder: {months}

PENGESTRØM:
  Indkomst:         {income:>12,.0f} DKK
  Udgifter:         {abs(expense):>12,.0f} DKK
  Netto:            {net:>+12,.0f} DKK
  Gns. pr. måned:   {net/max(months,1):>+12,.0f} DKK
  Opsparingsrate:   {net/income*100:.1f}%
{res_str}
UDGIFTER PR. KATEGORI:
{cat_str}

TOP 10 UDGIFTER:
{top_str}
"""
    if budgets:
        current_month = real[
            real["dato"].dt.year.eq(datetime.now().year) &
            real["dato"].dt.month.eq(datetime.now().month)
        ]
        by_cat_month = current_month[current_month["beløb"] < 0].groupby("kategori")["beløb"].sum().abs()
        budget_lines = []
        for cat, limit in sorted(budgets.items()):
            if limit <= 0:
                continue
            spent = by_cat_month.get(cat, 0)
            pct   = spent / limit * 100
            budget_lines.append(f"  {cat}: {spent:,.0f} / {limit:,.0f} DKK ({pct:.0f}%)")
        if budget_lines:
            ctx += "\nBUDGETMÅL (denne måned):\n" + "\n".join(budget_lines) + "\n"

    if profile:
        ctx += f"""
=== BRUGERPROFIL ===
Alder: {profile.get('age','?')} | Indkomst: {profile.get('income','?')} DKK/md brutto | Formue: {profile.get('net_worth','?')} DKK
Familie: {profile.get('family','')} | Karriere: {profile.get('career','')}
Mål: {profile.get('goals','')} | Finansiel frihed: {profile.get('freedom','')}
"""
    return ctx
