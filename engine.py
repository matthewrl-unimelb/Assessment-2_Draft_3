"""
engine.py - every calculation and every met / not-met decision lives here.

Design rule for the whole app:  AI READS AND EXPLAINS - THIS FILE CALCULATES AND DECIDES.
Nothing in this file calls the AI. Each rule is plain if-then logic (Lab 1 style), with the
regulation it comes from written next to it so a lawyer can check it.

Money: the Fed's FR Y-9C figures are in THOUSANDS of US dollars, and this file keeps thousands.
`bn()` turns a value into "$12.3bn" for display. Canadian (OSFI) figures are in C$ millions.

Simplifications (also stated on screen):
  * the combined bank is the two banks ADDED TOGETHER - no purchase premium or goodwill;
  * size categories use asset size only.
"""

import csv
import datetime
import io
import json
import os
import re

# ======================================================================================
# 1. READING FR Y-9C REPORTS
#    Each figure is identified by its MDRM code - the Fed's ID for one line of the report.
# ======================================================================================
FIELDS = {
    # our name          (MDRM code(s),        plain-English label,                   Y-9C location)
    "total_assets":      (["BHCK2170"],        "Total assets",                         "Sch. HC, item 12"),
    "avg_assets_lev":    (["BHCAA224"],        "Average assets for leverage ratio",    "Sch. HC-R Pt I"),
    "cet1":              (["BHCAP859"],        "Common equity tier 1 (CET1) capital",  "Sch. HC-R Pt I"),
    "tier1":             (["BHCA8274"],        "Tier 1 capital",                       "Sch. HC-R Pt I"),
    "tier2":             (["BHCA5311"],        "Tier 2 capital",                       "Sch. HC-R Pt I"),
    "total_capital":     (["BHCA3792"],        "Total capital",                        "Sch. HC-R Pt I"),
    "rwa":               (["BHCAA223"],        "Risk-weighted assets",                 "Sch. HC-R Pt II"),
    "cet1_ratio":        (["BHCAP793"],        "CET1 ratio (reported, %)",             "Sch. HC-R Pt I"),
    "tier1_ratio":       (["BHCA7206"],        "Tier 1 ratio (reported, %)",           "Sch. HC-R Pt I"),
    "total_ratio":       (["BHCA7205"],        "Total capital ratio (reported, %)",    "Sch. HC-R Pt I"),
    "leverage_ratio":    (["BHCA7204"],        "Leverage ratio (reported, %)",         "Sch. HC-R Pt I"),
    "slr":               (["BHCAH036"],        "Supplementary leverage ratio (reported, %)", "Sch. HC-R Pt I"),
    "total_liabilities": (["BHCK2948"],        "Total liabilities",                    "Sch. HC, item 21"),
    "deposits":          (["BHDM6631", "BHDM6636", "BHFN6631", "BHFN6636"], "Total deposits", "Sch. HC, item 13"),
}
RATIO_FIELDS = {"cet1_ratio", "tier1_ratio", "total_ratio", "leverage_ratio", "slr"}

# The lines of the filing the AI reads (Schedule HC, HC-M goodwill, HC-R Part I) - built once by build_y9c_template.py
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "library", "y9c_template.json")) as _fh:
    Y9C_TEMPLATE = json.load(_fh)
TEMPLATE_CODES = {l["mdrm"] for l in Y9C_TEMPLATE["lines"]}
PERCENT_CODES = {"BHCAP793", "BHCA7206", "BHCA7205", "BHCA7204", "BHCAH036", "BHCAH311"}


def _num(value):
    try:
        return float(str(value).replace(",", "")) if value not in ("", None) else None
    except ValueError:
        return None


def _bank_from(get, rssd, name, city, state, quarter):
    bank = {"rssd": rssd, "name": name, "city": city, "state": state, "quarter": quarter}
    for key, (codes, _label, _loc) in FIELDS.items():
        present = [v for v in (_num(get(c)) for c in codes) if v is not None]
        bank[key] = sum(present) if present else None
    # every line of the filing the AI will read, exactly as filed (for the AI's reading, and to check it)
    bank["raw"] = {c: v for c, v in ((c, _num(get(c))) for c in TEMPLATE_CODES) if v is not None}
    return bank


def parse_y9c_bulk(file_bytes):
    """The Fed's bulk download (caret '^' separated .txt). Returns (quarter, {rssd: bank})."""
    reader = csv.reader(io.StringIO(file_bytes.decode("latin-1")), delimiter="^")
    header = next(reader)
    banks, quarter = {}, None
    for row in reader:
        if len(row) < 10:
            continue
        rec = dict(zip(header, row))
        quarter = rec.get("RSSD9999", quarter)
        bank = _bank_from(rec.get, rec.get("RSSD9001"), (rec.get("RSSD9017") or "").strip(),
                          (rec.get("RSSD9130") or "").strip().title(), (rec.get("RSSD9200") or "").strip(), rec.get("RSSD9999"))
        if bank["total_assets"]:          # skip mid-tier entities with no balance sheet
            banks[bank["rssd"]] = bank
    return quarter, banks


def parse_y9c_pdf(file_bytes):
    """One FR Y-9C report saved as a PDF from the Fed's National Information Center.
    These PDFs are fillable forms: each number sits in a field named after its MDRM code
    (e.g. 'BHCK2170'), so figures are read exactly - no AI, no guessing.
    Returns (quarter, {rssd: bank}), or (None, {}) if the PDF is not an FR Y-9C."""
    from pypdf import PdfReader
    vals = {}
    for full, f in (PdfReader(io.BytesIO(file_bytes)).get_fields() or {}).items():
        v = f.get("/V")
        if v in (None, "") or str(v).strip() in ("", "/Off"):
            continue
        vals.setdefault(re.sub(r"\[\d+\]$", "", full.split(".")[-1]), str(v).strip())
    if "BHCK2170" not in vals:
        return None, {}
    try:
        quarter = datetime.datetime.strptime(vals.get("TEXT9999", ""), "%B %d, %Y").strftime("%Y%m%d")
    except ValueError:
        quarter = None
    bank = _bank_from(vals.get, vals.get("ID_RSSD", "pdf"), vals.get("NM_LGL", "Unnamed holding company").strip(),
                      vals.get("CITY", "").title(), vals.get("STATE_ABBR_NM", ""), quarter)
    return quarter, {bank["rssd"]: bank}


def merge_quarters(parsed):
    """[(quarter, {rssd: bank}), ...] -> {rssd: {"latest", "history", "avg_assets", "quarters"}}"""
    merged = {}
    for quarter, banks in sorted(parsed, key=lambda x: x[0] or ""):
        for rssd, bank in banks.items():
            entry = merged.setdefault(rssd, {"history": []})
            if not any(b["quarter"] == bank["quarter"] for b in entry["history"]):
                entry["history"].append(bank)
    for entry in merged.values():
        entry["latest"] = entry["history"][-1]
        assets = [b["total_assets"] for b in entry["history"][-4:] if b["total_assets"]]
        entry["avg_assets"] = sum(assets) / len(assets)
        entry["quarters"] = len(assets)
    return merged


def cross_checks(bank):
    """Data checks: recompute each reported ratio from its parts."""
    checks = []
    for label, num, den, reported in (("CET1 ratio", "cet1", "rwa", "cet1_ratio"), ("Tier 1 ratio", "tier1", "rwa", "tier1_ratio"),
                                      ("Total capital ratio", "total_capital", "rwa", "total_ratio"),
                                      ("Leverage ratio", "tier1", "avg_assets_lev", "leverage_ratio")):
        if None in (bank.get(num), bank.get(den), bank.get(reported)) or not bank.get(den):
            checks.append({"check": label, "ok": None, "result": "missing data"})
            continue
        calc = 100 * bank[num] / bank[den]
        checks.append({"check": label, "ok": abs(calc - bank[reported]) < 0.05,
                       "result": f"{calc:.2f}% recomputed vs {bank[reported]:.2f}% reported"})
    return checks


# --------------------------------------------------------------------------------------
# 1b. THE FILING AS THE AI READS IT, AND THE CODE CHECK OF WHAT THE AI READ
# --------------------------------------------------------------------------------------
def filing_extract(bank):
    """Lay out a bank's FR Y-9C as 'item, caption [code] = value' lines (only lines with a value).
    Works the same for a PDF filing and for the Fed's bulk .txt file."""
    raw = bank.get("raw") or {}
    out = [f"FILING: {bank.get('name')} - FR Y-9C as of {bank.get('quarter')}. Dollar amounts in thousands of US$; "
           f"lines marked 'percentage' are percentages."]
    current = None
    for l in Y9C_TEMPLATE["lines"]:
        v = raw.get(l["mdrm"])
        if v is None:
            continue
        if l["schedule"] != current:
            current = l["schedule"]
            out.append("\n" + Y9C_TEMPLATE["schedules"][current])
        shown = f"{v:.4f}" if l["mdrm"] in PERCENT_CODES else (f"{v:.0f}" if l["mdrm"] == "BHCAP838" else f"{v:,.0f}")
        cap = (l["parent"] + " - " if l["parent"] else "") + l["caption"]
        out.append(f"  {l['item']}. {cap} [{l['mdrm']}] = {shown}")
    return "\n".join(out)


