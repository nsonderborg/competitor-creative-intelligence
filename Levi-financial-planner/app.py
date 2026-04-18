import streamlit as st
import pandas as pd
import requests
import json
import shutil
from datetime import datetime
from pathlib import Path

from nordea_parser import (
    parse_any, load_all_processed, build_context, build_balance_sheet_context,
    load_categories, save_categories, recategorize,
)

st.set_page_config(page_title="Finansiel Cockpit", page_icon="📊", layout="wide")

BASE_DIR     = Path(__file__).parent
INBOX        = BASE_DIR / "data/inbox"
PROCESSED    = BASE_DIR / "data/processed"
REPORTS      = BASE_DIR / "data/reports"
CONFIG_DIR   = BASE_DIR / "config"
PROFILE_FILE = CONFIG_DIR / "profile.json"
OLLAMA_URL   = "http://localhost:11434/api/chat"

BLACKROCK_SYSTEM = """Du er Chief Financial Planning Officer hos BlackRock med 30 års erfaring i livslange finansielle roadmaps.
Tænk i årtier. Brug konkrete DKK-tal. Tilpas til dansk kontekst: folkepension (~14.000 DKK/md fra 67), ATP, arbejdsmarkedspension, KBH-boligmarked.
Prioriter: (1) katastrofebeskyttelse, (2) dyr gæld, (3) formue-opbygning. Svar på dansk."""