# What the AI is asked to find in the filing - described by MEANING, not by line number - and the exact
# code(s) the app uses to check each answer.
READ_TARGETS = {
    "total_assets":      ("Total assets", ["BHCK2170"]),
    "total_liabilities": ("Total liabilities", ["BHCK2948"]),
    "deposit_lines":     ("Every deposit line reported (domestic and foreign; non-interest- and interest-bearing) - as a LIST of values",
                          ["BHDM6631", "BHDM6636", "BHFN6631", "BHFN6636"]),
    "total_equity":      ("Total holding company equity capital", ["BHCK3210"]),
    "aoci":              ("Accumulated other comprehensive income (unrealised gains/losses), from the balance sheet", ["BHCKB530"]),
    "goodwill":          ("Goodwill", ["BHCK3163"]),
    "securities_afs":    ("Available-for-sale debt securities", ["BHCK1773"]),
    "securities_htm":    ("Held-to-maturity securities", ["BHCKJJ34"]),
    "loans":             ("Loans and leases held for investment (before the allowance)", ["BHCKB528"]),
    "allowance":         ("Allowance for credit losses on loans and leases", ["BHCK3123"]),
    "cet1":              ("Common equity tier 1 capital", ["BHCAP859"]),
    "tier1":             ("Tier 1 capital", ["BHCA8274"]),
    "tier2":             ("Tier 2 capital", ["BHCA5311"]),
    "total_capital":     ("Total capital", ["BHCA3792"]),
    "rwa":               ("Total risk-weighted assets", ["BHCAA223"]),
    "avg_assets_lev":    ("Total assets for the leverage ratio", ["BHCAA224"]),
    "cet1_ratio":        ("Common equity tier 1 capital ratio (percentage)", ["BHCAP793"]),
    "tier1_ratio":       ("Tier 1 capital ratio (percentage)", ["BHCA7206"]),
    "total_ratio":       ("Total capital ratio (percentage)", ["BHCA7205"]),
    "leverage_ratio":    ("Leverage ratio (percentage)", ["BHCA7204"]),
    "slr":               ("Supplementary leverage ratio (percentage), if reported", ["BHCAH036"]),
}


def _to_float(v):
    try:
        return float(str(v).replace(",", "").replace("$", "").replace("%", "")) if v not in (None, "", "null") else None
    except ValueError:
        return None


def check_ai_read(ai_read, bank):
    """CODE check of the AI's reading: every figure against the exact value filed under its code,
    then the AI's own figures must reproduce the ratios the bank reported."""
    raw, rows = bank.get("raw") or {}, []
    for key, (label, codes) in READ_TARGETS.items():
        item = ai_read.get(key) if isinstance(ai_read.get(key), dict) else {"value": ai_read.get(key)}
        if key == "deposit_lines":
            vals = item.get("value") if isinstance(item.get("value"), list) else ([item.get("value")] if item.get("value") is not None else [])
            nums = [x for x in (_to_float(v) for v in vals) if x is not None]
            got = sum(nums) if nums else None                     # code adds the lines; the AI never adds
            label = "Total deposits (the app adds the deposit lines the AI found)"
        else:
            got = _to_float(item.get("value"))
        present = [raw[c] for c in codes if c in raw]
        exact = sum(present) if present else None
        pct = key in RATIO_FIELDS
        if exact is None and got is None:
            status = "not_reported"
        elif got is None:
            status = "missed"
        elif exact is None:
            status = "differs"
        else:
            status = "match" if abs(got - exact) <= (0.006 if pct else max(1.0, 0.0005 * abs(exact))) else "differs"
        rows.append({"key": key, "label": label, "ai": got, "exact": exact, "status": status, "pct": pct,
                     "where": str(item.get("line") or ""), "codes": codes})
    figs = {r["key"]: r["ai"] for r in rows}
    figs["deposits"] = figs.pop("deposit_lines", None)
    internal = cross_checks(figs)
    n = {k: sum(1 for r in rows if r["status"] == k) for k in ("match", "differs", "missed", "not_reported")}
    return {"rows": rows, "internal": internal, "counts": n, "checked": n["match"] + n["differs"] + n["missed"],
            "all_ok": n["differs"] == 0 and n["missed"] == 0}


# Balance-sheet lines that are often holdings a bank holding company cannot keep indefinitely (Schedule HC).
HOLDING_SIGNALS = [("BHCK3656", "Direct and indirect investments in real estate ventures", "HC item 9"),
                   ("BHCK2130", "Investments in unconsolidated subsidiaries and associated companies", "HC item 8"),
                   ("BHCKJA22", "Equity securities not held for trading", "HC item 2.c"),
                   ("BHCK2150", "Other real estate owned (e.g. foreclosed property)", "HC item 7")]


def money(thousands):
    """Thousands of $ -> '$705m' below $1bn, else '$1.65bn'."""
    if thousands is None:
        return "n/a"
    return f"${thousands / 1e3:,.0f}m" if abs(thousands) < 1e6 else bn(thousands, 2)


def holding_signals(bank, floor=50_000):
    """The bank's own balance-sheet lines that may need to be sold or conformed - exact from the filing ($50m+)."""
    raw = bank.get("raw") or {}
    return [{"label": label, "item": item, "value": raw[c]} for c, label, item in HOLDING_SIGNALS if (raw.get(c) or 0) >= floor]


def bank_profile(bank):
    """Plain figures for the AI's analyst review - read exactly from the filing (thousands of US$)."""
    raw = bank.get("raw") or {}
    g = lambda c: raw.get(c)
    out = {"Total assets": g("BHCK2170"), "Loans held for investment": g("BHCKB528"), "Allowance for credit losses": g("BHCK3123"),
           "Available-for-sale securities": g("BHCK1773"), "Held-to-maturity securities": g("BHCKJJ34"), "Trading assets": g("BHCK3545"),
           "Total deposits": sum(raw.get(c, 0) for c in ("BHDM6631", "BHDM6636", "BHFN6631", "BHFN6636")) or None,
           "Other borrowed money": g("BHCK3190"), "Total equity": g("BHCK3210"), "AOCI": g("BHCKB530"), "Goodwill": g("BHCK3163"),
           "CET1 capital": g("BHCAP859"), "Risk-weighted assets": g("BHCAA223"), "AOCI opt-out election (1 = opted out)": g("BHCAP838")}
    for c, label, item in HOLDING_SIGNALS:
        out[f"{label} ({item})"] = g(c)
    shares = {}
    ta = g("BHCK2170")
    if ta:
        for k in ("Loans held for investment", "Available-for-sale securities", "Held-to-maturity securities", "Total deposits", "Goodwill"):
            if out.get(k):
                shares[k] = 100 * out[k] / ta
    if g("BHCKB530") is not None and g("BHCAP859"):
        shares["AOCI as % of CET1"] = 100 * g("BHCKB530") / g("BHCAP859")
    if g("BHCK3163") and g("BHCK3210"):
        shares["Goodwill as % of equity"] = 100 * g("BHCK3163") / g("BHCK3210")
    if g("BHCK3123") and g("BHCKB528"):
        shares["Allowance as % of loans"] = 100 * g("BHCK3123") / g("BHCKB528")
    return out, shares


def bn(thousands, dp=1):
    """Thousands of dollars -> '$12.3bn' (or '$1.25tn')."""
    if thousands is None:
        return "n/a"
    sign = "-" if thousands < 0 else ""
    if abs(thousands) >= 1e9:
        return f"{sign}${abs(thousands) / 1e9:,.2f}tn"
    return f"{sign}${abs(thousands) / 1e6:,.{dp}f}bn"


# ======================================================================================
# 2. SIZE CATEGORY  (12 CFR 252.5; 12 CFR 217.2) - by size only, plus a GSIB flag
# ======================================================================================
LINES = {"IV": 100e6, "III": 250e6, "II": 700e6}
CATEGORY_ORDER = ["None", "IV", "III", "II", "I"]
CATEGORY_CITE = "12 CFR 252.5; 12 CFR 217.2"


def category(avg_assets, gsib=False):
    if gsib:
        return "I", "It is a U.S. global systemically important bank (GSIB). Category I is only for GSIBs."
    if avg_assets >= LINES["II"]:
        return "II", f"Average total assets of {bn(avg_assets)} are $700bn or more."
    if avg_assets >= LINES["III"]:
        return "III", f"Average total assets of {bn(avg_assets)} are between $250bn and $700bn."
    if avg_assets >= LINES["IV"]:
        return "IV", f"Average total assets of {bn(avg_assets)} are between $100bn and $250bn."
    return "None", f"Average total assets of {bn(avg_assets)} are below $100bn, so no category applies."


def cat_label(c):
    return "Below $100bn" if c == "None" else f"Category {c}"


def rank(c):
    return CATEGORY_ORDER.index(c)