ANALYST_SYSTEM = """Du er en skarp finansanalytiker specialiseret i personlig økonomi.
Vær direkte og konkret — brug DKK-tal, ingen floskler. Identificer mønstre, bekymrende udgifter og opsparingsmuligheder. Svar på dansk."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_profile():
    if PROFILE_FILE.exists():
        with open(PROFILE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_profile(p):
    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2, ensure_ascii=False)


def ask_ollama(model, messages, system=None):
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)
    try:
        r = requests.post(OLLAMA_URL, json={"model": model, "messages": msgs, "stream": False}, timeout=180)
        if r.status_code == 200:
            return r.json()["message"]["content"]
        return f"Ollama fejl: {r.status_code}"
    except requests.exceptions.ConnectionError:
        return "❌ Kan ikke forbinde til Ollama. Kør: `ollama serve`"
    except Exception as e:
        return f"Fejl: {e}"


def get_models():
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        if r.status_code == 200:
            return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        pass
    return []


# ── Session init ──────────────────────────────────────────────────────────────
for k, v in [("messages", []), ("persona", "analyst"), ("df", None), ("context", ""), ("cat_data", None)]:
    if k not in st.session_state:
        st.session_state[k] = v

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📊 Finansiel Cockpit")

    models = get_models()
    model  = st.selectbox("Model", models) if models else st.text_input("Model", value="llama3.1")
    if not models:
        st.caption("⚠️ Ollama ikke fundet — kør `ollama serve`")

    st.divider()
    st.session_state.persona = st.radio(
        "AI Persona",
        ["analyst", "blackrock"],
        format_func=lambda x: "🔬 Finansanalytiker" if x == "analyst" else "🏦 BlackRock Rådgiver",
    )

    st.divider()
    st.subheader("📂 Upload fil")
    uploaded = st.file_uploader(
        "Nordea kontoudtog",
        type=["csv", "txt", "numbers"],
        help="Understøtter Apple Numbers (.numbers) og CSV-eksport fra Nordea Netbank"
    )
    if uploaded:
        df_new = parse_any(uploaded, uploaded.name)
        if df_new is not None:
            PROCESSED.mkdir(parents=True, exist_ok=True)
            dest = PROCESSED / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded.name}"
            uploaded.seek(0)
            dest.write_bytes(uploaded.read())
            n_res = df_new["reserveret"].sum() if "reserveret" in df_new.columns else 0
            st.success(f"✓ {len(df_new) - n_res} bogførte + {n_res} reserverede posteringer")
        else:
            st.error("Kunne ikke parse filen — tjek Nordea-formatet")

    st.caption("eller læg filer i:")
    st.code(str(INBOX), language=None)

    if st.button("🔄 Scan inbox-mappe", use_container_width=True):
        moved = 0
        for pattern in ["*.csv", "*.numbers"]:
            for f in INBOX.glob(pattern):
                df_new = parse_any(f, f.name)
                if df_new is not None:
                    shutil.move(str(f), str(PROCESSED / f.name))
                    st.success(f"✓ {f.name}")
                    moved += 1
        if moved == 0:
            st.info("Ingen nye filer i inbox")

    all_df = load_all_processed(PROCESSED)
    if all_df is not None:
        cat_data = load_categories(CONFIG_DIR)
        all_df   = recategorize(all_df, cat_data["rules"], cat_data.get("overrides", {}))
        _profile = load_profile() or {}
        st.session_state.df       = all_df
        st.session_state.cat_data = cat_data
        st.session_state.context  = (
            build_context(all_df, _profile or None, budgets=_profile.get("budgets") or None)
            + build_balance_sheet_context(_profile)
        )
        real    = all_df[~all_df["reserveret"]] if "reserveret" in all_df.columns else all_df
        income  = real[real["beløb"] > 0]["beløb"].sum()
        expense = real[real["beløb"] < 0]["beløb"].sum()
        st.divider()
        st.metric("Indkomst", f"{income:,.0f} DKK")
        st.metric("Udgifter", f"{abs(expense):,.0f} DKK")
        st.metric("Netto",    f"{income+expense:+,.0f} DKK")

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📊 Dashboard", "📋 Transaktioner", "💬 AI Chat", "🗺️ Livs-Roadmap", "⚙️ Profil & Rapporter"]
)
df = st.session_state.df

# ── TAB 1 ─────────────────────────────────────────────────────────────────────
with tab1:
    if df is None:
        st.info("Upload en fil i sidepanelet for at se dit dashboard.")
    else:
        real    = df[~df["reserveret"]] if "reserveret" in df.columns else df
        reserved = df[df["reserveret"]]  if "reserveret" in df.columns else pd.DataFrame()
        income  = real[real["beløb"] > 0]["beløb"].sum()
        expense = real[real["beløb"] < 0]["beløb"].sum()
        net     = income + expense
        months  = real["dato"].dropna().dt.to_period("M").nunique()
        savings_rate = net / income * 100 if income > 0 else 0

        if len(reserved) > 0:
            items = " · ".join(reserved["label"].dropna().tolist())
            st.info(f"⏳ **Reserverede (ikke bogført):** {items}")

        st.subheader("5 tal der fortæller om du er på rette spor")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Gns. opsparing/md",  f"{net/max(months,1):,.0f} DKK")
        c2.metric("Opsparingsrate",      f"{savings_rate:.1f}%",     help="Mål: >20%")
        c3.metric("Udgiftsratio",        f"{abs(expense/income*100):.1f}%", help="Mål: <80%")
        subs_md = abs(real[real["kategori"] == "Abonnementer"]["beløb"].sum() / max(months, 1))
        c4.metric("Abonnementer/md",     f"{subs_md:,.0f} DKK")
        c5.metric("Dataperiode",         f"{months} mdr.")

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Udgifter pr. kategori")
            cat_data = real[real["beløb"] < 0].groupby("kategori")["beløb"].sum().abs().sort_values(ascending=False)
            st.bar_chart(cat_data)
        with col2:
            st.subheader("Månedlig pengestrøm")
            monthly = real.dropna(subset=["dato"]).groupby(
                real.dropna(subset=["dato"])["dato"].dt.to_period("M").astype(str)
            )["beløb"].sum()
            st.bar_chart(monthly)

        # ── Budget progress ───────────────────────────────────────────────────
        budgets = load_profile().get("budgets", {})
        active  = {c: v for c, v in budgets.items() if v > 0}
        if active:
            st.subheader("Budgetstatus denne måned")
            now = pd.Timestamp.now()
            this_month = real[
                real["dato"].dt.year.eq(now.year) & real["dato"].dt.month.eq(now.month)
            ]
            by_cat = this_month[this_month["beløb"] < 0].groupby("kategori")["beløb"].sum().abs()
            for cat, limit in sorted(active.items()):
                spent = float(by_cat.get(cat, 0))
                pct   = spent / limit
                label = f"{cat}: {spent:,.0f} / {limit:,.0f} DKK ({pct*100:.0f}%)"
                if pct > 1.0:
                    st.error(f"Over budget! {label}")
                elif pct > 0.8:
                    st.warning(label)
                else:
                    st.success(label)
                st.progress(min(pct, 1.0))
        else:
            st.caption("💡 Sæt budgetmål under ⚙️ Profil & Rapporter for at se budgetstatus her.")

# ── TAB 2 ─────────────────────────────────────────────────────────────────────
with tab2:
    if df is None:
        st.info("Ingen data endnu.")
    else:
        c1, c2, c3 = st.columns(3)
        ftype   = c1.selectbox("Type", ["Alle", "Indkomst", "Udgift", "Reserveret"])
        fcat    = c2.selectbox("Kategori", ["Alle"] + sorted(df["kategori"].dropna().unique().tolist()))
        fsearch = c3.text_input("Søg (navn/beskrivelse)")

        filt = df.copy()
        if ftype == "Reserveret":
            filt = filt[filt["reserveret"]]
        elif ftype != "Alle":
            filt = filt[~filt["reserveret"]]
            filt = filt[filt["type"] == ftype]
        if fcat != "Alle":
            filt = filt[filt["kategori"] == fcat]
        if fsearch:
            filt = filt[filt["label"].str.contains(fsearch, case=False, na=False)]

        disp = filt[["dato", "label", "afsender", "modtager", "beløb", "saldo", "kategori", "valuta"]].copy()
        disp["dato"]  = disp["dato"].dt.strftime("%d/%m/%Y").fillna("Reserveret")
        disp["beløb"] = disp["beløb"].map(lambda x: f"{x:+,.2f}")
        disp["saldo"] = disp["saldo"].map(lambda x: f"{x:,.2f}" if pd.notna(x) else "")
        disp.columns  = ["Dato", "Navn/Beskrivelse", "Afsender", "Modtager", "Beløb", "Saldo", "Kategori", "Valuta"]
        st.dataframe(disp, use_container_width=True, hide_index=True)

        # ── Category editor ───────────────────────────────────────────────────
        cat_data = st.session_state.cat_data or load_categories(CONFIG_DIR)
        rules    = cat_data["rules"]
        overrides = cat_data.get("overrides", {})
        cat_names = [c for c in rules.keys() if c != "Andet"] + ["Andet"]

        with st.expander("🏷️ Reklassificér & Rediger regler"):
            ed_col1, ed_col2 = st.columns(2)

            # ── Per-transaction override ──────────────────────────────────────
            with ed_col1:
                st.markdown("**Reklassificér transaktion**")
                non_res = filt[~filt["reserveret"]] if "reserveret" in filt.columns else filt
                if non_res.empty:
                    st.caption("Ingen transaktioner at reklassificere.")
                else:
                    tx_labels = [
                        f"{r['dato'].strftime('%d/%m/%y') if pd.notna(r['dato']) else '?'} · "
                        f"{str(r['label'])[:30]} · {r['beløb']:+,.0f} DKK"
                        for _, r in non_res.iterrows()
                    ]
                    tx_idx = st.selectbox("Vælg transaktion", range(len(non_res)), format_func=lambda i: tx_labels[i], key="tx_pick")
                    new_cat = st.selectbox("Ny kategori", cat_names, key="tx_new_cat")
                    if st.button("💾 Gem reklassificering"):
                        row = non_res.iloc[tx_idx]
                        dato = row["dato"].strftime("%Y-%m-%d") if pd.notna(row["dato"]) else "NaT"
                        key  = f"{dato}||{row['beløb']}||{row['label']}"
                        overrides[key] = new_cat
                        save_categories(CONFIG_DIR, {"rules": rules, "overrides": overrides})
                        st.success(f"Gemt: '{row['label']}' → {new_cat}")
                        st.rerun()

            # ── Keyword rule editor ───────────────────────────────────────────
            with ed_col2:
                st.markdown("**Rediger kategori-nøgleord**")
                edit_cat = st.selectbox("Vælg kategori", [c for c in rules.keys() if c != "Andet"], key="rule_cat")
                current_kws = ", ".join(rules.get(edit_cat, []))
                new_kws_raw = st.text_area("Nøgleord (komma-separeret)", value=current_kws, height=100, key="rule_kws")
                if st.button("💾 Gem nøgleord"):
                    rules[edit_cat] = [k.strip().lower() for k in new_kws_raw.split(",") if k.strip()]
                    save_categories(CONFIG_DIR, {"rules": rules, "overrides": overrides})
                    st.success(f"Nøgleord for '{edit_cat}' gemt.")
                    st.rerun()

            st.divider()
            st.markdown("**Tilføj ny kategori**")
            nc1, nc2, nc3 = st.columns([2, 3, 1])
            new_cat_name = nc1.text_input("Navn", key="new_cat_name")
            new_cat_kws  = nc2.text_input("Nøgleord (komma-separeret)", key="new_cat_kws")
            if nc3.button("Opret", key="new_cat_btn"):
                if new_cat_name and new_cat_name not in rules:
                    rules[new_cat_name] = [k.strip().lower() for k in new_cat_kws.split(",") if k.strip()]
                    save_categories(CONFIG_DIR, {"rules": rules, "overrides": overrides})
                    st.success(f"Kategori '{new_cat_name}' oprettet.")
                    st.rerun()
                elif new_cat_name in rules:
                    st.warning(f"'{new_cat_name}' findes allerede.")
                else:
                    st.warning("Angiv et kategorinavn.")

# ── TAB 3 ─────────────────────────────────────────────────────────────────────
with tab3:
    if df is None:
        st.info("Upload data først.")
    else:
        system = BLACKROCK_SYSTEM if st.session_state.persona == "blackrock" else ANALYST_SYSTEM
        label  = "🏦 BlackRock Rådgiver" if st.session_state.persona == "blackrock" else "🔬 Finansanalytiker"
        st.caption(f"Persona: **{label}** · Kører 100% lokalt via Ollama")

        suggestions = {
            "analyst":   ["Hvad bruger jeg for meget på?", "Analysér mine abonnementer", "Hvad er min opsparingsrate?", "Find usædvanlige udgifter"],
            "blackrock": ["Lav mit livslange finansielle roadmap", "Hvad er mine næste 3 finansielle moves?", "Hvornår kan jeg blive finansielt fri?", "Hvad bør min opsparingsrate være?"],
        }
        cols = st.columns(4)
        for i, (col, sug) in enumerate(zip(cols, suggestions[st.session_state.persona])):
            if col.button(sug, key=f"s{i}", use_container_width=True):
                st.session_state.messages.append({"role": "user", "content": sug})

        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

        if prompt := st.chat_input("Stil et spørgsmål om dine finanser..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.write(prompt)

            seed = [
                {"role": "user",      "content": f"Her er mine finansielle data:\n\n{st.session_state.context}"},
                {"role": "assistant", "content": "Forstået. Jeg har læst dine data og er klar til at analysere."},
            ]
            with st.chat_message("assistant"):
                with st.spinner("Analyserer..."):
                    resp = ask_ollama(model, seed + st.session_state.messages, system=system)
                st.write(resp)
            st.session_state.messages.append({"role": "assistant", "content": resp})

        if st.session_state.messages:
            if st.button("Ryd chat"):
                st.session_state.messages = []
                st.rerun()

# ── TAB 4 ─────────────────────────────────────────────────────────────────────
with tab4:
    st.subheader("🗺️ BlackRock Livs-Finansielt Roadmap")
    profile = load_profile()
    if not profile:
        st.warning("Udfyld din profil under ⚙️ Profil & Rapporter for at generere dit personlige roadmap.")
    else:
        st.markdown(f"**Profil:** Alder {profile.get('age','?')} · {profile.get('income','?')} DKK/md · Formue {profile.get('net_worth','?')} DKK")
        if st.button("🏦 Generer mit BlackRock Livs-Roadmap", type="primary"):
            ctx = (build_context(df, profile) if df is not None else "") + build_balance_sheet_context(profile)
            roadmap_prompt = f"""Lav et komplet livslang finansielt roadmap.