REQUIREMENTS = [  # what each category switches on, tied to a provision in the library
    ("Annual capital plan (CCAR)", {"None": "No", "IV": "Yes", "III": "Yes", "II": "Yes", "I": "Yes"}, "12 CFR 225.8"),
    ("Stress capital buffer (min 2.5%) replaces the 2.5% conservation buffer",
     {"None": "No", "IV": "Yes", "III": "Yes", "II": "Yes", "I": "Yes"}, "12 CFR 217.11(a); 12 CFR 225.8"),
    ("Supervisory stress test", {"None": "No", "IV": "Every other year", "III": "Annual", "II": "Annual", "I": "Annual"}, "12 CFR 252.44"),
    ("Supplementary leverage ratio (3%)", {"None": "No", "IV": "No", "III": "Yes", "II": "Yes", "I": "Yes (enhanced)"}, "12 CFR 217.10(a)(1)(v)"),
    ("Countercyclical capital buffer", {"None": "No", "IV": "No", "III": "Yes", "II": "Yes", "I": "Yes"}, "12 CFR 217.11(b)"),
    ("Unrealised securities gains/losses (AOCI) count in CET1",
     {"None": "Optional opt-out", "IV": "Optional opt-out", "III": "Optional opt-out", "II": "Yes", "I": "Yes"}, "12 CFR 217.22(b)(2)"),
    ("Liquidity coverage ratio / NSFR", {"None": "No", "IV": "Possibly (reduced)", "III": "Yes (reduced or full)", "II": "Yes (full)", "I": "Yes (full)"},
     "12 CFR 249.30(c)"),
]


# The same seven requirements as questions for the AI to answer from the regulation text (same order as REQUIREMENTS).
REQUIREMENT_QUESTIONS = [
    "Must it develop and submit an annual capital plan to the Fed (12 CFR 225.8)?",
    "Is it subject to a stress capital buffer requirement set through the capital plan rule, in place of the fixed 2.5% capital "
    "conservation buffer?",
    "Is it subject to the Fed's supervisory stress test (12 CFR 252.44)? ('applies' whether annual or every other year)",
    "Must it meet the 3% supplementary leverage ratio minimum (12 CFR 217.10(a)(1)(v))?",
    "Must it calculate and hold a countercyclical capital buffer amount (12 CFR 217.11(b))?",
    "Must unrealised gains and losses on securities (AOCI) be included in its CET1 capital? Answer 'applies' if they MUST be "
    "included, 'optional' if the bank may elect to exclude them (the AOCI opt-out).",
    "Is it subject to the liquidity coverage ratio and net stable funding ratio (Part 249)? Answer 'conditional' if only "
    "above a weighted short-term wholesale funding threshold.",
]


def newly_applying(before, after):
    return [{"Requirement": r, "Before": m[before], "After": m[after], "Source": c}
            for r, m, c in REQUIREMENTS if m[before] != m[after]]


# ======================================================================================
# 3. THE COMBINED BANK (simple addition)
# ======================================================================================
def combine(a, t):
    keys = ("total_assets", "avg_assets_lev", "cet1", "tier1", "tier2", "total_capital", "rwa", "total_liabilities", "deposits")
    c = {k: (a[k] or 0) + (t[k] or 0) for k in keys}
    c["name"] = "Combined bank"
    c["cet1_ratio"] = 100 * c["cet1"] / c["rwa"]
    c["tier1_ratio"] = 100 * c["tier1"] / c["rwa"]
    c["total_ratio"] = 100 * c["total_capital"] / c["rwa"]
    c["leverage_ratio"] = 100 * c["tier1"] / c["avg_assets_lev"]
    if a.get("slr") and t.get("slr"):   # back out each bank's leverage exposure from its reported SLR
        c["slr"] = 100 * c["tier1"] / (a["tier1"] / (a["slr"] / 100) + t["tier1"] / (t["slr"] / 100))
    else:
        c["slr"] = None
    return c


# ======================================================================================
# 4. CAPITAL, LEVERAGE AND LIABILITIES TESTS
# ======================================================================================
CAPITAL_RATIOS = [("cet1_ratio", "CET1 ratio", 4.5), ("tier1_ratio", "Tier 1 ratio", 6.0), ("total_ratio", "Total capital ratio", 8.0)]
BUFFER = 2.5   # capital conservation buffer, or the minimum stress capital buffer for Category IV+


# What each size category must hold for the three risk-based ratios (minimum + the buffer on top).
# Minimums are the same for every bank (12 CFR 217.10(a)); the buffer grows with the category.
CATEGORY_CAPITAL = [
    # (category, who it covers, CET1, Tier 1, Total, the buffer on top of the minimum, source)
    ("None", "Below $100bn", "7.0%", "8.5%", "10.5%",
     "Capital conservation buffer of 2.5%", "12 CFR 217.10(a); 217.11(a)"),
    ("IV", "$100bn – $250bn", "≥ 7.0%", "≥ 8.5%", "≥ 10.5%",
     "Stress capital buffer, set each year from the Fed's stress test — at least 2.5%", "12 CFR 217.11(a); 12 CFR 225.8"),
    ("III", "$250bn – $700bn", "≥ 7.0%", "≥ 8.5%", "≥ 10.5%",
     "Stress capital buffer (at least 2.5%) plus the countercyclical buffer set by the Fed", "12 CFR 217.11(a)–(b); 12 CFR 225.8"),
    ("II", "$700bn or more", "≥ 7.0%", "≥ 8.5%", "≥ 10.5%",
     "Stress capital buffer plus countercyclical buffer; ratios must also be met under the 'advanced approaches'",
     "12 CFR 217.11; 12 CFR 217.100"),
    ("I", "U.S. GSIBs (the largest, systemically important banks)", "≥ 8.0%", "≥ 9.5%", "≥ 11.5%",
     "Stress capital buffer plus countercyclical buffer plus a GSIB surcharge of at least 1.0%; advanced approaches",
     "12 CFR 217.11; 12 CFR 217.403; 12 CFR 217.100"),
]


def judge(value, minimum, with_buffer):
    if value is None:
        return "unknown"
    if value < minimum:
        return "not_met"
    if value < with_buffer:
        return "warning"
    return "met"


def capital_tests(bank):
    return [{"key": k, "test": name, "value": bank.get(k), "minimum": m, "with_buffer": m + BUFFER,
             "status": judge(bank.get(k), m, m + BUFFER), "cite": "12 CFR 217.10(a); 12 CFR 217.11(a)"}
            for k, name, m in CAPITAL_RATIOS]


def leverage_tests(bank, cat):
    rows = [{"key": "leverage_ratio", "test": "Tier 1 leverage ratio", "value": bank.get("leverage_ratio"), "minimum": 4.0,
             "with_buffer": 4.0, "status": judge(bank.get("leverage_ratio"), 4.0, 4.0), "cite": "12 CFR 217.10(a)(1)(iv)"}]
    if cat in ("III", "II", "I"):
        rows.append({"key": "slr", "test": "Supplementary leverage ratio", "value": bank.get("slr"), "minimum": 3.0,
                     "with_buffer": 3.0, "status": judge(bank.get("slr"), 3.0, 3.0), "cite": "12 CFR 217.10(a)(1)(v)"})
    return rows


# What each size category must hold for leverage (Tier 1 capital against assets, ignoring risk).
CATEGORY_LEVERAGE = [
    # (category, who, Tier 1 leverage ratio, supplementary leverage ratio, source)
    ("None", "No category", "4%", "Does not apply", "12 CFR 217.10(a)(1)(iv)"),
    ("IV", "$100bn – $250bn", "4%", "Does not apply", "12 CFR 217.10(a)(1)(iv)"),
    ("III", "$250bn – $700bn", "4%", "3% — measured against total leverage exposure, which adds off-balance-sheet items",
     "12 CFR 217.10(a)(1)(iv)–(v), (c)"),
    ("II", "$700bn or more", "4%", "3%", "12 CFR 217.10(a)(1)(iv)–(v), (c)"),
    ("I", "U.S. GSIBs", "4%", "3% plus a leverage buffer tied to its GSIB surcharge (the 'enhanced' SLR)",
     "12 CFR 217.10(a)(1)(v); 12 CFR 217.11"),
]

FIN_SECTOR_LIABILITIES = 23_223_259_570   # thousands of $ = $23.22 trillion
FIN_SECTOR_SOURCE = ("Federal Reserve notice, FR Doc. 2025-09560 — in effect 1 Jul 2025 to 30 Jun 2026. "
                     "Check for the figure published for 1 Jul 2026 onward.")


def liabilities_test(combined_liabilities, total=FIN_SECTOR_LIABILITIES):
    """12 U.S.C. 1852(b); 12 CFR 251: the combined firm may not exceed 10% of financial-sector liabilities."""
    limit = 0.10 * total
    share = 100 * combined_liabilities / total
    return {"status": "met" if combined_liabilities <= limit else "not_met", "share": share, "limit": limit,
            "detail": f"{bn(combined_liabilities)} = {share:.2f}% of the financial sector's liabilities (limit 10% = {bn(limit)})."}


# ======================================================================================
# 5. A CANADIAN BANK BUYING A U.S. BANK - the U.S. rules it becomes subject to
#    All amounts in thousands of US$.
# ======================================================================================
IHC_TRIGGER = 50e6          # U.S. non-branch assets (12 CFR 252.153)
SUBPART_O_TRIGGER = 100e6   # combined U.S. assets incl. branches (12 CFR 252.150 - Subpart O)