{ctx}

10 sektioner:
1. **Nuværende årti — 3 vigtigste moves RIGHT NOW** (konkrete handlinger + DKK-beløb)
2. **Nettoformue-milepæle** ved alder 30, 40, 50, 60, 70
3. **Indkomstvækst-strategi** — karrieretræk og sideindkomst
4. **Opsparingsrate-progression** — hvad nu og hvad på sigt
5. **Investeringsevolution** — aggressiv vækst → indkomst/bevarelse (inkl. dansk pension)
6. **Store køb på tidslinje** — bolig KBH, bil, barns uddannelse
7. **Finansielt uafhængighedsnummer** — præcis porteføljeværdi + alder (SWR 3,5-4%)
8. **Arv og legacy** — testamente, forsikringer, formueoverdragelse
9. **Risikotidslinje** — dominerende risici i hvert årti
10. **Månedlig tracking** — de 5 præcise tal at følge

Brug konkrete DKK-tal. Inkluder folkepension (~14.000 DKK/md fra 67), ATP og arbejdsmarkedspension."""

            with st.spinner("BlackRock-rådgiveren bygger dit roadmap... (1-3 min)"):
                roadmap = ask_ollama(model, [{"role": "user", "content": roadmap_prompt}], system=BLACKROCK_SYSTEM)
            st.markdown(roadmap)
            REPORTS.mkdir(parents=True, exist_ok=True)
            rpath = REPORTS / f"roadmap_{datetime.now().strftime('%Y%m%d')}.md"
            rpath.write_text(f"# BlackRock Livs-Roadmap\nGenereret: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n{roadmap}", encoding="utf-8")
            st.success(f"Gemt: {rpath.name}")

# ── TAB 5 ─────────────────────────────────────────────────────────────────────
with tab5:
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("👤 Din Profil")
        profile   = load_profile()
        age       = st.number_input("Alder", 18, 80, int(profile.get("age", 28)))
        income_p  = st.number_input("Månedlig bruttoindkomst (DKK)", 0, 500000, int(profile.get("income", 45000)), step=1000)
        net_worth = st.number_input("Nettoformue (DKK)", -1000000, 10000000, int(profile.get("net_worth", 0)), step=10000)
        family    = st.text_input("Familieplaner", profile.get("family", ""))
        career    = st.text_area("Karrierebane", profile.get("career", ""), height=80)
        goals     = st.text_area("Finansielle mål", profile.get("goals", ""), height=80)
        freedom   = st.text_input("Hvad er finansiel frihed for dig?", profile.get("freedom", ""))

        st.divider()
        st.markdown("**Budgetmål pr. kategori (DKK/md)**")
        NON_EXPENSE = {"Andet", "Løn & Indkomst", "Overførsler"}
        budget_cats = load_categories(CONFIG_DIR)
        expense_cats = [c for c in budget_cats["rules"] if c not in NON_EXPENSE]
        saved_budgets = profile.get("budgets", {})
        new_budgets = {}
        b_cols = st.columns(2)
        for i, cat in enumerate(expense_cats):
            new_budgets[cat] = b_cols[i % 2].number_input(
                cat, min_value=0, max_value=100_000,
                value=int(saved_budgets.get(cat, 0)), step=100, key=f"budget_{cat}"
            )

        # ── Balance sheet ─────────────────────────────────────────────────────
        with st.expander("💰 Formue & Balance Sheet"):
            saved_assets = profile.get("assets", {})
            st.markdown("**Aktiver**")
            a1, a2 = st.columns(2)
            liq_val  = a1.number_input("Likviditet — kontanter/opsparing (DKK)", 0, 10_000_000, int(saved_assets.get("liquidity_dkk", 0)), step=10_000, key="bs_liq")
            inv_val  = a2.number_input("Investeringer — aktier/fonde (DKK)", 0, 10_000_000, int(saved_assets.get("investments_dkk", 0)), step=10_000, key="bs_inv",
                                       help="Se config/portfolio.json for porteføljeværdi fra Saxo")
            pen_val  = a1.number_input("Pensionsopsparing inkl. arbejdsgiver (DKK)", 0, 10_000_000, int(saved_assets.get("pension_dkk", 0)), step=10_000, key="bs_pen")
            re_val   = a2.number_input("Friværdi — fast ejendom (DKK)", 0, 10_000_000, int(saved_assets.get("real_estate_equity_dkk", 0)), step=10_000, key="bs_re")
            oth_val  = a1.number_input("Øvrige aktiver (DKK)", 0, 10_000_000, int(saved_assets.get("other_dkk", 0)), step=10_000, key="bs_oth")
            new_assets = {"liquidity_dkk": liq_val, "investments_dkk": inv_val,
                          "pension_dkk": pen_val, "real_estate_equity_dkk": re_val, "other_dkk": oth_val}

            st.divider()
            st.markdown("**Passiver**")
            saved_liabs = {d["name"]: d for d in profile.get("liabilities", [])}
            liab_defs = [
                ("Boliglån", True),
                ("Forbrugslån", False),
                ("Kreditkort", False),
                ("Studielån", False),
            ]
            new_liabs = []
            for debt_name, has_years in liab_defs:
                saved = saved_liabs.get(debt_name, {})
                cols = st.columns([3, 2, 2] if has_years else [3, 2, 2])
                bal  = cols[0].number_input(f"{debt_name} — saldo (DKK)", 0, 5_000_000, int(saved.get("balance_dkk", 0)), step=10_000, key=f"liab_bal_{debt_name}")
                rate = cols[1].number_input(f"Rente (%)", 0.0, 30.0, float(saved.get("interest_rate_pct", 0.0)), step=0.1, key=f"liab_rate_{debt_name}")
                if has_years:
                    yrs = cols[2].number_input("År tilbage", 0, 40, int(saved.get("years_remaining", 0)), step=1, key=f"liab_yrs_{debt_name}")
                    new_liabs.append({"name": debt_name, "balance_dkk": bal, "interest_rate_pct": rate, "years_remaining": yrs})
                else:
                    new_liabs.append({"name": debt_name, "balance_dkk": bal, "interest_rate_pct": rate})

            st.divider()
            st.markdown("**Forsikringer**")
            saved_ins = profile.get("insurance", {})
            i1, i2, i3 = st.columns(3)
            life_cov  = i1.number_input("Livsforsikring dækning (DKK)", 0, 10_000_000, int(saved_ins.get("life_dkk", 0)), step=100_000, key="ins_life")
            crit_ill  = i2.checkbox("Kritisk sygdom", value=bool(saved_ins.get("critical_illness", False)), key="ins_crit")
            home_ins  = i3.checkbox("Indboforsikring", value=bool(saved_ins.get("home", False)), key="ins_home")
            new_insurance = {"life_dkk": life_cov, "critical_illness": crit_ill, "home": home_ins}

            st.divider()
            st.markdown("**Pension**")
            saved_pen = profile.get("pension", {})
            p1, p2, p3 = st.columns(3)
            emp_pct   = p1.number_input("Arbejdsgiverbidrag (%/md)", 0.0, 25.0, float(saved_pen.get("employer_contribution_pct", 0.0)), step=0.5, key="pen_emp")
            priv_dkk  = p2.number_input("Privat bidrag (DKK/md)", 0, 20_000, int(saved_pen.get("private_contribution_dkk", 0)), step=100, key="pen_priv")
            ret_age   = p3.number_input("Pensionsalder-mål", 50, 75, int(saved_pen.get("target_retirement_age", 67)), step=1, key="pen_age")
            new_pension = {"employer_contribution_pct": emp_pct, "private_contribution_dkk": priv_dkk, "target_retirement_age": ret_age}

        if st.button("💾 Gem profil", type="primary"):
            save_profile({"age": age, "income": income_p, "net_worth": net_worth,
                          "family": family, "career": career, "goals": goals,
                          "freedom": freedom, "budgets": new_budgets,
                          "assets": new_assets, "liabilities": new_liabs,
                          "insurance": new_insurance, "pension": new_pension})
            st.success("Profil gemt!")

    with col2:
        st.subheader("📋 Rapporter")
        REPORTS.mkdir(parents=True, exist_ok=True)
        rpts = sorted(REPORTS.glob("*.md"), reverse=True)
        if rpts:
            for r in rpts[:8]:
                with st.expander(r.name):
                    st.markdown(r.read_text(encoding="utf-8"))
        else:
            st.info("Ingen rapporter endnu.")

        st.divider()
        st.subheader("🔄 Generer månedlig rapport")
        if df is not None and st.button("Kør månedlig analyse"):
            ctx    = build_context(df, load_profile() or None)
            prompt = f"""Lav en struktureret månedlig finansiel rapport:

{ctx}

## Månedlig Finansiel Rapport — {datetime.now().strftime('%B %Y')}
### Resumé (3 bullet points)
### Pengestrøm
### Kategorianalyse — hvad stikker ud?
### Opsparingsstatus
### Abonnementscheck (list alle med beløb)
### 3 handlinger til næste måned
### På-sporet score: X/10 med begrundelse"""

            with st.spinner("Genererer..."):
                report = ask_ollama(model, [{"role": "user", "content": prompt}], system=ANALYST_SYSTEM)
            rpath = REPORTS / f"rapport_{datetime.now().strftime('%Y%m')}.md"
            rpath.write_text(report, encoding="utf-8")
            st.success(f"Gemt: {rpath.name}")
            st.markdown(report)

        st.divider()
        st.subheader("📁 Database")
        proc = list(PROCESSED.glob("*.csv")) + list(PROCESSED.glob("*.numbers"))
        st.caption(f"{len(proc)} filer indlæst")
        for f in sorted(proc):
            st.caption(f"• {f.name}")