SUBPART_O_RULES = [
    ("U.S. risk committee and U.S. chief risk officer for the combined U.S. operations", "12 CFR 252.155"),
    ("Liquidity stress tests and a U.S. liquidity buffer (branches and IHC)", "12 CFR 252.156; 12 CFR 252.157"),
    ("Capital stress testing", "12 CFR 252.158"),
    ("Certify the parent meets home-country capital standards consistent with Basel", "12 CFR 252.154"),
]
SUBPART_O_NOTE = "Applies to foreign banks with $100bn+ total assets and $100bn+ combined U.S. assets (12 CFR Part 252, Subpart O)."


def _transition(before_on, after_on):
    return "applies" if before_on else ("newly_applies" if after_on else "met")


def us_footprint(ihc_assets, branch_assets, target_assets):
    """U.S. presence before and after the deal. Branches are part of the parent, not subsidiaries."""
    nb_before = ihc_assets
    nb_after = ihc_assets + target_assets
    return {"nonbranch_before": nb_before, "nonbranch_after": nb_after,
            "combined_before": nb_before + branch_assets, "combined_after": nb_after + branch_assets}


def us_rules_for_foreign_buyer(fp):
    """The U.S. thresholds a foreign bank crosses, before vs after the deal."""
    rows = []
    rows.append({"status": _transition(fp["nonbranch_before"] >= IHC_TRIGGER, fp["nonbranch_after"] >= IHC_TRIGGER),
                 "check": "Hold all U.S. subsidiaries through one U.S. intermediate holding company (IHC)",
                 "detail": f"U.S. non-branch assets {bn(fp['nonbranch_before'])} → {bn(fp['nonbranch_after'])} (trigger $50bn).",
                 "src": "12 CFR 252.153"})
    c_before, c_after = category(fp["nonbranch_before"])[0], category(fp["nonbranch_after"])[0]
    rows.append({"status": "newly_applies" if rank(c_after) > rank(c_before) else ("applies" if c_after != "None" else "met"),
                 "check": "The IHC's own U.S. category (treated like a U.S. bank holding company)",
                 "detail": f"{cat_label(c_before)} → {cat_label(c_after)}", "src": CATEGORY_CITE})
    o_before, o_after = fp["combined_before"] >= SUBPART_O_TRIGGER, fp["combined_after"] >= SUBPART_O_TRIGGER
    for rule, cite in SUBPART_O_RULES:
        rows.append({"status": _transition(o_before, o_after), "check": rule,
                     "detail": f"Combined U.S. assets incl. branches {bn(fp['combined_before'])} → {bn(fp['combined_after'])} (trigger $100bn).",
                     "src": cite})
    return rows, (c_before, c_after)


# ======================================================================================
# 6. REG K - can the Canadian bank keep its businesses outside the U.S.?  (12 CFR 211.23)
#    A "qualifying foreign banking organization" (QFBO) may do ANY kind of business outside
#    the U.S. and own foreign companies that do some U.S. business (211.23(f)). To qualify,
#    disregarding its U.S. banking, it must pass BOTH tests (211.23(a)), each on 2 of 3 measures:
#      Test 1 - mostly a bank:        banking outside the U.S. > worldwide non-banking
#      Test 2 - mostly outside U.S.:  banking outside the U.S. > banking in the U.S.
#    U.S. territories (Puerto Rico, Guam...) count as the U.S. (211.23, footnote 10).
# ======================================================================================
def qfbo_test(parent_total_assets, us_banking_assets, us_revenue_share=None, us_income_share=None, mostly_banking=None):
    """parent_total_assets and us_banking_assets in thousands of US$ (after the deal).
    us_*_share: % of the parent's banking revenue / net income earned in the U.S. after the deal (None = not given).
    mostly_banking: the user's confirmation for Test 1 (True / False / None)."""
    legs = []
    if parent_total_assets and us_banking_assets is not None:
        outside = parent_total_assets - us_banking_assets
        legs.append({"measure": "Assets", "us_share": 100 * us_banking_assets / parent_total_assets, "pass": outside > us_banking_assets,
                     "detail": f"Outside U.S. {bn(outside)} vs in U.S. {bn(us_banking_assets)}"})
    else:
        legs.append({"measure": "Assets", "us_share": None, "pass": None, "detail": "Need the parent's total assets (Pillar 3)."})
    asset_share = legs[0]["us_share"]
    for name, share in (("Revenue", us_revenue_share), ("Net income", us_income_share)):
        if share is None and asset_share is not None:
            # Not entered: estimate from the asset split, and say so. Replace with annual-report figures.
            legs.append({"measure": name, "us_share": asset_share, "pass": asset_share < 50, "estimated": True,
                         "detail": f"Estimated at {asset_share:.0f}% (same as the asset split) — enter the annual-report figure to replace"})
        else:
            legs.append({"measure": name, "us_share": share, "pass": None if share is None else share < 50,
                         "detail": "Not entered" if share is None else f"{share:.0f}% earned in the U.S."})
    passes = sum(1 for l in legs if l["pass"] is True)
    fails = sum(1 for l in legs if l["pass"] is False)
    test2 = "met" if passes >= 2 else ("not_met" if fails >= 2 else "unknown")
    test1 = {True: "met", False: "not_met", None: "unknown"}[mostly_banking]
    overall = "not_met" if "not_met" in (test1, test2) else ("met" if test1 == test2 == "met" else "unknown")
    headroom = (parent_total_assets - 2 * us_banking_assets) if parent_total_assets else None
    return {"test1": test1, "test2": test2, "overall": overall, "legs": legs, "headroom": headroom}


REG_K_CONSEQUENCES = [
    ("What qualifying allows", "It may do business of any kind outside the U.S., and own foreign companies that also do some U.S. "
     "business — provided more than half of each such company's assets and revenue are outside the U.S., it doesn't underwrite U.S. "
     "securities beyond what U.S. bank holding companies may, and its U.S. financial activities have Fed approval.", "12 CFR 211.23(f)"),
    ("Failing the tests", "Failing for two consecutive years (as shown in its annual FR Y-7 report) ends the exemptions.", "12 CFR 211.23(d)(1)"),
    ("What must then be unwound", "Activities and investments started after the first failing year must be ended or sold within three "
     "months of the second annual report, unless the Fed consents.", "12 CFR 211.23(d)(2)"),
    ("The way out", "The bank can ask the Fed for a specific determination that it remains eligible — even before it fails.", "12 CFR 211.23(e)"),
]


# ======================================================================================
# 7. THE CANADIAN PARENT UNDER OSFI (C$ millions)
# ======================================================================================
OSFI_DSIB = {"cet1": 8.0, "tier1": 9.5, "total": 11.5, "leverage": 3.5}    # CAR (2027) Ch.1 s.10 (+ DSB); LR Guideline
OSFI_OTHER = {"cet1": 7.0, "tier1": 8.5, "total": 10.5, "leverage": 3.0}


def parent_tests(parent, target_rwa_cad, target_assets_cad, dsib=True, dsb=0.0):
    """Parent's OSFI ratios before/after buying the target for cash at book value
    (capital unchanged; the target's risk-weighted assets and exposure are added)."""
    base = OSFI_DSIB if dsib else OSFI_OTHER
    extra = dsb if dsib else 0
    rows = []
    for name, num, den, add, target, cite in [
        ("CET1 ratio", "cet1", "rwa", target_rwa_cad, base["cet1"] + extra, "OSFI CAR (2027) Ch.1 s.10"),
        ("Tier 1 ratio", "tier1", "rwa", target_rwa_cad, base["tier1"] + extra, "OSFI CAR (2027) Ch.1 s.10"),
        ("Total capital ratio", "total_capital", "rwa", target_rwa_cad, base["total"] + extra, "OSFI CAR (2027) Ch.1 s.10"),
        ("Leverage ratio", "tier1", "leverage_exposure", target_assets_cad, base["leverage"], "OSFI Leverage Requirements Guideline"),
    ]:
        if not parent.get(num) or not parent.get(den):
            rows.append({"test": name, "before": None, "after": None, "target": target, "status": "unknown", "cite": cite})
            continue
        before = 100 * parent[num] / parent[den]
        after = 100 * parent[num] / (parent[den] + add)
        rows.append({"test": name, "before": before, "after": after, "target": target,
                     "status": "met" if after >= target else "not_met", "cite": cite})
    return rows


# ======================================================================================
# 7b. DEAL OPTIONS - "stay under the line"
#     The AI PROPOSES ways to restructure the deal; this code TESTS each one by re-running the
#     same rules as the rest of the app. The AI may only use the moves listed in LEVERS, and only
#     the businesses listed in the chosen preset - code caps anything larger than what exists.
#     All amounts in thousands of US$.
# ======================================================================================
DEAL_PRESETS = {
    "Friendly all-stock merger": {
        "story": ("The buyer pays entirely in its own shares, so it borrows nothing for the deal. The bank being bought has a "
                  "wealth-management arm and a credit-card book that could be sold separately. The client wants to keep the "
                  "branch network whole and would accept a modest share issue."),
        "price_to_cet1": 1.3, "debt_share": 0.0, "equity_ok": True, "securities_ok": True, "branch_ok": False, "canadian_only": False,
        # (business of the bank being bought, share of its total assets, risk weight of those assets)
        "businesses": [("Wealth management & trust", 0.04, 0.30), ("Credit-card portfolio", 0.07, 1.00)],
    },
    "Cash deal funded with debt": {
        "story": ("The buyer pays cash - about 1.5 times the target's CET1 capital - and borrows 70% of it at the holding company. "
                  "The board will not issue new shares because it does not want dilution. The bank being bought has a commercial "
                  "real estate loan book and a residential mortgage book that could be sold."),
        "price_to_cet1": 1.5, "debt_share": 0.7, "equity_ok": False, "securities_ok": True, "branch_ok": False, "canadian_only": False,
        "businesses": [("Commercial real estate loans", 0.12, 1.00), ("Residential mortgages", 0.15, 0.50)],
    },
    "Board says: stay under the next line": {
        "story": ("The board has said the deal only works if the combined bank stays in the buyer's current size category. It will "
                  "sell up to about a quarter of the bank being bought - overlapping branches, the auto-loan book, part of the "
                  "securities portfolio - and will consider a share issue only as a last resort. A third of the price is borrowed."),
        "price_to_cet1": 1.2, "debt_share": 0.3, "equity_ok": True, "securities_ok": True, "branch_ok": False, "canadian_only": False,
        "businesses": [("Overlapping branches (loans and deposits)", 0.10, 0.70), ("Auto-loan portfolio", 0.07, 1.00),
                       ("Part of the securities portfolio", 0.08, 0.20)],
    },
    "Canadian buyer, flexible structure": {
        "story": ("The Canadian parent's priority is keeping its Reg K exemptions for its businesses outside the U.S. It can keep "
                  "some of the target's commercial lending in its own U.S. branch instead of the IHC, sell the target's non-core "
                  "books, and send new capital down to the IHC if needed. It pays in shares."),
        "price_to_cet1": 1.4, "debt_share": 0.0, "equity_ok": True, "securities_ok": True, "branch_ok": True, "canadian_only": True,
        "businesses": [("Commercial loan book", 0.18, 1.00), ("Branch network in one region", 0.12, 0.70), ("Wealth management", 0.05, 0.30)],
    },
}

LEVERS = {
    "sell_business": "Sell one of the listed businesses of the bank being bought (its loans and the matching deposits go to the purchaser, sold at book value)",
    "raise_equity": "Raise new common equity (for a Canadian buyer: the parent sends new capital down to the IHC). Adds to capital - and to assets, as cash",
    "replace_debt_with_stock": "Pay part of the price in shares instead of the planned acquisition debt",
    "sell_securities": "The buyer sells some of its own securities before closing and repays wholesale funding with the cash",
    "book_in_branch": "Keep part of the target's lending in the Canadian parent's U.S. branch, outside the IHC (Canadian buyer only)",
}
SECURITIES_RW = 0.20       # assumed risk weight of securities sold (mostly government and agency bonds)
MAX_SECURITIES = 0.05      # the buyer can sell up to 5% of its own assets in securities
MAX_BRANCH = 0.20          # up to 20% of the target's assets can stay in the branch


def deal_menu(preset_name, target_assets, target_cet1, buyer_assets, canadian):
    """What the AI is allowed to use for this deal, with the most each move can be (thousands of US$)."""
    p = DEAL_PRESETS[preset_name]
    price = p["price_to_cet1"] * (target_cet1 or 0)
    menu = {"price": price, "deal_debt": p["debt_share"] * price, "businesses": {}, "levers": {}}
    for name, share, rw in p["businesses"]:
        menu["businesses"][name] = {"max": share * target_assets, "rw": rw}
    menu["levers"]["sell_business"] = sum(b["max"] for b in menu["businesses"].values())
    if p["equity_ok"]:
        menu["levers"]["raise_equity"] = 0.5 * (target_cet1 or 0)          # at most half the target's CET1 again
    if menu["deal_debt"]:
        menu["levers"]["replace_debt_with_stock"] = menu["deal_debt"]
    if p["securities_ok"]:
        menu["levers"]["sell_securities"] = MAX_SECURITIES * buyer_assets
    if p["branch_ok"] and canadian:
        menu["levers"]["book_in_branch"] = MAX_BRANCH * target_assets
    return menu


def clean_levers(levers, menu):
    """Code check on the AI's proposal: unknown moves are dropped, amounts are capped at what exists."""
    out, notes, used = [], [], {}
    for lv in levers or []:
        kind = str(lv.get("lever", ""))
        try:
            amt = max(0.0, float(lv.get("amount_bn", 0))) * 1e6
        except (TypeError, ValueError):
            amt = 0.0
        if kind not in menu["levers"]:
            notes.append(f"Dropped a move the client has ruled out or that isn't available: '{kind}'.")
            continue
        biz = None
        if kind == "sell_business":
            biz = lv.get("business")
            if biz not in menu["businesses"]:
                notes.append(f"Dropped the sale of '{biz}', which is not one of the listed businesses.")
                continue
            cap = menu["businesses"][biz]["max"] - used.get(biz, 0)
            label = biz
        else:
            cap = menu["levers"][kind] - used.get(kind, 0)
            label = kind
        if amt > cap + 1:
            notes.append(f"AI asked for {bn(amt)} ({label.replace('_', ' ')}); capped at the {bn(cap)} available.")
            amt = cap
        if amt <= 0:
            continue
        used[label] = used.get(label, 0) + amt
        out.append({"lever": kind, "business": biz, "amount": amt})
    return out, notes


def apply_levers(base, levers, menu):
    """Return a new pro forma after the moves. Simple, stated assumptions - this is a screening tool."""
    x = dict(base)
    for lv in levers:
        amt, kind = lv["amount"], lv["lever"]
        if kind == "sell_business":
            rw = menu["businesses"][lv["business"]]["rw"]
            for k in ("avg_assets", "total_assets", "lev_assets", "liabilities"):
                x[k] -= amt
            x["rwa"] -= rw * amt
            if x.get("slr_exposure"):
                x["slr_exposure"] -= amt
            if x.get("us_combined") is not None:
                x["us_combined"] -= amt
                x["parent_total"] = x["parent_total"] - amt if x.get("parent_total") else None
        elif kind == "sell_securities":
            for k in ("avg_assets", "total_assets", "lev_assets", "liabilities"):
                x[k] -= amt
            x["rwa"] -= SECURITIES_RW * amt
            if x.get("slr_exposure"):
                x["slr_exposure"] -= amt
            if x.get("us_combined") is not None:
                x["us_combined"] -= amt
                x["parent_total"] = x["parent_total"] - amt if x.get("parent_total") else None
        elif kind == "raise_equity":
            for k in ("cet1", "tier1", "total_capital", "avg_assets", "total_assets", "lev_assets"):
                x[k] += amt
            if x.get("slr_exposure"):
                x["slr_exposure"] += amt
            if x.get("us_combined") is not None:
                x["us_combined"] += amt            # the cash sits in the U.S.; the parent's total is unchanged
        elif kind == "replace_debt_with_stock":
            x["liabilities"] -= amt
        elif kind == "book_in_branch":
            # The loans leave the IHC (and its category count) but stay in the U.S. and in the parent:
            # Subpart O and Reg K do not change. Capital moves with them, so the IHC's ratios hold steady.
            share = (base["target_rwa_density"] * amt) / x["rwa"]
            for k in ("cet1", "tier1", "total_capital"):
                x[k] -= share * x[k]
            for k in ("avg_assets", "total_assets", "lev_assets", "liabilities"):
                x[k] -= amt
            x["rwa"] -= base["target_rwa_density"] * amt
            if x.get("slr_exposure"):
                x["slr_exposure"] -= amt
    return x


def evaluate(x):
    """Run the app's ordinary rules on a pro forma."""
    cat = category(x["avg_assets"], x.get("gsib", False))[0]
    bank = {"cet1_ratio": 100 * x["cet1"] / x["rwa"], "tier1_ratio": 100 * x["tier1"] / x["rwa"],
            "total_ratio": 100 * x["total_capital"] / x["rwa"], "leverage_ratio": 100 * x["tier1"] / x["lev_assets"],
            "slr": 100 * x["tier1"] / x["slr_exposure"] if x.get("slr_exposure") else None}
    out = {"category": cat, "ratios": bank, "capital": capital_tests(bank), "leverage": leverage_tests(bank, cat),
           "liabilities": liabilities_test(x["liabilities"]), "x": x}
    if x.get("us_combined") is not None:
        out["regk"] = qfbo_test(x.get("parent_total"), x["us_combined"], x.get("us_rev_share"), x.get("us_ni_share"), x.get("mostly_banking"))
        out["subpart_o"] = x["us_combined"] >= SUBPART_O_TRIGGER
    return out


def deal_goals(base, buyer_cat, before_us_combined=None, who="the combined bank"):
    """The lines this deal crosses or fails, worked out by code. Each goal has a test and a 'gap'."""
    ev = evaluate(base)
    goals = []
    if rank(ev["category"]) > rank(buyer_cat) and buyer_cat != "I":
        nxt = CATEGORY_ORDER[rank(buyer_cat) + 1]
        line = LINES[nxt]
        goals.append({"id": "category", "line": line,
                      "text": f"Keep {who} below {bn(line, 0)} so it stays {cat_label(buyer_cat).replace('Below', 'below')}",
                      "gap": base["avg_assets"] - line, "cite": CATEGORY_CITE})
    if any(r["status"] in ("not_met", "warning") for r in ev["capital"] + ev["leverage"]):
        goals.append({"id": "capital", "text": "Bring every capital and leverage ratio above the minimum plus buffer", "gap": None,
                      "cite": "12 CFR 217.10; 217.11"})
    if ev["liabilities"]["status"] == "not_met":
        goals.append({"id": "liabilities", "text": "Stay under the 10% liabilities concentration limit",
                      "gap": base["liabilities"] - ev["liabilities"]["limit"], "cite": "12 U.S.C. 1852(b); 12 CFR 251"})
    if "regk" in ev and ev["regk"]["test2"] == "not_met":
        goals.append({"id": "regk", "text": "Pass Reg K test 2: more of the parent's banking outside the U.S. than in it",
                      "gap": 2 * base["us_combined"] - base["parent_total"], "cite": "12 CFR 211.23(a)(2)"})
    if "regk" in ev and ev["subpart_o"] and before_us_combined is not None and before_us_combined < SUBPART_O_TRIGGER:
        goals.append({"id": "subpart_o", "line": SUBPART_O_TRIGGER, "text": "Keep combined U.S. assets below $100bn (avoid Subpart O)",
                      "gap": base["us_combined"] - SUBPART_O_TRIGGER, "cite": "12 CFR 252 Subpart O"})
    return goals


def goal_met(goal, ev):
    gid = goal["id"]
    if gid == "category":
        return ev["x"]["avg_assets"] < goal["line"]
    if gid == "capital":
        return all(r["status"] == "met" for r in ev["capital"] + ev["leverage"])
    if gid == "liabilities":
        return ev["liabilities"]["status"] == "met"
    if gid == "regk":
        return ev["regk"]["test2"] == "met"
    if gid == "subpart_o":
        return not ev["subpart_o"]
    return False


def best_case(goal, base, menu):
    """Can this goal be reached at all with the moves available? Code tries every move at its maximum
    (once without new equity - which adds size - and once with it).
    Returns (reachable, shortfall if not, share of everything available that is needed if it is)."""
    sells = [{"lever": "sell_business", "business": n, "amount": b["max"]} for n, b in menu["businesses"].items()]
    others = [{"lever": k, "business": None, "amount": v} for k, v in menu["levers"].items() if k not in ("sell_business", "raise_equity")]
    tries = [sells + others]
    if "raise_equity" in menu["levers"]:
        tries.append(sells + others + [{"lever": "raise_equity", "business": None, "amount": menu["levers"]["raise_equity"]}])
    best = None
    for levers in tries:
        ev = evaluate(apply_levers(base, levers, menu))
        if goal_met(goal, ev):
            lo, hi = 0.0, 1.0       # how much of everything is needed: scale every move down together
            for _ in range(30):
                mid = (lo + hi) / 2
                scaled = [dict(l, amount=l["amount"] * mid) for l in levers]
                if goal_met(goal, evaluate(apply_levers(base, scaled, menu))):
                    hi = mid
                else:
                    lo = mid
            return True, None, hi
        sf = goal_shortfall(goal, ev)
        best = sf if best is None or (sf is not None and sf < best) else best
    return False, best, None


def move_facts(goals, base, menu):
    """Facts for the AI: the fewest moves (each used in full) that clear every reachable goal, and which single
    moves could do it alone. Code tries every combination - there are at most a few dozen."""
    from itertools import combinations
    live = [g for g in goals if g.get("reachable", True)]
    moves = [("sell_business", n, b["max"]) for n, b in menu["businesses"].items()] + \
            [(k, None, v) for k, v in menu["levers"].items() if k != "sell_business"]
    label = lambda m: m[1] or m[0]
    for k in range(1, len(moves) + 1):
        hits = []
        for combo in combinations(moves, k):
            levers = [{"lever": m[0], "business": m[1], "amount": m[2]} for m in combo]
            if live and total_shortfall(live, evaluate(apply_levers(base, levers, menu)), cushion=False) == 0:
                hits.append([label(m) for m in combo])
        if hits:
            return {"fewest": k, "examples": hits[:4], "singles": [h[0] for h in hits] if k == 1 else []}
    return {"fewest": None, "examples": [], "singles": []}


def goal_shortfall(goal, ev):
    """How far an option still is from a goal (thousands of US$), for the AI's second try."""
    x = ev["x"]
    if goal["id"] == "category":
        return x["avg_assets"] - goal["line"]
    if goal["id"] == "liabilities":
        return x["liabilities"] - ev["liabilities"]["limit"]
    if goal["id"] == "regk" and x.get("parent_total"):
        return 2 * x["us_combined"] - x["parent_total"]
    if goal["id"] == "subpart_o":
        return x["us_combined"] - SUBPART_O_TRIGGER
    return None


def capital_deficit(ev):
    """Capital still needed (thousands of US$) to bring every ratio up to its minimum plus buffer."""
    x, need = ev["x"], 0.0
    for r in ev["capital"]:
        need = max(need, (r["with_buffer"] - r["value"]) / 100 * x["rwa"])
    for r in ev["leverage"]:
        if r["value"] is not None:
            base_ = x["lev_assets"] if r["key"] == "leverage_ratio" else x.get("slr_exposure") or x["lev_assets"]
            need = max(need, (r["with_buffer"] - r["value"]) / 100 * base_)
    return max(0.0, need)


SIZE_MARGIN = 0.10   # aim for a cushion of 10% of each gap below the line, not just touching it


def total_shortfall(goals, ev, cushion=True):
    """How far an option is from meeting every (reachable) goal; 0 = all met, with the cushion if asked."""
    out = 0.0
    for g in goals:
        if g.get("reachable", True) is False:
            continue
        if g["id"] == "capital":
            d = capital_deficit(ev)
            if d > 0 or not goal_met(g, ev):
                out += max(1.0, d)
            continue
        sf = goal_shortfall(g, ev)
        if sf is None:
            out += 0.0 if goal_met(g, ev) else 1.0
            continue
        c = SIZE_MARGIN * g["gap"] if cushion and g.get("gap") and g["gap"] > 0 else 0.0
        if sf + c >= 0:
            out += max(1.0, sf + c)
    return out


def size_option(base, moves, menu, goals):
    """The AI chooses WHICH moves, in order of preference, and any limit the client would want (max_bn).
    Code decides HOW MUCH: each move is used only as far as needed to clear the goals with a cushion of 10% of
    each gap (or in full, if even that is not enough).
    A move that does not help with what is left is skipped. Returns (levers, notes)."""
    chosen, notes, used = [], [], {}
    goals = [g for g in goals if g.get("reachable", True)]

    def score(levers):
        return total_shortfall(goals, evaluate(apply_levers(base, levers, menu)))

    for mv in moves or []:
        kind = str(mv.get("lever", ""))
        if kind not in menu["levers"]:
            notes.append(f"Skipped '{kind}': not available on this deal background.")
            continue
        biz = mv.get("business") if kind == "sell_business" else None
        if kind == "sell_business" and biz not in menu["businesses"]:
            notes.append(f"Skipped the sale of '{biz}': not one of the listed businesses.")
            continue
        key = biz or kind
        cap = (menu["businesses"][biz]["max"] if biz else menu["levers"][kind]) - used.get(key, 0)
        try:
            if mv.get("max_bn") not in (None, ""):
                cap = min(cap, max(0.0, float(mv["max_bn"])) * 1e6)
        except (TypeError, ValueError):
            pass
        now = score(chosen)
        if now == 0:
            break
        if cap <= 0:
            continue
        full = chosen + [{"lever": kind, "business": biz, "amount": cap}]
        if score(full) >= now:
            notes.append(f"Left out '{(biz or kind).replace('_', ' ')}': it does not help with what is left.")
            continue
        if score(full) > 0:
            chosen, used[key] = full, used.get(key, 0) + cap
            continue
        lo, hi = 0.0, cap
        for _ in range(40):
            mid = (lo + hi) / 2
            if score(chosen + [{"lever": kind, "business": biz, "amount": mid}]) == 0:
                hi = mid
            else:
                lo = mid
        amt = hi
        chosen.append({"lever": kind, "business": biz, "amount": amt})
        used[key] = used.get(key, 0) + amt
        break
    return chosen, notes


# ======================================================================================
# 7c. THE AI'S READING OF THE RULES vs THE BUILT-IN RULEBOOK
#     The AI reads 12 CFR 252.5, 217.10-11, 225.8, 252.44 and Part 249 and works out the category and
#     what applies. Code compares its answer, point by point, with REQUIREMENTS above.
# ======================================================================================
RULE_STATES = ["applies", "does not apply", "conditional", "optional"]


def rulebook_state(value):
    """The built-in rulebook's value for a requirement, in the same words the AI must use."""
    v = value.lower()
    if v.startswith("no"):
        return "does not apply"
    if v.startswith("optional"):
        return "optional"
    if v.startswith("possibly"):
        return "conditional"
    return "applies"          # "Yes", "Annual", "Every other year", "Yes (enhanced)", "Yes (reduced or full)" ...


def compare_rule_reading(ai_out, before, after):
    """Point-by-point comparison. Returns rows plus the counts that go on screen and into the memo."""
    cat = ai_out.get("category") or {}
    norm = lambda c: str(c or "").replace("Category", "").replace("category", "").strip().upper() or "?"
    ai_b, ai_a = norm(cat.get("before")), norm(cat.get("after"))
    ai_b = "None" if ai_b in ("NONE", "NO CATEGORY", "BELOW $100BN", "N/A") else ai_b
    ai_a = "None" if ai_a in ("NONE", "NO CATEGORY", "BELOW $100BN", "N/A") else ai_a
    rows = [{"point": "Size category before the deal", "ai": cat_label(ai_b) if ai_b in CATEGORY_ORDER else ai_b,
             "rulebook": cat_label(before), "agree": ai_b == before, "why": "", "cite": CATEGORY_CITE},
            {"point": "Size category after the deal", "ai": cat_label(ai_a) if ai_a in CATEGORY_ORDER else ai_a,
             "rulebook": cat_label(after), "agree": ai_a == after, "why": cat.get("why", ""), "cite": CATEGORY_CITE}]
    given = {str(r.get("name", "")).strip().lower(): r for r in ai_out.get("requirements", []) if isinstance(r, dict)}
    # (the AI answers by number; ai.read_rules puts each requirement's exact name back before this comparison)
    for name, values, cite in REQUIREMENTS:
        r = given.get(name.lower()) or next((x for k, x in given.items() if k[:18] == name.lower()[:18]), {})
        for when, cat_ in (("after", after),):
            ai_state = str(r.get(when, "")).strip().lower()
            ai_state = ai_state if ai_state in RULE_STATES else ("(not determined)" if ai_state else "")
            book = rulebook_state(values[cat_])
            close = {ai_state, book} <= {"optional", "conditional"}
            rows.append({"point": f"{name} — after the deal", "ai": ai_state or "(no answer)", "rulebook": f"{book} ({values[cat_]})",
                         "agree": True if ai_state == book else ("close" if close else False), "why": r.get("why", ""), "cite": cite})
    agree = sum(1 for r in rows if r["agree"] is True)
    close = sum(1 for r in rows if r["agree"] == "close")
    return {"rows": rows, "agree": agree, "close": close, "total": len(rows), "differ": len(rows) - agree - close}


# ======================================================================================
# 7d. THE AI ANALYST'S TOOLS - the AI chooses what to test; these functions do the arithmetic.
#     `base` is the combined bank as plain numbers (built in app.py), thousands of US$.
# ======================================================================================
def _scale_in(x, part, factor):
    """Grow (factor > 0) or shrink (factor < 0) one bank's contribution to the combined pro forma."""
    for k_x, k_p in (("avg_assets", "avg_assets"), ("total_assets", "total_assets"), ("lev_assets", "lev_assets"),
                     ("liabilities", "liabilities"), ("rwa", "rwa"), ("cet1", "cet1"), ("tier1", "tier1"), ("total_capital", "total_capital")):
        x[k_x] += factor * (part.get(k_p) or 0)
    if x.get("slr_exposure"):
        x["slr_exposure"] += factor * (part.get("total_assets") or 0) * 1.12
    if x.get("us_combined") is not None:
        x["us_combined"] += factor * (part.get("total_assets") or 0)
        if x.get("parent_total"):
            x["parent_total"] += factor * (part.get("total_assets") or 0)


def tool_scenario(base, target_size_pct=100.0, buyer_size_pct=100.0, capital_loss_bn=0.0, rwa_change_pct=0.0, extra_debt_bn=0.0):
    """What-if: change either bank's size, knock capital, move risk-weighted assets, add debt. Re-runs every rule."""
    x = dict(base)
    _scale_in(x, base["target"], float(target_size_pct) / 100 - 1)
    _scale_in(x, base["buyer"], float(buyer_size_pct) / 100 - 1)
    loss = float(capital_loss_bn) * 1e6
    for k in ("cet1", "tier1", "total_capital"):
        x[k] -= loss
    x["rwa"] *= 1 + float(rwa_change_pct) / 100
    x["liabilities"] += float(extra_debt_bn) * 1e6
    ev = evaluate(x)
    out = {"inputs": {"target_size_pct": target_size_pct, "buyer_size_pct": buyer_size_pct, "capital_loss_bn": capital_loss_bn,
                      "rwa_change_pct": rwa_change_pct, "extra_debt_bn": extra_debt_bn},
           "category": cat_label(ev["category"]), "average_assets": bn(x["avg_assets"]),
           "ratios": {r["test"]: f"{r['value']:.2f}% ({STATUS[r['status']][1].lower()}; needs {r['with_buffer']:.1f}%)"
                      for r in ev["capital"] + ev["leverage"] if r["value"] is not None},
           "liabilities_share_of_limit": f"{100 * x['liabilities'] / ev['liabilities']['limit']:.1f}%"}
    if "regk" in ev and ev["regk"]["legs"][0]["us_share"] is not None:
        out["reg_k_us_share_of_banking_assets"] = f"{ev['regk']['legs'][0]['us_share']:.1f}% (test 2: {STATUS[ev['regk']['test2']][1].lower()})"
        out["combined_us_assets"] = bn(x["us_combined"])
    newly = [r["Requirement"] for r in newly_applying(base["buyer_cat"], ev["category"])]
    out["newly_applies_vs_buyer_today"] = newly or ["nothing new"]
    return out


def tool_headroom(base):
    """How far the combined bank sits from every line the app tests, right now."""
    ev = evaluate(base)
    x, out = base, {}
    for c, line in LINES.items():
        d = x["avg_assets"] - line
        out[f"${line / 1e6:.0f}bn line (Category {c})"] = f"{bn(abs(d))} {'above' if d >= 0 else 'below'}"
    for r in ev["capital"]:
        out[f"{r['test']} surplus over minimum + buffer"] = (f"{r['value'] - r['with_buffer']:+.2f} points = "
                                                            f"{bn((r['value'] - r['with_buffer']) / 100 * x['rwa'])} of capital")
    for r in ev["leverage"]:
        if r["value"] is not None:
            den = x["lev_assets"] if r["key"] == "leverage_ratio" else x["slr_exposure"]
            out[f"{r['test']} surplus over {r['minimum']:.0f}%"] = f"{r['value'] - r['minimum']:+.2f} points = {bn((r['value'] - r['minimum']) / 100 * den)}"
    out["10% liabilities limit"] = f"{bn(ev['liabilities']['limit'] - x['liabilities'])} of room"
    if "regk" in ev and ev["regk"]["headroom"] is not None:
        h = ev["regk"]["headroom"]
        out["Reg K assets measure"] = f"{bn(abs(h))} {'of room for more U.S. banking assets' if h > 0 else 'past the point where it fails'}"
        out["Subpart O ($100bn combined U.S. assets)"] = f"{bn(abs(x['us_combined'] - SUBPART_O_TRIGGER))} {'above' if x['us_combined'] >= SUBPART_O_TRIGGER else 'below'}"
    return out


def tool_break_even(base):
    """What it would take to flip each result - solved exactly by code."""
    ev, x, out = evaluate(base), base, {}
    worst_buffer = min((r["value"] - r["with_buffer"]) / 100 * x["rwa"] for r in ev["capital"])
    worst_min = min((r["value"] - r["minimum"]) / 100 * x["rwa"] for r in ev["capital"])
    lev_room = x["tier1"] - 0.04 * x["lev_assets"]
    out["Capital loss before any ratio falls into its buffer"] = bn(max(0.0, worst_buffer))
    out["Capital loss before any ratio breaches its minimum"] = bn(max(0.0, min(worst_min, lev_room)))
    t_avg = base["target"]["avg_assets"] or 1
    cat = ev["category"]
    above = [l for l in LINES.values() if l > x["avg_assets"]]
    if above:
        nxt = min(above)
        out[f"Growth in the bank being bought before the combined bank crosses {bn(nxt, 0)}"] = (
            f"{100 * (nxt - x['avg_assets']) / t_avg:.1f}% ({bn(nxt - x['avg_assets'])})")
    below = [l for l in LINES.values() if l <= x["avg_assets"]]
    if below:
        low = max(below)
        out[f"Shrinkage needed to get back under {bn(low, 0)}"] = (f"{bn(x['avg_assets'] - low)} = "
                                                                  f"{100 * (x['avg_assets'] - low) / t_avg:.1f}% of the bank being bought")
    out["Category today (combined)"] = cat_label(cat)
    if "regk" in ev and ev["regk"]["headroom"] is not None:
        h = ev["regk"]["headroom"]
        out["U.S. banking assets the parent could add (or must shed) for the Reg K assets measure"] = (
            f"{'add up to' if h > 0 else 'shed more than'} {bn(abs(h))}")
    return out


def tool_timeline(base, buyer_history, target_history, quarter_labels):
    """The four-quarter average after closing, quarter by quarter (balance sheets held at their latest size).
    Moving UP a category uses the four-quarter average; moving DOWN needs four quarters in a row below the line (12 CFR 252.5)."""
    b_hist = [v for v in buyer_history if v] or [base["buyer"]["total_assets"]]
    t_last = (target_history or [base["target"]["total_assets"]])[-1]
    b_last = b_hist[-1]
    pre = (b_hist[-4:] if len(b_hist) >= 4 else [b_hist[0]] * (4 - len(b_hist)) + b_hist)
    series, rows = list(pre), []
    for i, label in enumerate(quarter_labels):
        series.append(b_last + t_last)
        window = series[-4:]
        avg = sum(window) / 4
        rows.append({"quarter_end": label, "quarters_since_closing": i + 1, "four_quarter_average": bn(avg),
                     "category": cat_label(category(avg, base.get("gsib", False))[0])})
    start = cat_label(category(sum(pre) / 4, base.get("gsib", False))[0])
    change = next((r for r in rows if r["category"] != start), None)
    final = rows[-1]["category"] if rows else start
    summary = (f"Before closing the four-quarter average puts it in {start}. It first reaches {change['category']} at the "
               f"{change['quarter_end']} quarter-end ({change['quarters_since_closing']} quarter(s) after closing)"
               + (f", and is in {final} from then on" if change["category"] == final else f", ending at {final}") + "."
               if change else f"It stays in {start} for all six quarter-ends shown.")
    return {"summary": summary, "rows": rows,
            "note": "Balance sheets held at their latest reported size. A bank moves up a category on its "
                    "four-quarter average and only moves down after four quarters in a row below the line."}


ANALYST_TOOLS = {
    "headroom": "How far the combined bank is from every line right now (size lines, capital surplus over minimum + buffer, "
                "leverage, liabilities limit, and for a Canadian buyer Reg K and Subpart O). No arguments.",
    "break_even": "What it would take to flip each result: capital loss before buffers or minimums are breached, growth before "
                  "the next size line, shrinkage to get back under the line below, Reg K room. No arguments.",
    "scenario": "A what-if. Arguments (all optional): target_size_pct (100 = as filed; 110 = bank being bought 10% bigger), "
                "buyer_size_pct, capital_loss_bn (a loss that cuts CET1, Tier 1 and total capital), rwa_change_pct (e.g. 15 = "
                "risk-weighted assets 15% higher), extra_debt_bn (acquisition debt). Returns category, every ratio and its status, "
                "liabilities, Reg K share, and what newly applies.",
    "timeline": "The combined bank's four-quarter average size and category for each of the six quarter-ends after closing. No arguments.",
}


def run_tool(name, args, base, timeline_inputs):
    args = args if isinstance(args, dict) else {}
    if name == "headroom":
        return tool_headroom(base)
    if name == "break_even":
        return tool_break_even(base)
    if name == "timeline":
        return tool_timeline(base, *timeline_inputs)
    if name == "scenario":
        clean = {}
        for k, lo, hi in (("target_size_pct", 0, 300), ("buyer_size_pct", 0, 300), ("capital_loss_bn", -500, 500),
                          ("rwa_change_pct", -90, 200), ("extra_debt_bn", 0, 1000)):
            v = _to_float(args.get(k))
            if v is not None:
                clean[k] = min(hi, max(lo, v))
        return tool_scenario(base, **clean)
    return {"error": f"Unknown tool '{name}'. Use one of: {', '.join(ANALYST_TOOLS)}."}


# ======================================================================================
# 7e. DISPOSAL REVIEW OF THE PARENT'S HOLDINGS (Reg K, and the BHC Act as applied through Reg Y)
#     The AI gives a reasoned verdict per holding; code fixes the vocabulary, the timing and the consistency checks.
# ======================================================================================
VERDICTS = {
    "keep": ("Can keep", "met"),
    "keep_conditions": ("Can keep — conditions apply", "warning"),
    "at_risk": ("At risk if Reg K status is lost", "review"),
    "sell": ("Likely must sell or restructure", "not_met"),
    "approval": ("Needs Fed approval or notice", "newly_applies"),
}
VERDICT_ORDER = ["sell", "at_risk", "approval", "keep_conditions", "keep"]


def disposal_timing(verdict, regk_overall, closing):
    """When a disposal would bite - straight from 12 CFR 211.23(d); dates are a rough guide from the closing date."""
    if verdict not in ("sell", "at_risk"):
        return ""
    if regk_overall == "not_met":
        when = ""
        if closing:
            first = closing.replace(year=closing.year + 2)
            m = first.month + 3
            when = f" — about {datetime.date(first.year + (m - 1) // 12, (m - 1) % 12 + 1, min(first.day, 28)):%b %Y}"
        return ("If Reg K status stays lost: sell or wind down within 3 months of the second failing annual report"
                + when + ", unless the Fed consents (12 CFR 211.23(d))")
    if verdict == "sell":
        return "Before relying on the exemption — the 211.23(f) conditions are not met on these facts"
    return "Only if it later stops qualifying (12 CFR 211.23(d))"


def disposal_checks(h, verdict, regk_overall):
    """Code's consistency check of each AI verdict against the app's own Reg K result and the facts given."""
    notes = []
    nonbank = h.get("activity") in ("Insurance", "Real estate", "Non-financial (commercial)", "Securities & investment", "Funds & trusts")
    in_us = str(h.get("country", "")).strip().lower() in ("united states", "usa", "us", "u.s.", "puerto rico", "guam",
                                                           "u.s. virgin islands", "american samoa", "northern mariana islands")
    if regk_overall == "not_met" and verdict == "keep" and nonbank and not in_us:
        notes.append("The app's Reg K test FAILS, so non-banking holdings abroad lose their exemption in time — AI said 'can keep'.")
    if verdict == "sell" and not h.get("us_business") and not in_us:
        notes.append("No U.S. business: a qualifying bank may hold it, so 'at risk if Reg K status is lost' may fit better than "
                     "'must sell' — check the AI's reason.")
    if in_us and verdict == "keep" and nonbank:
        notes.append("Located in the U.S. or a U.S. territory, which Reg K treats as the U.S. — a non-banking business there must "
                     "be one a U.S. bank holding company may own.")
    return notes


# ======================================================================================
# 7f. NUMBER CHECK - every $ figure and % the AI writes must come from the app's own results
# ======================================================================================
_MONEY = re.compile(r"(?:US|C)?\$\s?(\d[\d,]*(?:\.\d+)?)\s?(tn|trillion|bn|billion|m|million)?", re.I)
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s?(?:%|percent\b|per cent\b)")
REG_CONSTANTS = {4.5, 6.0, 8.0, 4.0, 3.0, 2.5, 7.0, 8.5, 10.5, 9.5, 11.5, 10.0, 1.0, 50.0, 25.0, 5.0, 3.5, 0.0, 100.0}


def _numbers(text):
    money, pct = [], []
    for m in _MONEY.finditer(text or ""):
        v = float(m.group(1).replace(",", ""))
        unit = (m.group(2) or "").lower()
        v = v * 1000 if unit in ("tn", "trillion") else v / 1000 if unit in ("m", "million") else v
        if unit or v >= 1:
            money.append((m.group(0).strip(), v))
    for m in _PCT.finditer(text or ""):
        pct.append((m.group(0).strip(), float(m.group(1))))
    return money, pct


def verify_numbers(text, sources):
    """Returns {'checked', 'unverified': [...]} - a number passes if it matches (to its own rounding) a number in `sources`."""
    s_money, s_pct = _numbers(sources)
    s_m = [v for _, v in s_money] + [50.0, 100.0, 250.0, 700.0, 75.0]
    s_p = [v for _, v in s_pct] + sorted(REG_CONSTANTS)
    checked, bad = 0, []
    for tok, v in _numbers(text)[0]:
        checked += 1
        if not any(abs(v - x) <= max(0.051, 0.0051 * abs(x)) for x in s_m):
            bad.append(tok)
    for tok, v in _numbers(text)[1]:
        checked += 1
        if not any(abs(v - x) <= 0.051 for x in s_p):
            bad.append(tok)
    return {"checked": checked, "unverified": list(dict.fromkeys(bad))}


# ======================================================================================
# 8. STATUS LABELS
# ======================================================================================
STATUS = {
    "met": ("✓", "Met", "#1e7d4f"),
    "warning": ("!", "Inside buffer", "#b26a00"),
    "review": ("!", "Review", "#b26a00"),
    "not_met": ("✕", "Not met", "#b42318"),
    "newly_applies": ("↑", "Newly applies", "#1f3a93"),
    "applies": ("•", "Already applies", "#5b6474"),
    "unknown": ("?", "Can't tell", "#6b7280"),
}
