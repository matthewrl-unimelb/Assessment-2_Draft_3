"""
app.py - Bank Merger Regulatory Check (Streamlit).

Run:    python3 -m streamlit run app.py
Layout: step list on the left (green arrows show where you are and what's next).
        Home (choose the deal) -> 1 At a glance -> 2 Capital ratios -> 3 Leverage & liabilities
        -> 4 Canadian buyer -> 5 Summary & next steps.  Plus a "Size examples" reference page.
Rule:   engine.py calculates and decides; ai.py reads and explains; this file only shows things.
"""

import datetime
import hashlib
import io
import json
import os
import re

import pandas as pd
import streamlit as st

import ai
import engine as E
from library import Library

try:  # local development: read API keys from a .env file (never upload it)
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

st.set_page_config(page_title="Bank Merger Regulatory Check", page_icon="🏦", layout="wide")
HERE = os.path.dirname(os.path.abspath(__file__))
TEST = os.path.join(HERE, "test_data")
SMALL_BANKS = "BHCF20260930.txt"   # the Fed's bulk FR Y-9C file for 18 smaller U.S. holding companies
US_ARM_FILES = {                    # FR Y-9C reports of the Canadian banks' U.S. holding companies
    "TD": ["TD_US_FRY9C_2026Q1.pdf", "TD_US_FRY9C_2026Q2.pdf"], "BMO": ["BMO_US_FRY9C_2026Q2.pdf"],
    "RBC": ["RBC_US_FRY9C_2026Q2.pdf"], "CIBC": ["CIBC_US_FRY9C_2026Q2.pdf"]}
PILLAR3 = {"RBC": ("RBC_Pillar3_Q3_2026.pdf", "RBC Pillar 3 report (Q3 2026)"),
           "BMO": ("BMO_RegCapital_Q3_2026.pdf", "BMO capital disclosure (Q3 2026)"),
           "TD": ("TD_RegDisclosure_Q3_2023.pdf", "TD disclosure (Q3 2023 — older layout)")}
with open(os.path.join(HERE, "library", "us_structure.json")) as _fh:
    STRUCTURE = json.load(_fh)   # built once by build_structure.py from the Fed's NIC ownership data
CANADIAN = list(STRUCTURE)       # TD, RBC, BMO, CIBC

PAGE_NAMES = {"home": "Home", "setup": "Getting started", "glance": "At a glance", "capital": "Capital ratios",
              "leverage": "Leverage & liabilities", "canadian": "Canadian buyer", "analyst": "AI analyst", "options": "Deal options", "summary": "Summary & next steps",
              "sizes": "Size examples"}
EXAMPLE_POOL = "EXAMPLE_BANKS_2026Q2.txt"   # fictional banks sized just under the category lines (make_example_banks.py)


# Streamlit reads "$...$" as maths. Escape dollar signs in plain text (raw HTML blocks are left alone).
def _escape_dollars(fn):
    def wrapper(body="", *args, **kwargs):
        # Block-level HTML (<table>, <div>, <p>) is not run through markdown, so it is left alone;
        # everything else - including inline <span> lines - gets its dollar signs escaped.
        if isinstance(body, str) and not re.match(r"\s*<(table|div|style|p)[\s>]", body):
            body = re.sub(r"(?<!\\)\$", r"\\$", body)
        return fn(body, *args, **kwargs)
    return wrapper


for _n in ("markdown", "info", "success", "warning", "error", "caption", "write"):
    setattr(st, _n, _escape_dollars(getattr(st, _n)))

# --------------------------------------------------------------------------------------
# Look and feel: white, calm, generous spacing, two typefaces
# --------------------------------------------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Source+Serif+4:opsz,wght@8..60,600;8..60,700&display=swap');
:root { --ink:#1a1d23; --muted:#6b7280; --line:#e7e9ee; --navy:#1f3a93; --green:#1e7d4f; --ai:#6c4ee0; }
.stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stMain"] { background:#ffffff !important; color:var(--ink); }
[data-testid="stSidebar"], [data-testid="stSidebar"] > div { background:#f7f8fa !important; }
.stApp p, .stApp li, .stApp label, .stApp td, .stApp th, .stApp input, .stApp textarea, .stMarkdown {
  font-family:'Inter', system-ui, sans-serif !important; color:var(--ink); }
.stApp button, .stApp button p { font-family:'Inter', system-ui, sans-serif !important; }
.stApp button[kind="primary"], .stApp button[kind="primary"] p, .stApp button[kind="primaryFormSubmit"], .stApp button[kind="primaryFormSubmit"] p { color:#ffffff !important; }
.stApp button[kind="secondary"] p { color:var(--ink); }
.stApp p, .stApp li { font-size:17px; line-height:1.6; }
h1, h2, h3 { font-family:'Source Serif 4', Georgia, serif !important; color:var(--ink) !important; letter-spacing:-0.01em; }
h1 { font-size:2.4rem !important; font-weight:700 !important; }
h2 { font-size:1.75rem !important; font-weight:700 !important; margin-top:0.2rem !important; }
h3 { font-size:1.25rem !important; font-weight:600 !important; }
.block-container { padding-top:2.6rem; max-width:1100px; }
.lede { font-size:19px; color:#3c4250; max-width:760px; line-height:1.55; }
.muted { color:var(--muted) !important; font-size:14.5px; }
.pill { display:inline-block; padding:3px 11px; border-radius:99px; font-weight:600; font-size:13.5px; white-space:nowrap; }
table.nice { width:100%; border-collapse:collapse; margin:4px 0 18px; }
table.nice th { text-align:left; font-weight:600; font-size:13px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted);
  border-bottom:1px solid var(--line); padding:10px 12px; background:#fff; }
table.nice td { padding:12px; border-bottom:1px solid var(--line); vertical-align:top; font-size:15.5px; background:#fff; color:var(--ink); }
table.nice td.src { color:var(--muted); font-size:13.5px; }
.stat { border:1px solid var(--line); border-radius:14px; padding:14px 16px; background:#fff; }
.stat .n { font-size:30px; font-weight:700; font-family:'Inter'; }
.stat .l { font-size:14px; color:var(--muted); }
.card { border:1px solid var(--line); border-radius:16px; padding:18px 20px; background:#fff; }
.step-preview { display:flex; gap:14px; align-items:flex-start; padding:10px 0; border-bottom:1px solid var(--line); }
.step-preview .num { width:30px; height:30px; border-radius:50%; background:#eef2ff; color:var(--navy); font-weight:700;
  display:flex; align-items:center; justify-content:center; flex-shrink:0; }
div.stButton > button { border-radius:10px; font-weight:600; }
/* left-hand step list */
.st-key-nav div.stButton > button > div { justify-content:flex-start; }
.st-key-nav div.stButton > button { justify-content:flex-start; text-align:left; border:1px solid transparent; background:transparent;
  color:var(--ink); padding:.55rem .8rem; font-weight:500; }
.st-key-nav div.stButton > button:hover { background:#eceef3; }
.st-key-nav div.stButton > button[kind="primary"] { background:var(--navy); color:#fff; font-weight:700; }
.arrows { color:var(--green); text-align:center; font-weight:800; line-height:.62; font-size:16px; margin:2px 0 4px; letter-spacing:0; }
.gap { height:6px; border-left:2px solid #dfe3ea; margin-left:26px; }
/* AI answers */
[class*="st-key-ai_"] { border-left:4px solid var(--ai); background:#f8f6ff; border-radius:10px; padding:14px 18px 6px; margin:6px 0 14px; }
.ai-tag { display:inline-block; background:#efeafe; color:#5a3fc0; font-size:12.5px; font-weight:600; padding:2px 10px; border-radius:99px; }
.code-tag { display:inline-block; background:#e7f4ec; color:#1e7d4f; font-size:12.5px; font-weight:600; padding:2px 10px; border-radius:99px; }
/* force a light look for every control, whatever theme the browser or server uses */
.stApp button[kind="secondary"], .stApp button[kind="secondaryFormSubmit"], [data-testid="stPopover"] button {
  background:#ffffff !important; color:var(--ink) !important; border:1px solid #d0d5dd !important; }
.stApp button[kind="secondary"]:hover, [data-testid="stPopover"] button:hover { border-color:var(--navy) !important; color:var(--navy) !important; }
.stApp button[kind="secondary"] p, [data-testid="stPopover"] button p { color:inherit !important; }
.stApp button[kind="primary"], .stApp button[kind="primaryFormSubmit"] { background:var(--navy) !important; border:1px solid var(--navy) !important; }
.stApp button:disabled { opacity:.4 !important; cursor:not-allowed !important; }
.stApp button[kind="tertiary"], .stApp button[kind="tertiary"] p { color:var(--navy) !important; background:transparent !important; text-decoration:underline; }
[data-baseweb="select"] > div, [data-baseweb="input"], [data-baseweb="input"] input, [data-baseweb="textarea"], textarea,
[data-testid="stNumberInputContainer"], [data-testid="stNumberInputContainer"] input, [data-testid="stNumberInputContainer"] button {
  background:#f5f7fa !important; color:var(--ink) !important; border-color:#d0d5dd !important; }
[data-baseweb="select"] span, [data-baseweb="select"] div { color:var(--ink) !important; }
[data-baseweb="popover"] ul, [data-baseweb="popover"] li, [data-baseweb="menu"] { background:#ffffff !important; color:var(--ink) !important; }
[data-testid="stFileUploaderDropzone"] { background:#f5f7fa !important; color:var(--ink) !important; }
[data-testid="stFileUploaderDropzone"] * { color:var(--ink) !important; }
/* checkbox ticks and radio dots: navy instead of the default red */
[data-testid="stCheckbox"] div:has(> svg polyline) { background-color:var(--navy) !important; border-color:var(--navy) !important; }
[data-testid="stRadioOption"]:has(input:checked) div:has(> div:only-child:empty) { background-color:var(--navy) !important; border-color:var(--navy) !important; }
/* the left-hand step list stays plain text, not boxes */
.st-key-nav div.stButton > button[kind="secondary"] { background:transparent !important; border:1px solid transparent !important; }
.st-key-nav div.stButton > button[kind="secondary"]:hover { background:#eceef3 !important; }
[data-testid="stExpander"] details, [data-testid="stExpander"] summary { background:#ffffff !important; color:var(--ink) !important; }
[data-testid="stVerticalBlockBorderWrapper"] { background:#ffffff; }
.howto { display:flex; gap:12px; align-items:flex-start; margin:10px 0; }
.howto .ic { font-size:20px; line-height:1.4; }
.howto b { display:block; font-size:16px; }
.howto span { color:var(--muted); font-size:15px; }
.diagram { display:flex; flex-direction:column; align-items:center; gap:6px; margin:10px 0 18px; }
.box { border:2px solid var(--line); border-radius:12px; padding:10px 16px; text-align:center; background:#fff; min-width:230px; }
.box.can { border-color:#c8102e; } .box.ihc { border-color:var(--navy); background:#f3f6ff; } .box.new { border-color:var(--green); background:#f1faf5; }
.box small { color:var(--muted); display:block; }
.row { display:flex; gap:12px; flex-wrap:wrap; justify-content:center; }
.down { color:var(--green); font-weight:800; }
</style>
""", unsafe_allow_html=True)


# --------------------------------------------------------------------------------------
# State and small helpers
# --------------------------------------------------------------------------------------
@st.cache_resource
def load_library():
    return Library()


LIB = load_library()
S = st.session_state
S.setdefault("page", "home")
S.setdefault("saved", {})
S.setdefault("ai_cache", {})
S.setdefault("chat", [])
S.setdefault("chat_i", 0)


def saved(name, default=None):
    return S["saved"].get(name, default)


def keep(name, value):
    S["saved"][name] = value
    return value


def go(page):
    S["page"] = page


def fp(*parts):
    return hashlib.md5(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:12]


def pages():
    """The steps shown. 'Canadian buyer' only appears when the buyer is a Canadian bank."""
    return ["home", "setup", "glance", "capital", "leverage"] + (["canadian"] if saved("canadian") else []) + ["analyst", "options", "summary"]


def page_title(pid):
    order = pages()
    return PAGE_NAMES[pid] if pid in ("home", "sizes") or pid not in order else f"{order.index(pid)}  {PAGE_NAMES[pid]}"


def header(pid):
    order = pages()
    n = f"{order.index(pid)} · " if pid in order and pid != "home" else ""
    st.markdown(f"## {n}{PAGE_NAMES[pid]}")


def ready():
    return bool(S.get("banks") and saved("acq") and saved("tgt") and saved("acq") != saved("tgt"))


def nice_date(q):
    try:
        return datetime.datetime.strptime(q, "%Y%m%d").strftime("%d %b %Y")
    except (TypeError, ValueError):
        return str(q)


ACRONYMS = {"Rbc": "RBC", "Bmo": "BMO", "Td": "TD", "Cibc": "CIBC", "Us": "US", "Usa": "USA", "(Usa)": "(USA)", "Llc": "LLC",
            "Lp": "LP", "N.a.": "N.A.", "Wafd,": "WaFd,", "Of": "of", "The": "the", "And": "and"}


def nice_name(name):
    name = re.sub(r"^(.*?),\s*the$", r"The \1", (name or "").strip(), flags=re.I)     # "TORONTO-DOMINION BANK, THE"
    words = name.title().split()
    out = [ACRONYMS.get(w, w) for w in words]
    if out:
        out[0] = out[0][0].upper() + out[0][1:]
    return " ".join(out)


def pill(status):
    icon, label, colour = E.STATUS[status]
    return f'<span class="pill" style="background:{colour}1a;color:{colour}">{icon}&nbsp; {label}</span>'


def rep_(v):
    """A ratio for the AI's facts: 'not reported' rather than 'n/a', so it isn't read as 'not applicable'."""
    return "not reported in the filings" if v is None else f"{v:.2f}%"


def pct(v):
    return "n/a" if v is None else f"{v:.2f}%"


def table(rows, cols, src_col=None):
    """Clean HTML table. rows = list of dicts; values may contain HTML (pills)."""
    head = "".join(f"<th>{c}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f'<td class="{"src" if c == src_col else ""}">{r.get(c, "")}</td>' for c in cols) + "</tr>" for r in rows)
    st.markdown(f'<table class="nice"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>', unsafe_allow_html=True)


# --------------------------------------------------------------------------------------
# Left-hand side: step list with green arrows, then API credentials
#   >>> FOR SUBMISSION: replace the credentials block with the required openai_credentials module
#       (https://github.com/stoneman-mls/openai_credentials).
# --------------------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🏦 Merger check")
    nav = st.container(key="nav")
    ORDER = pages()
    current = ORDER.index(S["page"]) if S["page"] in ORDER else None
    with nav:
        for i, p in enumerate(ORDER):
            done = current is not None and i < current
            label = ("✓  " if done and i > 0 else "") + page_title(p)
            st.button(label, key=f"nav_{p}", on_click=go, args=(p,), type="primary" if S["page"] == p else "secondary",
                      width="stretch")
            if i < len(ORDER) - 1:
                if current == i:
                    st.markdown('<div class="arrows">⌄<br>⌄<br>⌄</div>', unsafe_allow_html=True)
                else:
                    st.markdown('<div class="gap"></div>', unsafe_allow_html=True)
        st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)
        st.button("📏  Size examples", key="nav_sizes", on_click=go, args=("sizes",),
                  type="primary" if S["page"] == "sizes" else "secondary", width="stretch")
    st.divider()
    with st.expander("🔑 API key", expanded=not bool(S.get("api_key"))):
        provider = st.radio("Provider", ["Anthropic (Claude)", "OpenAI"], horizontal=True,
                            index=0 if saved("provider", "Anthropic (Claude)").startswith("Anthropic") else 1)
        keep("provider", provider)
        env_key = os.environ.get("ANTHROPIC_API_KEY" if provider.startswith("Anthropic") else "OPENAI_API_KEY", "")
        key = st.text_input("Key", type="password", value=env_key, help="Held only in this browser session; never saved.")
        model = st.text_input("Model", value=ai.DEFAULT_MODELS[provider])
        S["provider"], S["api_key"], S["model"] = provider, key, model
    counter = st.empty()


# --------------------------------------------------------------------------------------
# AI display and caching
# --------------------------------------------------------------------------------------
def run_ai(cache_key, fn, label="Thinking…"):
    if cache_key in S["ai_cache"]:
        return S["ai_cache"][cache_key]
    if not ai.ready():
        st.info("Add your API key in the left-hand panel to see the AI's explanation here. Everything else works without it.")
        return None
    with st.spinner(label):
        try:
            out = fn()
        except Exception as exc:
            st.error(f"The AI call did not work: {exc}")
            return None
    S["ai_cache"][cache_key] = out
    return out


def show_ai(result, title, key):
    if not result:
        return
    with st.container(key=f"ai_{key}"):
        chk = result.get("check")
        note = ""
        if chk:
            note = (f"cites {len(chk['cited'])} regulation passage(s) — all verified" if chk["has_citations"] and not chk["invalid"]
                    else "⚠️ unverified citations were removed" if chk["invalid"] else "no citations")
        st.markdown(f'<span class="ai-tag">✨ Written by AI</span> <span class="muted">&nbsp;{title}{" · " + note if note else ""}</span>',
                    unsafe_allow_html=True)
        st.markdown(result["text"])
        if result.get("passages"):
            with st.expander(f"Sources the AI was allowed to use ({len(result['passages'])})"):
                for p in result["passages"]:
                    st.markdown(f"**[{p['id']}] {p['cite']}** — {p['title']}  \n<span class='muted'>{p['status']} · as of {p['as_of']}</span>",
                                unsafe_allow_html=True)
                    st.caption(p["text"][:700] + ("…" if len(p["text"]) > 700 else ""))


def chat_box(page, facts):
    """One running Q&A. The box clears after each question; ◀ ▶ step through earlier answers."""
    st.markdown("### Ask a question")
    st.markdown('<span class="muted">Answers come only from the regulations loaded into this app, and a second AI call checks each one.</span>',
                unsafe_allow_html=True)
    with st.form(key=f"chatform_{page}", clear_on_submit=True, border=False):
        c1, c2 = st.columns([5, 1])
        q = c1.text_input("Question", label_visibility="collapsed", placeholder="e.g. What does the stress capital buffer do?")
        sent = c2.form_submit_button("Ask", type="primary", width="stretch")
    if sent and q.strip():
        if not ai.ready():
            st.warning("Add your API key in the left-hand panel first.")
        else:
            with st.spinner("Searching the regulations, answering, then checking the answer…"):
                ans = ai.ask(page, q.strip(), facts, LIB)
            S["chat"].append({"q": q.strip(), "a": ans, "page": page})
            S["chat_i"] = len(S["chat"]) - 1
    if S["chat"]:
        i = min(S["chat_i"], len(S["chat"]) - 1)
        item = S["chat"][i]
        c1, c2, c3 = st.columns([1, 3, 1])
        c1.button("◀  Older", key=f"older_{page}", disabled=i == 0, on_click=lambda: S.update(chat_i=i - 1), width="stretch")
        c2.markdown(f"<div style='text-align:center;padding-top:8px' class='muted'>Question {i + 1} of {len(S['chat'])}</div>",
                    unsafe_allow_html=True)
        c3.button("Newer  ▶", key=f"newer_{page}", disabled=i == len(S["chat"]) - 1, on_click=lambda: S.update(chat_i=i + 1),
                  width="stretch")
        st.markdown(f"**Q: {item['q']}**")
        show_ai(item["a"], "Answer" + ("" if item["a"].get("verified") else " · not fully confirmed by the checker"), f"chat_{page}")
        if item["a"].get("trail"):
            with st.expander("How this answer was checked"):
                for t in item["a"]["trail"]:
                    st.write("• " + t)


def nav_buttons():
    st.write("")
    st.divider()
    order = pages()
    if S["page"] not in order:
        return
    i = order.index(S["page"])
    c1, _, c3 = st.columns([1, 2, 1])
    if i > 0:
        c1.button("←  Back", on_click=go, args=(order[i - 1],), width="stretch", key="back")
    if i < len(order) - 1:
        nxt = order[i + 1]
        c3.button(f"Next: {PAGE_NAMES[nxt]}  →", on_click=go, args=(nxt,), type="primary", width="stretch", key="next",
                  disabled=(not ready()) and nxt not in ("setup",))


def need_banks():
    st.info("First choose the two banks on the **Getting started** page.")
    st.button("Go to Getting started", on_click=go, args=("setup",), type="primary")


# --------------------------------------------------------------------------------------
# Loading banks
# --------------------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _parse_one(name, data):
    """Read one FR Y-9C file (PDF form or the Fed's bulk .txt). Cached, so re-runs are instant."""
    return E.parse_y9c_pdf(data) if name.lower().endswith(".pdf") else E.parse_y9c_bulk(data)


def _read_test(name):
    with open(os.path.join(TEST, name), "rb") as fh:
        return fh.read()


def rebuild_banks():
    """All banks the app knows about: the fictional example banks, the Canadian banks' U.S. arms,
    and whatever was uploaded for the buyer and for the bank being bought."""
    parsed, skipped = [], []
    files = [(EXAMPLE_POOL, _read_test(EXAMPLE_POOL))] + [(n, _read_test(n)) for v in US_ARM_FILES.values() for n in v]
    for slot in ("acq", "tgt"):
        files += list(S.get(f"files_{slot}", {}).items())
    for name, data in files:
        q, banks = _parse_one(name, data)
        if banks:
            parsed.append((q, banks))
        else:
            skipped.append(name)
    S["banks"] = E.merge_quarters(parsed)
    S["skipped"] = skipped


def ihc_rssd(pk):
    return STRUCTURE[pk]["ihcs"][0]["rssd"] if STRUCTURE[pk]["ihcs"] else None


def example_rssds():
    _, banks = _parse_one(EXAMPLE_POOL, _read_test(EXAMPLE_POOL))
    return list(banks)


def _by_name(fragment):
    return next((k for k, v in S["banks"].items() if fragment in v["latest"]["name"]), None)


EXAMPLE_DEALS = {
    "U.S. deal that crosses $100bn — Great Lakes Financial buys Prairie Trust": ("us", "GREAT LAKES", "PRAIRIE TRUST", None),
    "U.S. deal that crosses $250bn — Sun Belt Bancshares buys Atlantic Harbor": ("us", "SUN BELT", "ATLANTIC HARBOR", None),
    "U.S. deal that crosses $700bn — Pacific Crest Financial buys Cascade Bancorp": ("us", "PACIFIC CREST", "CASCADE", None),
    "Canadian buyer — RBC buys Liberty Square (Category IV → III)": ("ca", "RBC", "LIBERTY SQUARE", None),
    "Canadian buyer — CIBC buys Great Lakes Financial (U.S. presence crosses $100bn)": ("ca", "CIBC", "GREAT LAKES", None),
    "Canadian buyer — TD buys Keystone National (Category II, and fails Reg K)": ("ca", "TD", "KEYSTONE", None),
}


def load_example_deal(label):
    kind, buyer, target, holdings_file = EXAMPLE_DEALS[label]
    S["files_acq"], S["files_tgt"] = {}, {}
    S["parent"], S["disposal"], S["register"] = None, None, None
    _ = S["saved"].pop("parent_src", None)
    _ = rebuild_banks()
    _ = keep("tgt", _by_name(target))
    _ = keep("tgt_source", "Choose an example bank")
    if kind == "ca":
        _ = keep("canadian", True)
        _ = keep("parent_key", buyer)
        _ = keep("acq", ihc_rssd(buyer))
        if buyer in PILLAR3:
            S["pending_pillar3"] = PILLAR3[buyer][0]
    else:
        _ = keep("canadian", False)
        _ = keep("acq", _by_name(buyer))
        _ = keep("acq_source", "Choose an example bank")


def buyer_label():
    return f"{saved('parent_key')}'s U.S. arm" if saved("canadian") else "Buyer"


# --------------------------------------------------------------------------------------
# The deal (everything later pages need)
# --------------------------------------------------------------------------------------
def deal():
    B = S["banks"]
    A, T = B[saved("acq")], B[saved("tgt")]
    a, t = A["latest"], T["latest"]
    c = E.combine(a, t)
    gsib = saved("gsib", False)
    cat_a, cat_t = E.category(A["avg_assets"], gsib), E.category(T["avg_assets"])
    pf_avg = A["avg_assets"] + T["avg_assets"]
    cat_c = E.category(pf_avg, gsib)
    quarters = sorted({b["quarter"] for X in (A, T) for b in X["history"] if b["quarter"]})
    return dict(A=A, T=T, a=a, t=t, c=c, cat_a=cat_a, cat_t=cat_t, cat_c=cat_c, pf_avg=pf_avg,
                liab=E.liabilities_test(c["total_liabilities"] + saved("deal_debt_bn", 0.0) * 1e6),
                deal_debt=saved("deal_debt_bn", 0.0) * 1e6, quarters=[nice_date(q) for q in quarters],
                min_q=min(A["quarters"], T["quarters"]))


def parent_values():
    P = S.get("parent")
    return {k: P["fig"][k]["value"] for k in P["fig"]} if P else {}


def canadian(d):
    """Everything the Canadian-buyer analysis needs. Pure calls to engine.py - no AI here."""
    pk = saved("parent_key")
    G = STRUCTURE[pk]
    v = parent_values()
    fx = saved("fx", 1.40)
    branches = saved("branches_bn", 0.0) * 1e6
    fp_ = E.us_footprint(d["a"]["total_assets"], branches, d["t"]["total_assets"])
    us_rows, (ihc_before, ihc_after) = E.us_rules_for_foreign_buyer(fp_)
    parent_total_usd = (v["total_assets"] * 1e3 / fx + d["t"]["total_assets"]) if v.get("total_assets") else None
    us_banking_after = fp_["combined_after"]
    q = E.qfbo_test(parent_total_usd, us_banking_after, saved("us_rev_share"), saved("us_ni_share"),
                    {"Yes": True, "No": False}.get(saved("mostly_banking", "Yes")))
    regk_rows = [
        {"status": q["test1"], "check": "Reg K test 1 — more than half its worldwide business is banking",
         "detail": "Confirmed by the user." if q["test1"] == "met" else "Not confirmed.", "src": "12 CFR 211.23(a)(1)"},
        {"status": q["test2"], "check": "Reg K test 2 — more than half its banking is outside the U.S. (after the deal)",
         "detail": "; ".join(f"{l['measure']}: {l['detail']}" for l in q["legs"]), "src": "12 CFR 211.23(a)(2)"}]
    if q["overall"] == "not_met":
        regk_rows.append({"status": "not_met", "check": "Reg K exemptions for its businesses outside the U.S.",
                          "detail": "If it fails for two years in a row, the exemptions end; anything acquired after the first failing year "
                                    "must be sold or wound down within three months, unless the Fed agrees otherwise.",
                          "src": "12 CFR 211.23(d)"})
    hold_rows = []
    disp = disposal_current()
    if disp:
        n = {k: sum(1 for r in disp["rows"] if r["verdict"] == k) for k in E.VERDICTS}
        status = "not_met" if n["sell"] else ("review" if n["at_risk"] or n["approval"] else "met")
        detail = (f"Of {len(disp['rows'])} holdings reviewed: {n['sell']} likely must sell or restructure; {n['at_risk']} at risk if "
                  f"Reg K status is lost; {n['approval']} need Fed approval or notice.")
    else:
        status = "not_met" if q["overall"] == "not_met" else "review"
        detail = ("Not reviewed yet. Because it fails the Reg K tests, its non-banking holdings outside the U.S. are at risk — "
                  "run the holdings review on the Canadian buyer page." if q["overall"] == "not_met" else
                  "Not reviewed yet — run the holdings review on the Canadian buyer page.")
    hold_rows.append({"status": status, "check": "Holdings the parent may have to sell (AI review, checked by the app)",
                      "detail": detail, "src": "12 CFR 211.23; 12 CFR 225.28, 225.86"})
    hold_rows.append({"status": "review" if G["outside_ihc"] else "met", "check": "U.S. companies held outside the IHC",
                      "detail": (", ".join(nice_name(x["name"]) for x in G["outside_ihc"][:3]) + " — confirm an exception applies or move under the IHC.")
                      if G["outside_ihc"] else "None — every U.S. company is under the IHC.", "src": "12 CFR 252.153"})
    osfi_rows = []
    if v.get("cet1"):
        to_cad = lambda usd_k: usd_k / 1e3 * fx
        parent = {k: v.get(k) for k in ("cet1", "tier1", "total_capital", "rwa", "leverage_exposure")}
        for r in E.parent_tests(parent, to_cad(d["t"]["rwa"]), to_cad(d["t"]["total_assets"]), saved("dsib", True), saved("dsb", 3.0)):
            osfi_rows.append({"status": r["status"], "check": f"Parent's {r['test']} (OSFI)",
                              "detail": f"{pct(r['before'])} → {pct(r['after'])} vs target {r['target']:.2f}%", "src": r["cite"]})
    else:
        osfi_rows.append({"status": "unknown", "check": "Parent's capital ratios (OSFI)", "detail": "Load the parent's Pillar 3 report on Getting started.",
                          "src": "OSFI CAR (2027) Ch.1"})
    return dict(pk=pk, G=G, v=v, fp=fp_, us_rows=us_rows, ihc_before=ihc_before, ihc_after=ihc_after, q=q, regk_rows=regk_rows,
                hold_rows=hold_rows, osfi_rows=osfi_rows, parent_total_usd=parent_total_usd,
                rows=us_rows + regk_rows + hold_rows + osfi_rows)


def summary_rows(d):
    rows = []
    before, after = d["cat_a"][0], d["cat_c"][0]
    rows.append({"status": "newly_applies" if E.rank(after) > E.rank(before) else "met", "check": "Size category of the combined U.S. bank",
                 "detail": f"{E.cat_label(before)} → {E.cat_label(after)} (combined {E.bn(d['pf_avg'])})", "src": E.CATEGORY_CITE})
    for r in E.newly_applying(before, after):
        rows.append({"status": "newly_applies", "check": r["Requirement"], "detail": f"{r['Before']} → {r['After']}", "src": r["Source"]})
    for r in E.capital_tests(d["c"]) + E.leverage_tests(d["c"], after):
        rows.append({"status": r["status"], "check": f"{r['test']} (combined)",
                     "detail": f"{pct(r['value'])} vs {r['with_buffer']:.1f}% needed" if r["value"] is not None else
                     "Not reported by both banks — can't combine", "src": r["cite"]})
    rows.append({"status": d["liab"]["status"], "check": "10% liabilities concentration limit", "detail": d["liab"]["detail"],
                 "src": "12 U.S.C. 1852(b); 12 CFR 251"})
    if saved("canadian"):
        cx = canadian(d)
        rows += [r for r in cx["us_rows"] if not r["check"].startswith("The IHC's own")] + cx["regk_rows"] + cx["hold_rows"] + cx["osfi_rows"]
    cmp_ = rule_cmp(d)
    if cmp_:
        rows.append({"status": "met" if cmp_["differ"] == 0 else "review", "check": "AI's reading of the rules vs the built-in rulebook",
                     "detail": f"Agree on {cmp_['agree']} of {cmp_['total']} points" + (f"; {cmp_['differ']} to review" if cmp_["differ"] else ""),
                     "src": "12 CFR 252.5; 217.10–11; 225.8; 252.44; Part 249"})
    if d["min_q"] < 4:
        rows.append({"status": "unknown", "check": "Four-quarter average size",
                     "detail": f"Only {d['min_q']} quarter(s) loaded for at least one bank; size uses what is available.", "src": "12 CFR 252.5"})
    return rows


def show_summary_table(rows):
    table([{"Status": pill(r["status"]), "Check": r["check"], "Detail": r["detail"], "Source": r["src"]} for r in rows],
          ["Status", "Check", "Detail", "Source"], src_col="Source")


def counts(rows):
    n = {k: 0 for k in E.STATUS}
    for r in rows:
        n[r["status"]] += 1
    cols = st.columns(4)
    groups = [("met", ("met",), "Met"), ("not_met", ("not_met",), "Not met"),
              ("newly_applies", ("newly_applies", "warning"), "Newly applies / in buffer"), ("unknown", ("unknown", "review"), "Can't tell / review")]
    for col, (k, members, name) in zip(cols, groups):
        icon, _, colour = E.STATUS[k]
        col.markdown(f'<div class="stat"><div class="n" style="color:{colour}">{sum(n[m] for m in members)}</div>'
                     f'<div class="l">{icon} {name}</div></div>', unsafe_allow_html=True)
    st.write("")


# ======================================================================================
# SHARED HELPERS FOR THE AI WORKFLOW
# ======================================================================================
def run_many(jobs, label):
    """jobs: [(cache_key, fn)]. Runs the ones not yet done AT THE SAME TIME under one spinner; caches each result."""
    todo = [(k, f) for k, f in jobs if k not in S["ai_cache"]]
    if todo and ai.ready():
        def safe(f):
            def run():
                try:
                    return f()
                except Exception as exc:          # one failed call should not lose the others
                    return {"_error": str(exc)}
            return run
        with st.spinner(label):
            outs = ai.parallel([safe(f) for _, f in todo])
        errors = [o["_error"] for o in outs if isinstance(o, dict) and "_error" in o]
        for (k, _), o in zip(todo, outs):
            if not (isinstance(o, dict) and "_error" in o):
                S["ai_cache"][k] = o
        if errors:
            st.error(f"An AI call did not work: {errors[0]}. Reload the page to try again.")
    return [S["ai_cache"].get(k) for k, _ in jobs]


def closing_date():
    try:
        return datetime.date.fromisoformat(saved("closing"))
    except (TypeError, ValueError):
        return None


def quarter_ends_after(day, n=6):
    """The n calendar quarter-ends on or after a date (the first one includes the combined balance sheet)."""
    out, y, m = [], day.year, ((day.month - 1) // 3 + 1) * 3
    while len(out) < n:
        last = (datetime.date(y + (m // 12), m % 12 + 1, 1) - datetime.timedelta(days=1))
        if last >= day:
            out.append(last)
        m += 3
        if m > 12:
            m, y = m - 12, y + 1
    return out


def analysis_base(d):
    """The combined bank as plain numbers for the analyst's calculator, with each bank's own contribution."""
    base, before_us = options_base(d, d["deal_debt"])
    part = lambda b, avg: {"avg_assets": avg, "total_assets": b["total_assets"] or 0, "lev_assets": b["avg_assets_lev"] or 0,
                           "liabilities": b["total_liabilities"] or 0, "rwa": b["rwa"] or 0, "cet1": b["cet1"] or 0,
                           "tier1": b["tier1"] or 0, "total_capital": b["total_capital"] or 0}
    base.update(buyer=part(d["a"], d["A"]["avg_assets"]), target=part(d["t"], d["T"]["avg_assets"]), buyer_cat=d["cat_a"][0])
    day = closing_date() or datetime.date.today()
    labels = [q.strftime("%d %b %Y") for q in quarter_ends_after(day)]
    timeline = ([b["total_assets"] for b in d["A"]["history"]], [b["total_assets"] for b in d["T"]["history"]], labels)
    return base, before_us, timeline


def law(text, passages):
    """Passage IDs -> real citations, for anything a lawyer will copy out."""
    return ai.cites_to_law(text or "", passages or [])


def badge(ok, text):
    colour = "#1e7d4f" if ok is True else ("#b26a00" if ok is None else "#b42318")
    icon = "✓" if ok is True else ("!" if ok is None else "✕")
    return f'<span class="pill" style="background:{colour}1a;color:{colour}">{icon}&nbsp; {text}</span>'


def deal_sig():
    return [saved("acq"), saved("tgt"), saved("canadian"), saved("parent_key"), saved("gsib"), saved("deal_debt_bn"),
            saved("branches_bn"), saved("us_rev_share"), saved("us_ni_share"), saved("mostly_banking"), saved("closing"),
            bool(S.get("parent"))]


# ======================================================================================
# PAGES
# ======================================================================================
def read_pillar3(src_bytes, src_name):
    if saved("parent_src") == fp(src_name, len(src_bytes)):
        return
    from pypdf import PdfReader
    text, page_nums = ai.find_capital_pages(PdfReader(io.BytesIO(src_bytes)))
    out = run_ai(fp("extract", src_name, len(src_bytes)), lambda: {"fig": ai.extract_parent_figures("Getting started", text), "pages": page_nums},
                 "The AI is reading the report's key-metrics table…")
    if out:
        _ = keep("parent_src", fp(src_name, len(src_bytes)))
        S["parent"] = out


def page_home():
    st.markdown("# Bank merger regulatory check")
    st.markdown('<p class="lede">For a proposed bank merger, see which U.S. capital rules each bank meets, what the deal changes — '
                'and, if the buyer is a Canadian bank, what U.S. regulation it takes on and what that means for the businesses '
                'it owns at home.</p>', unsafe_allow_html=True)
    st.write("")
    left, right = st.columns([1.2, 1], gap="large")
    with left:
        st.markdown("### What you'll see")
        steps = [("Getting started", "Choose the two banks — upload their Fed filings or pick an example."),
                 ("At a glance", "Every requirement — met, not met, newly applies."),
                 ("Capital ratios", "Each bank, and the two combined, against what each size category needs."),
                 ("Leverage & liabilities", "The leverage ratio and the 10% liabilities cap."),
                 ("Canadian buyer", "Only for a Canadian buyer: the U.S. rules it takes on, Reg K, and holdings to review."),
                 ("AI analyst", "AI investigates the deal — choosing what to test, running the app's calculator, reporting back."),
                 ("Deal options", "If the deal crosses a line, AI suggests ways to restructure it — and the app tests each one."),
                 ("Summary & next steps", "A ranked issues list and a one-page memo, ready to email to the partner.")]
        for n, (title, body) in enumerate(steps, 1):
            st.markdown(f'<div class="step-preview"><div class="num">{n}</div><div><b style="font-size:17.5px">{title}</b><br>'
                        f'<span class="muted" style="font-size:15.5px">{body}</span></div></div>', unsafe_allow_html=True)
    with right:
        st.markdown("### How it works")
        st.markdown('<div class="howto"><div class="ic">📖</div><div><b>The rules are built into the app</b>'
                    '<span>Every threshold and ratio — the $100bn, $250bn and $700bn lines, the 4.5% CET1 minimum, the 10% '
                    'liabilities cap, the Reg K tests — is written into the app from the regulation itself, with the section '
                    'cited beside it. Nothing is looked up or guessed at the time you run it.</span></div></div>'
                    '<div class="howto"><div class="ic">🧮</div><div><b>The numbers are calculated without AI</b>'
                    '<span>Every figure and every met / not met result follows those fixed rules — the same answer every time.</span></div></div>'
                    '<div class="howto"><div class="ic">✨</div><div><b>The analysis is done by AI — and checked</b>'
                    '<span>AI reads both filings, applies the regulations, reviews the holdings, investigates the deal and drafts '
                    'the partner memo — using only the regulations in the app. The app checks every figure it reads and writes, '
                    'and compares its reading of the rules with the built-in rulebook.</span></div></div>',
                    unsafe_allow_html=True)
        st.markdown('<div class="card" style="background:#f7f9fc;margin-top:6px"><b>Why build the rules in?</b><br>'
                    '<span class="muted" style="font-size:15.5px">An AI asked to "apply the capital rules" can misremember a '
                    'threshold or a percentage. Here, the rules are fixed and every one carries its citation — '
                    '<b>so you only have to double-check the work, not triple-check it.</b></span></div>', unsafe_allow_html=True)
        st.write("")
        st.button("Get started  →", type="primary", on_click=go, args=("setup",), width="stretch")


def bank_picker(slot, label, exclude=()):
    """One bank: either an example bank or the user's own FR Y-9C upload (PDF or the Fed's bulk .txt)."""
    st.markdown(f"#### {label}")
    src = st.radio("Source", ["Upload its FR Y-9C", "Choose an example bank"], horizontal=True, label_visibility="collapsed",
                   index=["Upload its FR Y-9C", "Choose an example bank"].index(saved(f"{slot}_source", "Upload its FR Y-9C")),
                   key=f"src_{slot}")
    keep(f"{slot}_source", src)
    B = S["banks"]
    lab = lambda k: f"{nice_name(B[k]['latest']['name'])}  ·  {E.bn(B[k]['latest']['total_assets'])}"
    if src == "Choose an example bank":
        options = [k for k in sorted(example_rssds(), key=lambda k: -B[k]["latest"]["total_assets"]) if k not in exclude]
        st.markdown('<span class="muted">Fictional banks, sized just below the category lines so deals cross them.</span>',
                    unsafe_allow_html=True)
    else:
        files = st.file_uploader("FR Y-9C (PDF from the Fed's National Information Center, or the bulk .txt) — up to four quarters",
                                 type=["pdf", "txt"], accept_multiple_files=True, key=f"upload_{slot}")
        if files:
            new = {f.name: f.getvalue() for f in files}
            if new != S.get(f"files_{slot}"):
                S[f"files_{slot}"] = new
                rebuild_banks()
                B = S["banks"]
        uploaded = set()
        for name, data in S.get(f"files_{slot}", {}).items():
            uploaded |= set(_parse_one(name, data)[1])
        options = [k for k in sorted(uploaded, key=lambda k: -B[k]["latest"]["total_assets"]) if k not in exclude]
        if S.get("skipped"):
            st.warning("Not an FR Y-9C report, so skipped: " + ", ".join(n for n in S["skipped"] if n in S.get(f"files_{slot}", {})))
        if not options:
            st.markdown('<span class="muted">Search the bank at [ffiec.gov/npw](https://www.ffiec.gov/npw) → Financial Reports → FR Y-9C.</span>',
                        unsafe_allow_html=True)
            return None
    if len(options) == 1:
        keep(slot, options[0])
        b = B[options[0]]
        st.markdown(f"**{nice_name(b['latest']['name'])}** · {E.bn(b['latest']['total_assets'])} · "
                    f"{b['quarters']} quarter(s)")
        return options[0]
    pick = st.selectbox(label, options, format_func=lab, label_visibility="collapsed", key=f"pick_{slot}_{src}",
                        index=options.index(saved(slot)) if saved(slot) in options else 0)
    keep(slot, pick)
    return pick


def page_setup():
    header("setup")
    if "banks" not in S:
        rebuild_banks()
    st.markdown('<p class="lede">Choose the buyer and the bank being bought. Upload each one\'s FR Y-9C report from the Federal '
                'Reserve, or pick an example bank.</p>', unsafe_allow_html=True)
    def _on_example():
        if S.get("example_choice"):
            _ = load_example_deal(S["example_choice"])

    st.selectbox("Or load a ready-made example deal", list(EXAMPLE_DEALS), index=None, key="example_choice",
                 placeholder="Choose an example deal — it loads straight away", on_change=_on_example)

    is_can = st.checkbox("The buyer is a Canadian bank (TD, RBC, BMO or CIBC)", value=saved("canadian", False))
    if is_can != saved("canadian", False):
        keep("canadian", is_can)
        st.rerun()
    left, right = st.columns(2, gap="large")
    arm_ids = {ihc_rssd(k) for k in CANADIAN}
    with left:
        if is_can:
            st.markdown("#### Buyer (Canadian bank)")
            pk = st.selectbox("Canadian bank", CANADIAN, format_func=lambda k: f"{nice_name(STRUCTURE[k]['parent'])} ({k})",
                              index=CANADIAN.index(saved("parent_key")) if saved("parent_key") in CANADIAN else 0,
                              label_visibility="collapsed")
            if pk != saved("parent_key"):
                S["parent"], S["disposal"], S["register"] = None, None, None
                S["saved"].pop("parent_src", None)
            keep("parent_key", pk)
            keep("acq", ihc_rssd(pk))
            arm = S["banks"][ihc_rssd(pk)]
            st.markdown(f'Its U.S. arm: **{nice_name(arm["latest"]["name"])}** · {E.bn(arm["latest"]["total_assets"])} '
                        f'<span class="muted">(FR Y-9C, built into the app)</span>', unsafe_allow_html=True)
            st.markdown("**Its Pillar 3 report** — for its Canadian capital and total assets")
            c1, c2 = st.columns([1, 1.4])
            if S.get("pending_pillar3"):
                name = S.pop("pending_pillar3")
                read_pillar3(_read_test(name), name)
            if pk in PILLAR3 and c1.button("Use example", width="stretch", help=PILLAR3[pk][1]):
                read_pillar3(_read_test(PILLAR3[pk][0]), PILLAR3[pk][0])
            pdf = c2.file_uploader("Pillar 3 PDF", type=["pdf"], label_visibility="collapsed", key="p3_upload")
            if pdf is not None:
                read_pillar3(pdf.getvalue(), pdf.name)
            v = parent_values()
            if v:
                chk = ai.verify_parent(S["parent"]["fig"])
                ok = all(c["ok"] is True for c in chk)
                verdict = ("✓ double-checked against the bank's own ratios" if ok else
                           "? some figures are missing or don't match — check them on the Canadian buyer page")
                money = lambda x: f"C${x:,.0f}m" if x else "not found"
                st.markdown(f'<span class="ai-tag">✨ Read by AI</span>&nbsp; {v.get("period") or "Latest quarter"}: CET1 '
                            f'{money(v.get("cet1"))}, total assets {money(v.get("total_assets"))} · '
                            f'<span class="code-tag">{verdict}</span>', unsafe_allow_html=True)
        else:
            bank_picker("acq", "Buyer", exclude=arm_ids | {saved("tgt")})
            keep("gsib", st.checkbox("The buyer is a U.S. GSIB", value=saved("gsib", False)))
    with right:
        bank_picker("tgt", "Bank being bought (U.S.)", exclude=arm_ids | ({saved("acq")} if not is_can else set()))

    if ready():
        d = deal()
        st.write("")
        st.markdown(f'<div class="card" style="background:#f7f9fc"><b>{nice_name(d["a"]["name"])}</b> '
                    f'{"(" + saved("parent_key") + "\'s U.S. arm) " if is_can else ""}buying <b>{nice_name(d["t"]["name"])}</b> · '
                    f'combined {E.bn(d["pf_avg"])} · {E.cat_label(d["cat_a"][0])} → <b>{E.cat_label(d["cat_c"][0])}</b></div>',
                    unsafe_allow_html=True)
        c1, c2 = st.columns([1, 2])
        default_close = closing_date() or (datetime.date.today() + datetime.timedelta(days=270))
        when = c1.date_input("Expected closing date", value=default_close, format="DD/MM/YYYY",
                             help="Used for the quarter-by-quarter size timeline, disposal deadlines and the memo.")
        if when.isoformat() != saved("closing"):
            keep("closing", when.isoformat())
        c2.markdown('<div style="padding-top:34px" class="muted">Next: the AI reads both banks\' filings below, and the app '
                    'checks every figure it reads against the exact value filed.</div>', unsafe_allow_html=True)
        st.write("")
        filing_read_section(d)


def read_one_filing(b):
    """AI reads one bank's filing, code checks every figure, then AI writes an analyst's review of the checked figures."""
    text = E.filing_extract(b)
    read = ai.read_filing("Getting started", nice_name(b["name"]), text)
    chk = E.check_ai_read(read, b)
    corrected = 0
    misses = {r["key"]: (read.get(r["key"]) or {}).get("value") if isinstance(read.get(r["key"]), dict) else read.get(r["key"])
              for r in chk["rows"] if r["status"] in ("differs", "missed")}
    if misses:                      # loop: the AI re-reads only what the app could not confirm
        again = ai.reread_filing("Getting started", nice_name(b["name"]), text, misses)
        if again:
            before = chk["counts"]["match"]
            read = dict(read, **again)
            chk = E.check_ai_read(read, b)
            corrected = chk["counts"]["match"] - before
    chk["corrected"] = corrected
    prof, shares = E.bank_profile(b)
    figs = "\n".join(f"- {k}: {E.bn(v, 2) if isinstance(v, (int, float)) and 'election' not in k else v}"
                     for k, v in prof.items() if v is not None)
    figs += "\n" + "\n".join(f"- {k}: {v:.1f}%" for k, v in shares.items())
    figs += "\n" + "\n".join(f"- {E.FIELDS[k][1]}: {pct(b[k])}" for k in E.RATIO_FIELDS if b.get(k) is not None)
    checks = (f"- The AI read {chk['checked']} figures; {chk['counts']['match']} match the filed values exactly, "
              f"{chk['counts']['differs']} differ, {chk['counts']['missed']} were missed.\n"
              + "\n".join(f"- {c['check']}: {c['result']}" for c in E.cross_checks(b)))
    review = ai.review_bank("Getting started", nice_name(b["name"]), figs, checks)
    return {"read": read, "check": chk, "review": review}


def filing_read_section(d):
    banks = [d["a"], d["t"]]
    keys = [fp("read-filing", b["rssd"], b["quarter"], len(b.get("raw") or {})) for b in banks]
    if not ai.ready():
        st.info("Add your API key in the left-hand panel and the AI will read both filings here. Everything else works without it.")
        return
    results = run_many([(k, lambda b=b: read_one_filing(b)) for k, b in zip(keys, banks)],
                       "The AI is reading both filings line by line, and the app is checking every figure…")
    if not all(results):
        return
    checked = sum(r["check"]["checked"] for r in results)
    matched = sum(r["check"]["counts"]["match"] for r in results)
    fixed = sum(r["check"].get("corrected", 0) for r in results)
    ok = True if all(r["check"]["all_ok"] for r in results) else (None if matched >= 0.9 * checked else False)
    label = f"{matched} of {checked} figures match the filing exactly"
    if fixed:
        label += f" — {fixed} corrected by the AI on a second read"
    if ok is not True:
        label += "; the app uses the filed value for the rest"
    st.markdown(f'<div class="card"><span class="ai-tag">✨ Read by AI</span> <span class="code-tag">checked by the app</span>&nbsp; '
                f'<b>The AI read both FR Y-9C filings.</b> {badge(ok, label)}'
                f'<br><span class="muted">The AI found each figure by its meaning, line by line, as an analyst would. The app then '
                f'compared each one with the exact value filed under its Fed code, and recomputed the reported ratios from the AI\'s '
                f'figures. Wherever they disagree, the app uses the filed value.</span></div>', unsafe_allow_html=True)
    st.write("")
    tabs = st.tabs([nice_name(b["name"]) for b in banks])
    for tab, b, r in zip(tabs, banks, results):
        with tab:
            show_ai({"text": r["review"]}, "analyst's review of the filing — figures only, no law", f"review_{b['rssd']}")
            fmt = lambda v, is_pct: "—" if v is None else (f"{v:.2f}%" if is_pct else E.bn(v, 2))
            icon = {"match": badge(True, "match"), "differs": badge(False, "differs — app uses the filed value"),
                    "missed": badge(None, "AI missed it"), "not_reported": '<span class="muted">not in this filing</span>'}
            with st.expander(f"Figure by figure — {r['check']['counts']['match']} of {r['check']['checked']} match"):
                table([{"Figure": x["label"], "AI read": fmt(x["ai"], x["pct"]),
                        "Where the AI found it": x["where"] or "—", "Filed value": fmt(x["exact"], x["pct"]),
                        "Check": icon[x["status"]]} for x in r["check"]["rows"]],
                      ["Figure", "AI read", "Where the AI found it", "Filed value", "Check"])
                st.markdown('<span class="code-tag">Checked without AI</span>&nbsp; ' + " · ".join(
                    f"{'✓' if c['ok'] else '?' if c['ok'] is None else '✕'} {c['check']} from the AI's figures ({c['result']})"
                    for c in r["check"]["internal"]), unsafe_allow_html=True)


def page_glance():
    header("glance")
    if not ready():
        return need_banks()
    d = deal()
    st.markdown(f'<p class="lede"><b>{nice_name(d["a"]["name"])}</b> buying <b>{nice_name(d["t"]["name"])}</b> — '
                f'combined average assets {E.bn(d["pf_avg"])}.</p>', unsafe_allow_html=True)
    rows = summary_rows(d)
    counts(rows)
    show_summary_table(rows)
    st.markdown('<span class="muted">Combined bank = the two banks added together (no purchase premium or goodwill). '
                'Size categories use asset size only.</span>', unsafe_allow_html=True)
    facts = "\n".join(f"- {E.STATUS[r['status']][1]} | {r['check']} | {r['detail']}" for r in rows)
    st.write("")
    headline_key = fp("glance", facts)
    rf, rule_key = rule_facts(d)
    res, rules = run_many([
        (headline_key, lambda: ai.explain(
            "1 At a glance", "In 3-4 sentences, give the deal lawyer the headline: what the merger changes in regulatory terms and the "
            "single most important item to watch. Cite passages.", facts,
            "Category IV $100 billion average total consolidated assets capital plan stress capital buffer minimum capital ratios", LIB)),
        (rule_key, lambda: ai.read_rules("1 At a glance", rf, [r[0] for r in E.REQUIREMENTS], LIB,
                                         questions=E.REQUIREMENT_QUESTIONS))],
        "AI is writing the headline and, at the same time, reading the regulations to apply the rules itself…")
    show_ai(res, "Headline", "glance")
    rule_section(d, rules)
    chat_box("1 At a glance", facts)


def rule_facts(d):
    who = ("the U.S. intermediate holding company of a Canadian bank. It is itself a top-tier bank holding company domiciled in "
           "the United States, and it is not a consolidated subsidiary of any other U.S. bank holding company or savings and loan "
           "holding company" if saved("canadian") else
           "a top-tier U.S. bank holding company domiciled in the United States, not a consolidated subsidiary of any other bank "
           "holding company or savings and loan holding company")
    facts = (f"Entity: {who}. Average total consolidated assets: {E.bn(d['A']['avg_assets'])} before the deal, "
             f"{E.bn(d['pf_avg'])} after it (the two banks added together). It is {'' if saved('gsib') else 'not '}a U.S. GSIB. "
             "Cross-jurisdictional activity, total nonbank assets, weighted short-term wholesale funding and off-balance-sheet "
             "exposure are NOT available to the app.")
    return facts, fp("rules", facts)


def rule_cmp(d, rules=None):
    rules = rules or S["ai_cache"].get(rule_facts(d)[1])
    return E.compare_rule_reading(rules, d["cat_a"][0], d["cat_c"][0]) if rules else None


def rule_section(d, rules):
    st.markdown("### The rules, applied by AI — checked against the built-in rulebook")
    if not rules:
        return
    cmp_ = rule_cmp(d, rules)
    ok = cmp_["differ"] == 0
    P = rules["passages"]
    st.markdown(f'<p class="lede">The AI read the regulations themselves — 12 CFR 252.5 for the size category, 217.2 and 217.100 for '
                f'whether the bank uses the advanced approaches, then 217.10, 217.11, 217.22, 225.8, 252.44 and Part 249 for what '
                f'each brings — and applied them to this deal. The app compared its answer, point by point, with the rulebook '
                f'built into the app.</p>', unsafe_allow_html=True)
    st.markdown(badge(ok if cmp_["close"] == 0 else (None if ok else False),
                      f"AI and rulebook agree on {cmp_['agree']} of {cmp_['total']} points"
                      + (f", close on {cmp_['close']}" if cmp_["close"] else "")
                      + (f" — {cmp_['differ']} to review" if cmp_["differ"] else "")), unsafe_allow_html=True)
    V = rules.get("votes") or {}
    if V:
        st.markdown(f'<span class="muted">The AI read the rules <b>{V["n"]} times independently</b>, at the same time, and the app took '
                    f'the majority answer on each point — the readings were unanimous on {V["unanimous"]} of {V["points"]} points.</span>',
                    unsafe_allow_html=True)
    vote_of = {f"{n} — after the deal": v for n, v in (V.get("requirements") or {}).items()}
    vote_of.update({"Size category before the deal": V.get("before"), "Size category after the deal": V.get("after")})
    mark = {True: badge(True, "agree"), "close": badge(None, "close"), False: badge(False, "differ — review")}
    table([{"Point": r["point"], "AI, from the regulation text": f"<b>{r['ai']}</b>"
            + (f" <span class='muted'>({vote_of[r['point']]} of {V['n']} readings)</span>" if vote_of.get(r["point"]) else "")
            + f"<br><span class='muted'>{law(r['why'], P)}</span>",
            "Built-in rulebook": r["rulebook"], "": mark[r["agree"]]} for r in cmp_["rows"]],
          ["Point", "AI, from the regulation text", "Built-in rulebook", ""])
    trig = rules.get("other_triggers") or []
    if trig:
        st.markdown("**Other ways this bank could land in a higher category** — found by the AI in the regulation; the app has no "
                    "figures for these, so ask the client.")
        table([{"Trigger": f"<b>{t.get('trigger', '')}</b>", "Threshold": t.get("threshold", ""), "Effect": t.get("effect", ""),
                "Ask the client": t.get("check", ""), "Source": law(t.get("cite", ""), P).strip(" ()")} for t in trig],
              ["Trigger", "Threshold", "Effect", "Ask the client", "Source"], src_col="Source")
    if rules.get("citations", {}).get("invalid"):
        st.caption("⚙️ Citations the AI made to passages it was not given were removed.")
    with st.expander(f"Sources the AI applied ({len(P)})"):
        for p in P:
            st.markdown(f"**[{p['id']}] {p['cite']}** — {p['title']}")
            st.caption(p["text"][:600] + "…")


def ratio_cell(value, status):
    icon, _, colour = E.STATUS[status]
    return f'<span style="color:{colour};font-weight:600">{icon}&nbsp; {pct(value)}</span>'


def page_capital():
    header("capital")
    if not ready():
        return need_banks()
    d = deal()
    st.markdown('<p class="lede">Every bank must keep three ratios of capital to risk-weighted assets above a minimum, '
                'plus a 2.5% buffer. Below the buffer, dividends and bonuses are restricted; below the minimum, the bank is '
                'under-capitalised.</p>', unsafe_allow_html=True)
    rows = []
    for k, name, m in E.CAPITAL_RATIOS:
        r = {"Ratio": f"<b>{name}</b>", "Needed": f"{m:.1f}% minimum<br><span class='muted'>{m + E.BUFFER:.1f}% with buffer</span>"}
        for col, bank in (("Buyer", d["a"]), ("Bank bought", d["t"]), ("Combined", d["c"])):
            r[col] = ratio_cell(bank[k], E.judge(bank[k], m, m + E.BUFFER))
        rows.append(r)
    table(rows, ["Ratio", "Needed", "Buyer", "Bank bought", "Combined"])
    st.markdown(f'<span class="muted">Buyer: {nice_name(d["a"]["name"])}{" (" + saved("parent_key") + "\'s U.S. arm)" if saved("canadian") else ""} · Bank bought: {nice_name(d["t"]["name"])} · '
                f'Source: 12 CFR 217.10(a) (minimums), 217.11(a) (buffer). For Category IV and above, the buffer is the bank\'s '
                f'stress capital buffer, which is at least 2.5% (12 CFR 225.8).</span>', unsafe_allow_html=True)

    # ---- what the ratios mean (optional, written by AI on request) ----
    st.markdown("### What these ratios mean")
    explain_key = fp("ratios-explained")
    if explain_key in S["ai_cache"]:
        show_ai(S["ai_cache"][explain_key], "Plain-English guide to the capital ratios", "ratios_explained")
    else:
        st.markdown('<span class="muted">Not needed if you work with bank capital rules every day. Otherwise, AI can write a short '
                    'plain-English guide to each ratio, drawn only from the regulations in the app.</span>', unsafe_allow_html=True)
        if st.button("✨ Explain these ratios in plain English"):
            facts_now = "\n".join(f"{name}: buyer {pct(d['a'][k])}, bank bought {pct(d['t'][k])}, combined {pct(d['c'][k])}; "
                                  f"minimum {m}%, with buffer {m + E.BUFFER}%" for k, name, m in E.CAPITAL_RATIOS)
            res = run_ai(explain_key, lambda: ai.explain_multi(
                "2 Capital ratios", "Write a short plain-English guide for a transactional lawyer. Use a bold heading for each of: "
                "Risk-weighted assets; CET1 capital and the CET1 ratio; Tier 1 capital (including additional Tier 1); Total capital "
                "(including Tier 2); The buffers on top of the minimums (conservation buffer, stress capital buffer, countercyclical "
                "buffer, GSIB surcharge); What happens below the buffer or the minimum. Under each, two or three short sentences: first "
                "what it is in everyday words, drawn from the passages, then one sentence tying it to this deal's figures in APP FACTS. "
                "Cite passages. No preamble.",
                facts_now,
                [("section", "12 CFR 217.2", "Standardized total risk-weighted assets means"),
                 ("section", "12 CFR 217.20", "Common equity tier 1 capital is the sum"),
                 ("section", "12 CFR 217.20", "Additional tier 1 capital is the sum"),
                 ("section", "12 CFR 217.20", "Tier 2 capital is the sum"),
                 ("section", "12 CFR 217.10", "minimum capital requirements"),
                 ("section", "12 CFR 217.11", "maximum payout ratio"),
                 ("section", "12 CFR 217.11", "Stress capital buffer requirement"),
                 ("section", "12 CFR 217.11", "must calculate a countercyclical capital buffer amount"),
                 ("section", "12 CFR 217.403", "surcharge")], LIB),
                "Writing the guide…")
            if res:
                st.rerun()

    # ---- what each size category must hold ----
    st.markdown("### What each size category must hold")
    st.markdown('<p class="lede">The minimums are the same for every bank. What grows with size is the buffer on top — and '
                'below the buffer, dividends and bonuses are restricted.</p>', unsafe_allow_html=True)
    here = {}
    here.setdefault(d["cat_a"][0], []).append("buyer today")
    here.setdefault(d["cat_c"][0], []).append("after the deal")
    crow = []
    for cat, who, c1, t1, tot, buffer, src in E.CATEGORY_CAPITAL:
        label = f"<b>{'Below $100bn' if cat == 'None' else 'Category ' + cat}</b>"
        if cat in here:
            label += "<br>" + " ".join(f'<span class="pill" style="background:#1f3a931a;color:#1f3a93">{x}</span>' for x in here[cat])
        crow.append({"Size category": label, "Who": who if cat != "None" else "No category",
                     "CET1": c1, "Tier 1": t1, "Total capital": tot, "The buffer on top of the minimum": buffer, "Source": src})
    table(crow, ["Size category", "Who", "CET1", "Tier 1", "Total capital", "The buffer on top of the minimum", "Source"], src_col="Source")
    st.markdown('<span class="muted">Minimums for every bank: CET1 4.5%, Tier 1 6%, Total capital 8% (12 CFR 217.10(a)). '
                'Figures shown are minimum plus the lowest possible buffer; a bank\'s actual stress capital buffer, '
                'countercyclical buffer and GSIB surcharge are set by the Fed and can be higher.</span>', unsafe_allow_html=True)

    with st.expander("Where these numbers come from"):
        st.markdown('<span class="code-tag">✓ Calculated without AI</span>&nbsp; Read straight from the Fed filings and double-checked.', unsafe_allow_html=True)
        frows = []
        for k in ("cet1", "tier1", "total_capital", "rwa"):
            codes, lbl, loc = E.FIELDS[k]
            frows.append({"Figure": lbl, "Buyer": E.bn(d["a"][k]), "Bank bought": E.bn(d["t"][k]), "Combined": E.bn(d["c"][k]),
                          "FR Y-9C line": f"{' + '.join(codes)} · {loc}"})
        table(frows, ["Figure", "Buyer", "Bank bought", "Combined", "FR Y-9C line"], src_col="FR Y-9C line")
        for b in (d["a"], d["t"]):
            st.markdown(f"**{nice_name(b['name'])}** — " + " · ".join(
                f"{'✓' if c['ok'] else '?' if c['ok'] is None else '✕'} {c['check']}" for c in E.cross_checks(b)))

    facts = "\n".join(f"{name}: buyer {pct(d['a'][k])}, bank bought {pct(d['t'][k])}, combined {pct(d['c'][k])}; needed {m}% min / {m + E.BUFFER}% with buffer"
                      for k, name, m in E.CAPITAL_RATIOS) + f"\nCombined category: {E.cat_label(d['cat_c'][0])}"
    res = run_ai(fp("capital", facts), lambda: ai.explain(
        "2 Capital ratios", "In under 150 words, explain how the buyer, the bank bought, and the combined bank meet the capital "
        "ratio requirements, and which ratio has the least room. Cite passages.", facts,
        "minimum capital requirements common equity tier 1 capital ratio tier 1 total capital capital conservation buffer", LIB))
    show_ai(res, "What this means", "capital")
    chat_box("2 Capital ratios", facts)


def page_leverage():
    header("leverage")
    if not ready():
        return need_banks()
    d = deal()
    cat = d["cat_c"][0]
    st.markdown("### Leverage")
    st.markdown('<p class="lede">The leverage ratio compares Tier 1 capital with total assets, ignoring risk. '
                'Every bank needs 4%. From Category III, a second "supplementary" ratio of 3% also applies.</p>', unsafe_allow_html=True)
    rows = []
    for r in E.leverage_tests(d["c"], cat):
        row = {"Ratio": f"<b>{r['test']}</b>", "Needed": f"{r['minimum']:.1f}%"}
        for col, bank in (("Buyer", d["a"]), ("Bank bought", d["t"]), ("Combined", d["c"])):
            v = bank.get(r["key"])
            row[col] = ratio_cell(v, E.judge(v, r["minimum"], r["minimum"])) if v is not None else "<span class='muted'>not reported</span>"
        rows.append(row)
    table(rows, ["Ratio", "Needed", "Buyer", "Bank bought", "Combined"])
    st.markdown('<span class="muted">Source: 12 CFR 217.10(a)(1)(iv) and (v).</span>', unsafe_allow_html=True)

    # ---- what the leverage measures mean (optional, written by AI on request) ----
    st.markdown("### What these ratios mean")
    explain_key = fp("leverage-explained")
    if explain_key in S["ai_cache"]:
        show_ai(S["ai_cache"][explain_key], "Plain-English guide to leverage and the liabilities limit", "leverage_explained")
    else:
        st.markdown('<span class="muted">Not needed if you work with bank capital rules every day. Otherwise, AI can write a short '
                    'plain-English guide, drawn only from the regulations in the app.</span>', unsafe_allow_html=True)
        if st.button("✨ Explain leverage in plain English"):
            facts_now = (f"Tier 1 leverage ratio: buyer {pct(d['a']['leverage_ratio'])}, bank bought {pct(d['t']['leverage_ratio'])}, "
                         f"combined {pct(d['c']['leverage_ratio'])}, minimum 4%. Supplementary leverage ratio (only banks of $250bn+ report it): "
                         f"buyer {rep_(d['a'].get('slr'))}, bank bought {rep_(d['t'].get('slr'))}, combined {rep_(d['c'].get('slr'))}; "
                         f"it applies to the combined bank from Category III. "
                         f"Combined bank: {E.cat_label(cat)}. Liabilities: {d['liab']['detail']}")
            res = run_ai(explain_key, lambda: ai.explain_multi(
                "3 Leverage & liabilities", "Write a short plain-English guide for a transactional lawyer. Use a bold heading for each of: "
                "Tier 1 leverage ratio; How it differs from the risk-based capital ratios; Supplementary leverage ratio and total leverage "
                "exposure; The enhanced SLR for the largest banks; The 10% liabilities concentration limit. Under each, two or three short "
                "sentences: first what it is in everyday words, drawn from the passages, then one sentence tying it to this deal's figures "
                "in APP FACTS. Cite passages. No preamble.",
                facts_now,
                [("section", "12 CFR 217.10", "leverage ratio is the ratio"),
                 ("section", "12 CFR 217.10", "total leverage exposure"),
                 ("section", "12 CFR 217.11", "leverage buffer"),
                 ("section", "12 CFR 251.2", "10 percent of the aggregate"),
                 ("section", "12 CFR 251.3", "consolidated liabilities")], LIB),
                "Writing the guide…")
            if res:
                st.rerun()

    # ---- what each size category must hold ----
    st.markdown("### What each size category must hold")
    st.markdown('<p class="lede">Every bank needs a 4% Tier 1 leverage ratio. From Category III, the supplementary leverage ratio '
                'adds a second test that also counts off-balance-sheet exposures; the largest banks hold an extra buffer on top.</p>',
                unsafe_allow_html=True)
    here = {}
    here.setdefault(d["cat_a"][0], []).append("buyer today")
    here.setdefault(cat, []).append("after the deal")
    lrows = []
    for c_, who, lev, slr, src in E.CATEGORY_LEVERAGE:
        label = f"<b>{'Below $100bn' if c_ == 'None' else 'Category ' + c_}</b>"
        if c_ in here:
            label += "<br>" + " ".join(f'<span class="pill" style="background:#1f3a931a;color:#1f3a93">{x}</span>' for x in here[c_])
        lrows.append({"Size category": label, "Who": who, "Tier 1 leverage ratio": lev, "Supplementary leverage ratio": slr, "Source": src})
    table(lrows, ["Size category", "Who", "Tier 1 leverage ratio", "Supplementary leverage ratio", "Source"], src_col="Source")

    st.markdown("### Liabilities")
    st.markdown('<p class="lede">No merger may leave the combined firm with more than 10% of the liabilities of the whole U.S. '
                'financial sector. If the buyer borrows to pay for the deal, that debt adds to the combined liabilities.</p>',
                unsafe_allow_html=True)
    debt = st.number_input("Debt raised to finance the deal (US$bn)", 0.0, value=float(saved("deal_debt_bn", 0.0)), step=1.0,
                           help="For example, senior notes issued by the buyer's holding company to fund the purchase price.")
    if debt != saved("deal_debt_bn", 0.0):
        keep("deal_debt_bn", debt)
        st.rerun()
    d = deal()
    L = d["liab"]
    total_liab = d["c"]["total_liabilities"] + d["deal_debt"]
    share_of_limit = min(1.0, total_liab / L["limit"])
    c1, c2 = st.columns([3, 1])
    with c1:
        st.progress(share_of_limit, text=(f"Combined liabilities {E.bn(total_liab)}"
                                          + (f" (incl. {E.bn(d['deal_debt'])} of deal debt)" if d["deal_debt"] else "")
                                          + f" — {share_of_limit * 100:.1f}% of the way to the {E.bn(L['limit'])} limit").replace("$", "\\$"))
    c2.markdown(pill(L["status"]), unsafe_allow_html=True)
    room = L["limit"] - total_liab
    st.markdown(f'<span class="muted">Room left under the limit: <b>{E.bn(room)}</b>. Source: 12 U.S.C. 1852(b); 12 CFR 251. '
                f'Sector total {E.bn(E.FIN_SECTOR_LIABILITIES)} — {E.FIN_SECTOR_SOURCE}</span>', unsafe_allow_html=True)

    facts = (f"Leverage ratio: buyer {pct(d['a']['leverage_ratio'])}, bank bought {pct(d['t']['leverage_ratio'])}, combined "
             f"{pct(d['c']['leverage_ratio'])} vs 4% minimum. Combined category {E.cat_label(cat)} (SLR applies from Category III). "
             f"Liabilities: {L['detail']}")
    st.write("")
    res = run_ai(fp("leverage", facts), lambda: ai.explain(
        "3 Leverage & liabilities", "In under 150 words explain the leverage position and the liabilities concentration limit for "
        "this deal. Cite passages.", facts,
        "leverage ratio 4 percent supplementary leverage ratio concentration limit consolidated liabilities 10 percent financial companies", LIB))
    show_ai(res, "What this means", "leverage")
    chat_box("3 Leverage & liabilities", facts)


def page_canadian():
    header("canadian")
    if not ready():
        return need_banks()
    if not saved("canadian"):
        st.markdown('<p class="lede">This step is for a Canadian bank buying a U.S. bank. Tick <b>"The buyer is a Canadian bank"</b> '
                    'on the Getting started page to use it.</p>', unsafe_allow_html=True)
        st.button("Go to Getting started", on_click=go, args=("setup",))
        return
    d = deal()
    cx = canadian(d)
    G, v, fp_ = cx["G"], cx["v"], cx["fp"]
    parent_name = nice_name(G["parent"])
    ihc_name = nice_name(G["ihcs"][0]["name"]) if G["ihcs"] else "its U.S. holding company"
    st.markdown(f'<p class="lede">Once a foreign bank\'s U.S. presence is big enough, the U.S. regulates it much like a U.S. bank — '
                f'and that reaches back to the businesses it owns at home. Here: <b>{parent_name}</b> buying '
                f'<b>{nice_name(d["t"]["name"])}</b>.</p>', unsafe_allow_html=True)

    # ---- A. U.S. footprint ----
    st.markdown("### A. Its U.S. presence, before and after")
    st.markdown(f'<span class="muted">From {ihc_name}\'s FR Y-9C and the Fed\'s ownership records.</span>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    for col, lbl, before, after in ((c1, "U.S. subsidiaries (non-branch)", fp_["nonbranch_before"], fp_["nonbranch_after"]),
                                    (c2, "All U.S. operations incl. branches", fp_["combined_before"], fp_["combined_after"])):
        col.markdown(f'<div class="stat"><div class="l">{lbl}</div><div class="n" style="font-size:22px">{E.bn(before)} → {E.bn(after)}</div></div>',
                     unsafe_allow_html=True)
    c3.markdown(f'<div class="stat"><div class="l">Today in the U.S.</div><div class="n" style="font-size:22px">{G["under_ihc"]:,} companies</div>'
                f'<div class="l">under the IHC · {len(G["branches"])} branches/offices</div></div>', unsafe_allow_html=True)
    st.write("")
    keep("branches_bn", st.number_input("Assets in its U.S. branches and agencies (US$bn, optional)", 0.0, value=float(saved("branches_bn", 0.0)),
                                        step=1.0, help="From the branches' FFIEC 002 reports (available from the Fed on request). "
                                        "Branches count toward 'all U.S. operations' but not toward the $50bn IHC trigger."))

    # ---- B. U.S. rules ----
    st.markdown("### B. The U.S. rules it is now subject to")
    st.markdown(f'<span class="muted">{E.SUBPART_O_NOTE}</span>', unsafe_allow_html=True)
    show_summary_table(cx["us_rows"])
    new_ihc = E.newly_applying(cx["ihc_before"], cx["ihc_after"])
    if new_ihc:
        st.markdown(f"**What {ihc_name} newly has to do** ({E.cat_label(cx['ihc_before'])} → {E.cat_label(cx['ihc_after'])}):")
        table([{"Requirement": r["Requirement"], "Before": r["Before"], "After": r["After"], "Source": r["Source"]} for r in new_ihc],
              ["Requirement", "Before", "After", "Source"], src_col="Source")

    # ---- C. Reg K ----
    st.markdown("### C. Reg K — can it keep its businesses at home?")
    st.markdown('<p class="lede">A foreign bank may run <b>any</b> business outside the U.S. — and own foreign companies that also do some '
                'U.S. business — only while it is a <b>qualifying foreign banking organization</b>. It must stay mostly a bank, and '
                'mostly outside the U.S. A big U.S. acquisition pushes on the second test.</p>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    keep("mostly_banking", c1.radio("Is more than half its worldwide business banking?", ["Yes", "No", "Not sure"],
                                    index=["Yes", "No", "Not sure"].index(saved("mostly_banking", "Yes")), horizontal=True,
                                    help="Test 1. True for the big Canadian banks; confirm from its annual FR Y-7 report to the Fed."))
    keep("us_rev_share", c2.number_input("Share of its banking revenue earned in the U.S. after the deal (%)", 0.0, 100.0,
                                         value=saved("us_rev_share"), step=1.0, help="From its annual report's U.S. segment, plus the target."))
    keep("us_ni_share", c3.number_input("Share of its banking net income earned in the U.S. after the deal (%)", 0.0, 100.0,
                                        value=saved("us_ni_share"), step=1.0, help="From its annual report's U.S. segment, plus the target."))
    cx = canadian(d)
    q = cx["q"]
    table([{"Measure": l["measure"], "Share in the U.S.": "n/a" if l["us_share"] is None else f"{l['us_share']:.1f}%",
            "Result": pill({True: "met", False: "not_met", None: "unknown"}[l["pass"]]), "Detail": l["detail"]} for l in q["legs"]],
          ["Measure", "Share in the U.S.", "Result", "Detail"])
    st.markdown(f"**Overall: {pill(q['overall'])}** &nbsp; Test 1 {pill(q['test1'])} &nbsp; Test 2 {pill(q['test2'])}"
                + ((f" &nbsp; · &nbsp; Room for more U.S. banking assets before the assets measure fails: <b>{E.bn(q['headroom'])}</b>"
                    if q["headroom"] > 0 else
                    f" &nbsp; · &nbsp; U.S. banking assets are already <b>{E.bn(-q['headroom'])}</b> past the point where the assets measure fails")
                   if q["headroom"] is not None else ""), unsafe_allow_html=True)
    st.markdown('<span class="muted">Each test needs 2 of 3 measures. Assets come from the Pillar 3 report and FR Y-9Cs (U.S. assets include '
                'branches entered above); Puerto Rico, Guam and other territories count as the U.S. The parent\'s total assets are used as '
                '"outside the U.S." after removing U.S. assets — a simplification. Source: 12 CFR 211.23(a)–(b).</span>', unsafe_allow_html=True)
    with st.expander("What happens if it stops qualifying"):
        for title, body, cite in E.REG_K_CONSEQUENCES:
            st.markdown(f"**{title}.** {body} <span class='muted'>({cite})</span>", unsafe_allow_html=True)

    # ---- D. Holdings: what it may have to sell ----
    holdings_section(d, cx, parent_name)
    us_holdings_table(d, G)

    # ---- E. OSFI ----
    st.markdown("### E. Its Canadian capital (OSFI)")
    P = S.get("parent")
    if P:
        fig = P["fig"]
        st.markdown(f'<span class="ai-tag">✨ Read by AI</span>&nbsp; from pages {", ".join(map(str, P["pages"]))} of the Pillar 3 report. '
                    f'You can correct any figure in the table.', unsafe_allow_html=True)
        keys = ai.AMOUNT_FIELDS + ("cet1_ratio", "leverage_ratio")
        edit = pd.DataFrame([{"Figure": ai.PARENT_FIELDS[k].split(" (")[0], "C$ millions / %": fig[k]["value"],
                              "Where the AI found it": fig[k]["found_as"]} for k in keys])
        edited = st.data_editor(edit, hide_index=True, width="stretch", disabled=["Figure", "Where the AI found it"], key="parent_editor")
        for k, val in zip(keys, edited["C$ millions / %"]):
            fig[k]["value"] = None if pd.isna(val) else float(val)
        st.markdown('<span class="code-tag">✓ Checked without AI</span>&nbsp; ' + " · ".join(
            f"{'✓' if c['ok'] else '?' if c['ok'] is None else '✕'} {c['check']} ({c['result']})" for c in ai.verify_parent(fig)),
            unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    keep("fx", c1.number_input("C\\$ per US\\$1", 0.5, 3.0, float(saved("fx", 1.40)), 0.01, help="Enter today's exchange rate."))
    keep("dsib", c2.checkbox("It is a Canadian D-SIB", value=saved("dsib", True), help="TD, RBC, BMO and CIBC all are."))
    keep("dsb", c3.number_input("OSFI Domestic Stability Buffer (%)", 0.0, 4.0, float(saved("dsb", 3.0)), 0.25,
                                help="Set by OSFI; not in this app's library. Check OSFI's latest announcement."))
    cx = canadian(d)
    show_summary_table(cx["osfi_rows"])
    st.markdown('<span class="muted">Simplified: it pays cash at book value, so its capital is unchanged and the target\'s risk-weighted assets '
                'are added at their U.S. amount (OSFI\'s weights may differ).</span>', unsafe_allow_html=True)

    facts = "\n".join(f"- {E.STATUS[r['status']][1]} | {r['check']} | {r['detail']}" for r in cx["rows"])
    facts += f"\nParent: {G['parent']}; U.S. holding company: {ihc_name}."
    res = run_ai(fp("canadian", facts), lambda: ai.explain(
        "4 Canadian buyer", "In under 200 words, explain to the deal lawyer: which U.S. rules the Canadian bank is (newly) subject to after "
        "the deal; whether it still qualifies under Reg K to keep its non-U.S. businesses, and what happens if not; and which holdings "
        "need review. Use the statuses exactly as given. Cite passages.",
        facts, "qualifying foreign banking organization more than half banking outside United States nonbanking activities exemptions "
        "U.S. intermediate holding company combined U.S. assets $100 billion risk committee", LIB, k=8))
    show_ai(res, "What this means", "canadian")
    chat_box("4 Canadian buyer", facts)


# --------------------------------------------------------------------------------------
# Canadian buyer, section E: the holdings register and the disposal review
# --------------------------------------------------------------------------------------
REGISTER_EXAMPLE = "ILLUSTRATIVE_holdings_register.csv"


def register_text(name, data):
    """Turn an uploaded register into text the AI can read: spreadsheet rows, PDF pages, Word paragraphs or plain text."""
    low = name.lower()
    if low.endswith((".csv", ".xlsx", ".xls")):
        df = pd.read_csv(io.BytesIO(data)) if low.endswith(".csv") else pd.read_excel(io.BytesIO(data))
        return df.to_csv(index=False)
    if low.endswith(".pdf"):
        from pypdf import PdfReader
        text, _pg = ai.find_subsidiary_pages(PdfReader(io.BytesIO(data)))
        return text or "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages[:12])
    if low.endswith(".docx"):
        from docx import Document
        doc = Document(io.BytesIO(data))
        rows = ["\t".join(c.text for c in r.cells) for t in doc.tables for r in t.rows]
        return "\n".join([p.text for p in doc.paragraphs if p.text.strip()] + rows)
    return data.decode("utf-8", errors="ignore")


def disposal_current():
    """The disposal review for the deal on screen, if it has been run."""
    res = S.get("disposal")
    return res if res and res.get("deal") == fp(saved("parent_key"), saved("tgt")) else None


def two_ways_out(q):
    """One line framing the real choice, from numbers the app already has (no AI)."""
    h = q.get("headroom")
    if q["overall"] == "not_met" and q["test2"] == "not_met" and h is not None and h < 0:
        return ("not_met", f"<b>Two ways out.</b> Keep Reg K status by shedding more than <b>{E.bn(-h)}</b> of U.S. banking assets "
                           "(the assets measure; revenue and income move with it until real figures are entered) — or let Reg K status "
                           "go, and in time sell or wind down the non-banking holdings abroad that depend on it, reviewed below.")
    if q["overall"] == "not_met":
        return ("not_met", "<b>It fails a Reg K test</b>, so the holdings that depend on Reg K status are at risk — reviewed below.")
    if q["overall"] == "met" and h is not None:
        return ("met", f"<b>Reg K is met</b>, with room for {E.bn(h)} more U.S. banking assets. The review below checks each "
                       "holding's own conditions.")
    return ("unknown", "<b>Reg K status can't be confirmed yet</b> — load the parent's Pillar 3 report on Getting started. The "
                       "review below still shows what depends on it.")


def holdings_section(d, cx, parent_name):
    st.markdown("### D. Holdings — what it may have to sell")
    q, G = cx["q"], cx["G"]
    tone, line = two_ways_out(q)
    colour = E.STATUS[tone][2]
    st.markdown(f'<div class="card" style="border-left:4px solid {colour}">{line}</div>', unsafe_allow_html=True)
    if q["overall"] == "not_met" and q["test2"] == "not_met":
        st.button("See how in Deal options →", type="tertiary", on_click=go, args=("options",), key="to_options")
    sig = E.holding_signals(d["t"])
    if sig:
        st.markdown(f'<span class="muted">On <b>{nice_name(d["t"]["name"])}</b>\'s own balance sheet (its FR Y-9C): '
                    + " · ".join(f"{s['label'].split(' (')[0].lower()} <b>{E.money(s['value'])}</b>" for s in sig)
                    + " — a U.S. holding company may need to sell or conform these. The AI's review on Getting started looks at "
                      "them.</span>", unsafe_allow_html=True)
    st.write("")
    st.markdown(f'<p class="lede">Upload {parent_name}\'s holdings register — a spreadsheet, PDF, Word file or plain list. The AI '
                'reviews every holding under Reg K and Regulation Y; the app checks each verdict against its own Reg K result and '
                'works out the timing.</p>', unsafe_allow_html=True)
    c1, c2 = st.columns([3, 1.2])
    up = c1.file_uploader("Holdings register", type=["csv", "xlsx", "xls", "pdf", "docx", "txt"], key="register_upload",
                          help="Columns or lines with: company, country, business, ownership %, U.S. activities. Any layout works.")
    if c2.button("Use the example register", width="stretch", help="Fictional companies, for demonstration"):
        S["register"] = (REGISTER_EXAMPLE, _read_test(REGISTER_EXAMPLE))
    if up is not None:
        S["register"] = (up.name, up.getvalue())
    known = [dict(h, source="Fed records") for h in G.get("foreign_all", []) + G.get("territory_holdings", [])]
    include_known = bool(known)
    if known:
        c1.caption(f"The review also includes the {len(known)} companies the Fed's records list for {cx['pk']}.")
    reg = S.get("register")
    if reg:
        c2.markdown(f'<span class="muted">Loaded: <b>{reg[0]}</b></span>', unsafe_allow_html=True)
    run = st.button("✨ Review the holdings", type="primary", disabled=not (reg or known))
    if run:
        if not ai.ready():
            st.warning("Add your API key in the left-hand panel first.")
        else:
            with st.status("Reviewing the holdings…", expanded=True) as status:
                try:
                    holdings = []
                    if reg:
                        status.write(f"✨ AI is reading **{reg[0]}**…")
                        holdings = [dict(h, source=reg[0]) for h in
                                    ai.extract_register("4 Canadian buyer", register_text(*reg), parent_name)]
                        status.write(f"Found {len(holdings)} companies in the register.")
                    if include_known:
                        names = {h["name"].lower() for h in holdings}
                        holdings += [dict(h, business=h.get("activity", ""), ownership_pct=None, us_activity="")
                                     for h in known if h["name"].lower() not in names]
                    passages = ai.disposal_passages(holdings, LIB)
                    context = (f"Parent: {parent_name}, a Canadian bank, buying {nice_name(d['t']['name'])}. The app's Reg K result "
                               f"after the deal: test 1 {E.STATUS[q['test1']][1]}, test 2 {E.STATUS[q['test2']][1]}, overall "
                               f"{E.STATUS[q['overall']][1]} (U.S. share of its banking assets "
                               f"{'unknown' if q['legs'][0]['us_share'] is None else format(q['legs'][0]['us_share'], '.1f') + '%'}). "
                               "So: if overall is Not met, its Reg K exemptions are at risk; if Met, it qualifies.")
                    status.write(f"✨ AI is reviewing {len(holdings)} holdings against {len(passages)} passages of Reg K and "
                                 "Regulation Y, several at once…")
                    verdicts = ai.analyse_holdings("4 Canadian buyer", holdings, context, passages)
                    status.write("The app is checking every verdict and working out the timing…")
                    rows = []
                    for h in holdings:
                        v = verdicts.get(h["name"]) or {}
                        key = v.get("verdict")
                        rows.append(dict(h, verdict=key, reason=v.get("reason", ""), action=v.get("action", ""),
                                         timing=E.disposal_timing(key, q["overall"], closing_date()),
                                         notes=E.disposal_checks(h, key, q["overall"]) if key else
                                         ["The AI gave no verdict for this holding — review it by hand."]))
                    rows.sort(key=lambda r: (E.VERDICT_ORDER.index(r["verdict"]) if r["verdict"] in E.VERDICT_ORDER else -1, r["name"]))
                    S["disposal"] = {"deal": fp(saved("parent_key"), saved("tgt")), "rows": rows, "passages": passages,
                                     "regk": q["overall"], "source": reg[0] if reg else "the Fed's records"}
                    status.update(label="Holdings reviewed", state="complete", expanded=False)
                except Exception as exc:
                    status.update(label="The review did not finish", state="error")
                    st.error(f"Something went wrong: {exc}")
    res = disposal_current()
    if not res:
        return
    if res["regk"] != q["overall"]:
        st.info("The Reg K result above has changed since this review was run — press **Review the holdings** again to update it.")
    rows, P = res["rows"], res["passages"]
    n = {k: sum(1 for r in rows if r["verdict"] == k) for k in E.VERDICTS}
    cols = st.columns(4)
    for col, k in zip(cols, ("sell", "at_risk", "approval", "keep")):
        label, status_ = E.VERDICTS[k]
        colour = E.STATUS[status_][2]
        count = n[k] + (n["keep_conditions"] if k == "keep" else 0)
        col.markdown(f'<div class="stat"><div class="n" style="color:{colour}">{count}</div><div class="l">'
                     f'{label if k != "keep" else "Can keep (incl. with conditions)"}</div></div>', unsafe_allow_html=True)
    st.write("")
    flagged = sum(1 for r in rows if r["notes"])
    st.markdown(f'<span class="ai-tag">✨ Verdicts by AI</span> <span class="code-tag">checked by the app</span>&nbsp; '
                + badge(flagged == 0, "every verdict is consistent with the app's Reg K result" if flagged == 0 else
                        f"{flagged} verdict(s) flagged for a second look")
                + f' &nbsp;<span class="muted">· {len(rows)} holdings from {res["source"]}</span>', unsafe_allow_html=True)
    stake = lambda r: "" if r.get("ownership_pct") is None else f" · {r['ownership_pct']:.0f}% owned"
    verdict_pill = lambda r: (pill(E.VERDICTS[r["verdict"]][1]).replace(E.STATUS[E.VERDICTS[r["verdict"]][1]][1], E.VERDICTS[r["verdict"]][0])
                              if r["verdict"] else pill("unknown"))
    table([{"Verdict": verdict_pill(r) + "".join(f"<br><span style='color:#b26a00;font-size:13px'>⚠️ App check: {x}</span>"
                                                  for x in r["notes"]),
            "Company": f"<b>{nice_name(r['name'])}</b><br><span class='muted'>{r.get('country', '')}{stake(r)}</span>",
            "Business": (r.get("business") or r.get("activity", "")) + (f"<br><span class='muted'>U.S.: {r['us_activity']}</span>"
                                                                       if r.get("us_activity") and r["us_activity"].lower() != "none" else ""),
            "Why (AI)": law(r["reason"], P),
            "Next step": (r["action"] or "—") + (f"<br><span class='muted'>⏱ {r['timing']}</span>" if r["timing"] else "")}
           for r in rows],
          ["Verdict", "Company", "Business", "Why (AI)", "Next step"])
    out = pd.DataFrame([{"Company": r["name"], "Country": r.get("country"), "Ownership %": r.get("ownership_pct"),
                         "Business": r.get("business") or r.get("activity"), "U.S. activities": r.get("us_activity"),
                         "Verdict": E.VERDICTS[r["verdict"]][0] if r["verdict"] else "No verdict",
                         "Why": law(r["reason"], P), "Next step": r["action"], "Timing": r["timing"],
                         "App check": " ".join(r["notes"])} for r in rows])
    st.download_button("Download the disposal schedule (CSV)", out.to_csv(index=False), file_name="disposal_schedule.csv")
    st.markdown('<span class="muted">Covers only the holdings listed — the register uploaded plus the Fed\'s records. Screening view, '
                'not a legal opinion; timing is a rough guide from the expected closing date on Getting started (the two-year clock '
                'under 12 CFR 211.23(d) runs from the annual reports to the Fed).</span>', unsafe_allow_html=True)


def us_holdings_table(d, G):
    st.markdown("**In the U.S.** — everything must sit under the IHC, except branches and narrow exceptions.")
    rows = [{"Item": f"<b>{nice_name(d['t']['name'])}</b> (being bought)", "What to do": "Place under the IHC.", "Source": "12 CFR 252.153"}]
    for x in G["outside_ihc"]:
        rows.append({"Item": nice_name(x["name"]) + f" <span class='muted'>({x['type']}, {x['where']})</span>",
                     "What to do": "Held outside the IHC today — confirm it is a section 2(h)(2) company or DPC branch subsidiary, or move it.",
                     "Source": "12 CFR 252.153"})
    rows.append({"Item": f"{len(G['branches'])} U.S. branches, agencies and representative offices",
                 "What to do": "Stay outside the IHC (part of the parent itself). Branch vs subsidiary is a structuring choice.",
                 "Source": "12 CFR 252.153"})
    table(rows, ["Item", "What to do", "Source"], src_col="Source")
    with st.expander(f"Its U.S. branches and offices ({len(G['branches'])})"):
        table([{"Office": nice_name(b["name"]), "Type": b["type"], "Where": b["where"]} for b in G["branches"]], ["Office", "Type", "Where"])


# --------------------------------------------------------------------------------------
# AI analyst: the AI chooses what to investigate and calls the app's calculator; code checks every number
# --------------------------------------------------------------------------------------
TOOL_LABEL = {"headroom": "How close is it to every line?", "break_even": "What would it take to flip each result?",
              "scenario": "What if…", "timeline": "When does it bite? Quarter by quarter"}
FOCUS_IDEAS = ["How close is this deal to the next line?", "How much of a capital hit can the combined bank take?",
               "When after closing does the new category apply?", "What if the bank being bought keeps growing?"]


def analyst_facts(d, base):
    f = (f"Buyer: {nice_name(d['a']['name'])}{' (the U.S. arm of ' + saved('parent_key') + ')' if saved('canadian') else ''}, "
         f"average assets {E.bn(d['A']['avg_assets'])}, {E.cat_label(d['cat_a'][0])} today. Bank being bought: "
         f"{nice_name(d['t']['name'])}, {E.bn(d['T']['avg_assets'])}. Combined: {E.bn(d['pf_avg'])}, {E.cat_label(d['cat_c'][0])}. "
         f"Combined CET1 {pct(d['c']['cet1_ratio'])} on risk-weighted assets of {E.bn(d['c']['rwa'])}; CET1 capital "
         f"{E.bn(d['c']['cet1'])}; Tier 1 leverage {pct(d['c']['leverage_ratio'])}. Deal debt {E.bn(d['deal_debt'])}.")
    if closing_date():
        f += f" Expected closing {closing_date():%d %b %Y}."
    if saved("canadian"):
        cx = canadian(d)
        f += (f" Canadian buyer: combined U.S. assets {E.bn(cx['fp']['combined_after'])}; Reg K overall "
              f"{E.STATUS[cx['q']['overall']][1]}.")
    return f


def page_analyst():
    header("analyst")
    if not ready():
        return need_banks()
    d = deal()
    base, _before, tl = analysis_base(d)
    st.markdown('<p class="lede">The AI analyst investigates the deal the way a senior analyst would: it decides what to test, runs '
                'the app\'s calculator, reads the result and decides what to test next. It never does the arithmetic itself — '
                'and the app checks every number in its write-up.</p>', unsafe_allow_html=True)
    pick = st.pills("Suggested focus", FOCUS_IDEAS, key="focus_pick", label_visibility="collapsed")
    focus = st.text_input("What should the analyst focus on? (optional)", value=pick or saved("focus", ""),
                          placeholder="e.g. Could a weak year push the combined bank into its buffer?")
    keep("focus", focus)
    facts = analyst_facts(d, base)
    key = fp("analyst", deal_sig(), focus)
    res = S["ai_cache"].get(key)
    c1, c2 = st.columns([1, 3])
    go_ = c1.button("✨ Run the investigation" if not res else "↻ Investigate again", type="primary" if not res else "secondary")
    c2.markdown(f'<div class="muted" style="padding-top:8px">Up to {ai.ANALYST_MAX_STEPS} calculator calls, chosen one at a time by '
                'the AI, then a written report.</div>', unsafe_allow_html=True)
    if go_:
        if not ai.ready():
            st.warning("Add your API key in the left-hand panel first.")
        else:
            res = run_analyst(d, base, tl, facts, focus)
            if res:
                S["ai_cache"][key] = res
                S["analyst_last"] = {"deal": fp(saved("acq"), saved("tgt")), "report": res["report"]}
    if not res:
        st.markdown("#### What it can use")
        table([{"Tool": f"<b>{TOOL_LABEL[k]}</b>", "What the app calculates": v} for k, v in E.ANALYST_TOOLS.items()],
              ["Tool", "What the app calculates"])
        return
    nums = res["numbers"]
    st.markdown("### Findings")
    st.markdown((badge(not nums["unverified"], f"all {nums['checked']} figures trace to the app's calculations")
                 if not nums["unverified"] else
                 badge(None, f"{len(nums['unverified'])} of {nums['checked']} figures could not be traced: "
                             + ", ".join(nums["unverified"][:4]) + " — treat with care")), unsafe_allow_html=True)
    show_ai({"text": res["report"]}, "the analyst's findings", "analyst")
    st.markdown("### How the analyst got there")
    for i, h in enumerate(res["history"], 1):
        with st.container(border=True):
            args = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in (h["args"] or {}).items())
            st.markdown(f"<b>{i} · {TOOL_LABEL.get(h['tool'], h['tool'])}</b>{' — ' + args if args else ''}<br>"
                        f"<span class='ai-tag'>✨ AI's reason</span> <span class='muted'>{h['why']}</span>", unsafe_allow_html=True)
            r = h["result"]
            with st.expander("Result calculated by the app"):
                if isinstance(r, dict) and "rows" in r:
                    st.markdown(f"**{r.get('summary', '')}**")
                    table([{"Quarter-end": x["quarter_end"], "Quarters after closing": x["quarters_since_closing"],
                            "Four-quarter average": x["four_quarter_average"], "Category": x["category"]} for x in r["rows"]],
                          ["Quarter-end", "Quarters after closing", "Four-quarter average", "Category"])
                    st.caption(r["note"])
                elif isinstance(r, dict):
                    flat = []
                    for k, v in r.items():
                        if isinstance(v, dict):
                            flat += [(k2, v2) for k2, v2 in v.items()]
                        else:
                            flat.append((k.replace("_", " ").capitalize(), ", ".join(v) if isinstance(v, list) else v))
                    table([{"Measure": k, "Result": v} for k, v in flat], ["Measure", "Result"])


def run_analyst(d, base, tl, facts, focus):
    tools_doc = "\n".join(f"- {k}: {v}" for k, v in E.ANALYST_TOOLS.items())
    history, seen = [], set()
    try:
        with st.status("The AI analyst is investigating…", expanded=True) as status:
            for n in range(ai.ANALYST_MAX_STEPS):
                status.update(label=f"The AI analyst is choosing call {n + 1}…")
                dec = ai.analyst_next("AI analyst", facts, tools_doc, history, focus, n)
                if dec.get("done") and n >= 3:
                    break
                tool, args = str(dec.get("tool", "")), dec.get("args") if isinstance(dec.get("args"), dict) else {}
                sig = json.dumps([tool, args], sort_keys=True)
                if tool not in E.ANALYST_TOOLS:
                    result = {"error": f"There is no tool called '{tool}'."}
                elif sig in seen:
                    result = {"note": "Already run with these arguments - choose something new."}
                else:
                    result = E.run_tool(tool, args, base, tl)
                seen.add(sig)
                history.append({"tool": tool, "args": args, "why": str(dec.get("why", "")), "result": result})
                shown = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in args.items())
                status.write(f"**{n + 1} · {TOOL_LABEL.get(tool, tool)}**{' (' + shown + ')' if shown else ''} — {dec.get('why', '')}")
            status.update(label="The AI analyst is writing up its findings…")
            report = ai.analyst_report("AI analyst", facts, history, focus)
            inputs = " ".join(f"${v}bn" if k.endswith("_bn") else f"{v}%" for h in history for k, v in (h["args"] or {}).items())
            inputs += " " + " ".join(h["why"] for h in history)      # the AI's own scenario design (inputs, not results)
            nums = E.verify_numbers(report, facts + " " + inputs + " " + json.dumps([h["result"] for h in history]))
            status.update(label=f"Investigation complete — {len(history)} calculator calls", state="complete", expanded=False)
        return {"history": history, "report": report, "numbers": nums}
    except Exception as exc:
        st.error(f"The investigation did not finish: {exc}")
        return None


# --------------------------------------------------------------------------------------
# Deal options: AI proposes ways to stay under the line, code tests every one
# --------------------------------------------------------------------------------------
GOAL_SHORT = {"category": "Size line", "capital": "Capital", "liabilities": "Liabilities limit", "regk": "Reg K", "subpart_o": "Subpart O"}


def options_base(d, preset_debt):
    """The combined bank as plain numbers, ready for engine.apply_levers (thousands of US$)."""
    c, t = d["c"], d["t"]
    base = dict(avg_assets=d["pf_avg"], total_assets=c["total_assets"], rwa=c["rwa"], cet1=c["cet1"], tier1=c["tier1"],
                total_capital=c["total_capital"], lev_assets=c["avg_assets_lev"],
                slr_exposure=c["tier1"] / (c["slr"] / 100) if c.get("slr") else None,
                liabilities=c["total_liabilities"] + preset_debt, gsib=saved("gsib", False),
                target_rwa_density=(t["rwa"] / t["total_assets"]) if t.get("total_assets") else 0.6)
    before_us = None
    if saved("canadian"):
        cx = canadian(d)
        base.update(us_combined=cx["fp"]["combined_after"], parent_total=cx["parent_total_usd"],
                    us_rev_share=saved("us_rev_share"), us_ni_share=saved("us_ni_share"),
                    mostly_banking={"Yes": True, "No": False}.get(saved("mostly_banking", "Yes")))
        before_us = cx["fp"]["combined_before"]
    return base, before_us


def move_text(lv):
    a = E.bn(lv["amount"])
    return {"sell_business": f"Sell: {str(lv.get('business', ''))} — {a}",
            "raise_equity": f"Raise new equity — {a}",
            "replace_debt_with_stock": f"Pay {a} in shares instead of borrowing it",
            "sell_securities": f"Buyer sells {a} of its securities",
            "book_in_branch": f"Keep {a} of lending in the U.S. branch, outside the IHC"}[lv["lever"]]


def test_option(opt, base, menu, goals, client_note=""):
    if "moves" in opt:      # an AI strategy: code sizes each move, then tests
        moves = opt.get("moves") or []
        if not client_note.strip():   # a limit is only honoured if the client actually said something
            moves = [dict(m, max_bn=None) for m in moves if isinstance(m, dict)]
        levers, notes = E.size_option(base, moves, menu, goals)
    else:                   # the user's own amounts
        levers, notes = E.clean_levers(opt.get("levers"), menu)
    ev = E.evaluate(E.apply_levers(base, levers, menu))
    verdicts = {g["id"]: E.goal_met(g, ev) for g in goals}
    return dict(opt, levers_clean=levers, notes=notes, ev=ev, verdicts=verdicts,
                works=bool(levers) and all(verdicts[g["id"]] for g in goals if g.get("reachable", True)),
                short={g["id"]: E.goal_shortfall(g, ev) for g in goals if not verdicts[g["id"]]})


def option_facts(o, goals):
    ev = o["ev"]
    lines = [f"OPTION: {o.get('title', 'Untitled')}",
             "  Moves (as tested): " + ("; ".join(move_text(l) for l in o["levers_clean"]) or "none usable")]
    for g in goals:
        if o["verdicts"][g["id"]]:
            lines.append(f"  {g['text']}: MET")
        else:
            sf = o["short"].get(g["id"])
            lines.append(f"  {g['text']}: NOT MET" + (f" - still {E.bn(sf)} short" if sf and sf > 0 else ""))
    lines.append(f"  Result: {E.cat_label(ev['category'])}, average assets {E.bn(ev['x']['avg_assets'])}, CET1 "
                 f"{ev['ratios']['cet1_ratio']:.2f}%, leverage {ev['ratios']['leverage_ratio']:.2f}%")
    if "regk" in ev and ev["regk"]["legs"][0]["us_share"] is not None:
        lines.append(f"  Reg K: U.S. share of the parent's banking assets {ev['regk']['legs'][0]['us_share']:.1f}%")
    if o.get("moves"):
        lines.insert(1, "  Strategy (moves in order of preference): " + "; ".join(
            (m.get("business") or m.get("lever", "")) + (f" (max ${m['max_bn']}bn)" if m.get("max_bn") else "") for m in o["moves"]))
    lines += [f"  Code note: {n}" for n in o["notes"]]
    return "\n".join(lines)


def page_options():
    header("options")
    if not ready():
        return need_banks()
    d = deal()
    st.markdown('<p class="lede">If the deal crosses a line, there is often a way to restructure it. Choose the deal background '
                'below. AI suggests three ways to stay on the right side of the line, and the app tests each one with the same '
                'rules as every other page.</p>', unsafe_allow_html=True)

    # ---- 1. the deal background (preset) ----
    st.markdown("### 1  The deal background")
    names = [n for n, p in E.DEAL_PRESETS.items() if saved("canadian") or not p["canadian_only"]]
    if saved("preset") not in names:
        keep("preset", names[-1] if saved("canadian") else names[0])
    preset = st.radio("Deal background", names, index=names.index(saved("preset")), horizontal=True, label_visibility="collapsed")
    keep("preset", preset)
    P = E.DEAL_PRESETS[preset]
    menu = E.deal_menu(preset, d["t"]["total_assets"], d["t"]["cet1"], d["a"]["total_assets"], saved("canadian"))
    biz = "; ".join(f"{n.lower()} ({E.bn(b['max'])})" for n, b in menu["businesses"].items())
    st.markdown(f'<div class="card"><b>{preset}.</b> {P["story"]}<br><span class="muted">On these numbers: price about '
                f'{E.bn(menu["price"])} ({P["price_to_cet1"]}× the target\'s CET1), {E.bn(menu["deal_debt"])} borrowed. '
                f'Businesses that could be sold: {biz}.</span></div>', unsafe_allow_html=True)
    st.write("")
    note = st.text_input("Anything else the client has said? (optional)", value=saved("client_note", ""),
                         placeholder="e.g. They would rather not sell the credit-card book")
    keep("client_note", note)

    # ---- 2. the lines this deal crosses (code) ----
    base, before_us = options_base(d, menu["deal_debt"])
    goals = E.deal_goals(base, d["cat_a"][0], before_us, "the U.S. holding company (IHC)" if saved("canadian") else "the combined bank")
    for g in goals:
        g["reachable"], g["best_short"], g["need_share"] = E.best_case(g, base, menu)
        g["tight"] = bool(g["reachable"] and g["need_share"] and g["need_share"] > 0.85)
    st.markdown("### 2  The lines this deal crosses")
    if not goals:
        st.success("On this background the deal crosses no line the app tests, so there is nothing to restructure. "
                   "Try another background, or another deal on Getting started.")
        return
    table([{"Goal": f"<b>{g['text']}</b>",
            "How far over": E.bn(g["gap"]) if g.get("gap") and g["gap"] > 0 else "—",
            "Can it be avoided?": ("Yes — but only by using almost every move in full" if g["tight"] else "Yes, with the moves available")
            if g["reachable"] else
            "<b style='color:#b42318'>No</b> — even every move together leaves it "
            + (f"{E.bn(g['best_short'])} short" if g.get("best_short") and g["best_short"] > 0 else "short"),
            "Source": g["cite"]} for g in goals],
          ["Goal", "How far over", "Can it be avoided?", "Source"], src_col="Source")
    live = [g for g in goals if g["reachable"]]
    if not live:
        st.warning("None of these lines can be avoided with the moves this background allows — the deal is too large for "
                   "a sale of businesses to fix. Try another background, or treat the new requirements as a cost of the deal.")
        return
    st.markdown('<span class="muted"><span class="code-tag">Worked out by the app</span>&nbsp; Size uses the four-quarter average, '
                'so a sale only counts in full once four quarters have passed.</span>', unsafe_allow_html=True)

    # ---- 3. AI proposes, code tests, AI revises, AI explains ----
    st.markdown("### 3  Ways to stay under the line")
    menu_lines = []
    for k, cap in menu["levers"].items():
        if k == "sell_business":
            menu_lines.append(f"- sell_business: {E.LEVERS[k]}. Businesses: " + "; ".join(
                f"'{n}' up to ${b['max'] / 1e6:.1f}bn (risk weight {b['rw']:.0%})" for n, b in menu["businesses"].items()))
        else:
            menu_lines.append(f"- {k}: {E.LEVERS[k]}. Up to ${cap / 1e6:.1f}bn.")
    ruled_out = [k for k in E.LEVERS if k not in menu["levers"]]
    if ruled_out:
        menu_lines.append("Not available for this deal: " + ", ".join(ruled_out))
    menu_text = "\n".join(menu_lines)
    goals_text = "\n".join(f"- {g['id']}: {g['text']}" + (f" - currently over by ${g['gap'] / 1e6:.1f}bn" if g.get("gap") and g["gap"] > 0 else "")
                           + ("" if g["reachable"] else " - CANNOT be reached with the moves available (the app checked every move "
                              "at its maximum). Do not aim for it; mention it in a downside if relevant.")
                           + (" - TIGHT: only reachable by using almost EVERY move on the menu (at least one strategy must list them all)"
                              if g.get("tight") else "")
                           for g in goals)
    effects = ("How the app models each move: selling a business or securities cuts size, U.S. assets and liabilities by the "
               "amount and risk-weighted assets by amount x risk weight, while capital stays (so ratios rise); new equity adds "
               "capital AND the same amount of cash to assets (so size grows); paying in shares cuts liabilities only; keeping "
               "lending in the branch cuts the IHC's size but not combined U.S. assets or the Reg K test.")
    mf = E.move_facts(goals, base, menu)
    if mf["fewest"]:
        goals_text += (f"\nWorked out by the app: at least {mf['fewest']} move(s), each used in full, are needed to clear every "
                       "reachable goal. " + (f"Moves that can do it alone: {', '.join(mf['singles'])}. " if mf["singles"] else
                                             "No single move is enough on its own. ")
                       + "Combinations that work: " + " | ".join(" + ".join(c) for c in mf["examples"])
                       + ". So every strategy must list at least that many moves (the app stops using them once the goals are met).")
    facts = (f"Buyer today: {E.cat_label(d['cat_a'][0])}. After the deal: {E.cat_label(d['cat_c'][0])}, average assets "
             f"{E.bn(base['avg_assets'])}. Combined CET1 {pct(d['c']['cet1_ratio'])}, leverage {pct(d['c']['leverage_ratio'])}. "
             + (f"Combined U.S. assets {E.bn(base['us_combined'])}; parent total {E.bn(base['parent_total']) if base.get('parent_total') else 'unknown'}. "
                if saved("canadian") else "") + effects)
    key = fp("options", preset, note, base, [g["id"] for g in goals])

    def find_options():
        passages = ai.option_passages([g["id"] for g in goals], LIB)
        first = ai.propose_options("Deal options", P["story"], note, menu_text, goals_text, facts, passages)
        tested = [test_option(o, base, menu, goals, note) for o in first["options"]]
        trail = [f"Round 1: AI proposed {len(tested)} options; the app's tests passed {sum(o['works'] for o in tested)}."]
        revised = False
        if any(not o["works"] for o in tested):
            fb = "\n\n".join(option_facts(o, goals) for o in tested)
            second = ai.propose_options("Deal options", P["story"], note, menu_text, goals_text, facts, passages, feedback=fb)
            if second["options"]:
                tested = [test_option(o, base, menu, goals, note) for o in second["options"]]
                revised = True
                trail.append(f"Round 2: AI revised the options using the test results; the app's tests passed {sum(o['works'] for o in tested)}.")
        if not tested:
            return {"options": [], "trail": trail, "revised": False, "explanation": None}
        results = "\n\n".join(option_facts(o, goals) for o in tested)
        expl = ai.explain_options("Deal options", P["story"] + (" Client also said: " + note if note else ""), results, passages)
        return {"options": tested, "trail": trail, "revised": revised, "explanation": expl}

    res = S["ai_cache"].get(key)
    if res is None:
        st.markdown('<span class="muted">AI chooses three strategies; the app sizes and tests each one; if any falls short, AI '
                    'revises it once; then AI explains which fits best.</span>',
                    unsafe_allow_html=True)
        if st.button("✨ Find ways to stay under the line", type="primary"):
            res = run_ai(key, find_options, "AI is proposing options, then the app is testing each one…")
            if res:
                st.rerun()
        return

    S["options_result"] = {"deal": fp(saved("acq"), saved("tgt")), "preset": preset,
                           "works": [(o.get("title", ""), "; ".join(move_text(l) for l in o["levers_clean"])) for o in res["options"] if o["works"]],
                           "goals": [g["text"] for g in goals]}
    if not res["options"]:
        st.warning("The AI did not return any usable options. Try again, or pick another background.")
    seen_moves = {}
    for i, o in enumerate(res["options"], 1):
        sig = tuple(sorted((l["lever"], l.get("business") or "", round(l["amount"] / 1e5)) for l in o["levers_clean"]))
        same_as = seen_moves.get(sig)
        seen_moves.setdefault(sig, i)
        with st.container(border=True):
            st.markdown(f"<div style='font-size:20px;font-weight:600;margin:4px 0 8px'>Option {i} · {o.get('title', 'Untitled')} &nbsp;"
                        + pill("met" if o["works"] else "not_met").replace("Met", "Works").replace("Not met", "Falls short") + "</div>",
                        unsafe_allow_html=True)
            c1, c2 = st.columns([3, 2])
            with c1:
                st.markdown('<span class="ai-tag">✨ Strategy by AI</span> <span class="code-tag">amounts sized by the app</span>',
                            unsafe_allow_html=True)
                for l in o["levers_clean"]:
                    st.markdown(f"• {move_text(l)}")
                if not o["levers_clean"]:
                    st.markdown("• _No move helped on these numbers._")
                if o.get("why"):
                    st.markdown(f"**Why:** {o['why']}")
                if o.get("downside"):
                    st.markdown(f"**Downside:** {o['downside']}")
            with c2:
                st.markdown('<span class="code-tag">Tested by the app</span>', unsafe_allow_html=True)
                rows = []
                for g in goals:
                    ok = o["verdicts"][g["id"]]
                    sf = o["short"].get(g["id"])
                    rows.append({"Goal": GOAL_SHORT[g["id"]], "Result": pill("met" if ok else "not_met")
                                 + ("<br><span class='muted'>can't be avoided</span>" if not (ok or g["reachable"]) else
                                    f"<br><span class='muted'>{E.bn(sf)} short</span>" if (not ok and sf and sf > 0) else "")})
                ev = o["ev"]
                rows.append({"Goal": "Ends up in", "Result": E.cat_label(ev["category"])})
                rows.append({"Goal": "CET1 / leverage", "Result": f"{ev['ratios']['cet1_ratio']:.2f}% / {ev['ratios']['leverage_ratio']:.2f}%"})
                table(rows, ["Goal", "Result"])
            for n in o["notes"]:
                st.caption("⚙️ " + n)
            if same_as and o["levers_clean"]:
                st.caption(f"⚙️ Once sized, this ends up the same as Option {same_as}: the line is tight, so different "
                           "strategies need the same moves.")
    if res.get("revised"):
        st.markdown('<span class="muted">The AI revised these after the app tested its first ideas.</span>', unsafe_allow_html=True)
    with st.expander("How these options were found"):
        for t in res["trail"]:
            st.write("• " + t)
        st.write("• The AI chose the moves and their order; the app chose the amounts — each move used only as far as needed to "
                 f"clear the line with a cushion of {E.SIZE_MARGIN:.0%} of the gap (or in full if that isn't possible) — and dropped any move that didn't help (notes marked ⚙️).")
        st.write("• Assumptions: businesses are sold at book value with their matching funding; securities carry a "
                 f"{E.SECURITIES_RW:.0%} risk weight; new equity arrives as cash.")
    show_ai(res["explanation"], "Which option fits best", "options")
    if st.button("↻ Ask the AI for fresh options"):
        S["ai_cache"].pop(key, None)
        st.rerun()

    # ---- 4. try your own (code only) ----
    st.markdown("### 4  Try your own")
    st.markdown('<span class="muted">Set the moves yourself; the app tests them instantly. No AI here.</span>', unsafe_allow_html=True)
    mine = []
    cols = st.columns(2)
    j = 0
    for n, b in menu["businesses"].items():
        v = cols[j % 2].number_input(f"Sell: {n} (US$bn, max {b['max'] / 1e6:.1f})", 0.0, b["max"] / 1e6, 0.0, 1.0, key=f"own_{fp(n)}")
        mine.append({"lever": "sell_business", "business": n, "amount_bn": v})
        j += 1
    for k, cap in menu["levers"].items():
        if k == "sell_business":
            continue
        label = {"raise_equity": "Raise new equity", "replace_debt_with_stock": "Pay in shares instead of debt",
                 "sell_securities": "Buyer sells securities", "book_in_branch": "Keep lending in the U.S. branch"}[k]
        v = cols[j % 2].number_input(f"{label} (US$bn, max {cap / 1e6:.1f})", 0.0, cap / 1e6, 0.0, 1.0, key=f"own_{k}")
        mine.append({"lever": k, "amount_bn": v})
        j += 1
    own = test_option({"title": "Your option", "levers": mine}, base, menu, goals)
    table([{"Goal": GOAL_SHORT[g["id"]], "Result": pill("met" if own["verdicts"][g["id"]] else "not_met")
            + (f" <span class='muted'>{E.bn(own['short'][g['id']])} short</span>" if own["short"].get(g["id"]) and own["short"][g["id"]] > 0 else "")}
           for g in goals] + [{"Goal": "Ends up in", "Result": E.cat_label(own["ev"]["category"])},
                              {"Goal": "CET1 / leverage", "Result": f"{own['ev']['ratios']['cet1_ratio']:.2f}% / {own['ev']['ratios']['leverage_ratio']:.2f}%"}],
          ["Goal", "Result"])


NEXT_STEPS = {
    "Size category": "Plan for the new category's requirements to be in place by closing — supervisors expect it.",
    "Annual capital plan (CCAR)": "Start building the capital plan and stress-testing capability (12 CFR 225.8).",
    "Supervisory stress test": "Prepare for the Fed's supervisory stress test cycle.",
    "Supplementary leverage ratio (3%)": "Model the combined supplementary leverage ratio using both banks' leverage exposure.",
    "Liquidity coverage ratio / NSFR": "Check whether the combined bank's funding mix triggers the liquidity coverage ratio.",
    "Hold all U.S. subsidiaries": "Place the bank being bought under the U.S. intermediate holding company.",
    "U.S. companies held outside the IHC": "Confirm each U.S. company outside the IHC falls within an exception, or move it under the IHC.",
    "U.S. risk committee": "Set up the U.S. risk committee and appoint a U.S. chief risk officer (12 CFR 252.155).",
    "Liquidity stress tests": "Build U.S. liquidity stress testing and hold a U.S. liquidity buffer (12 CFR 252.157).",
    "Capital stress testing": "Prepare for capital stress testing of the U.S. operations (12 CFR 252.158).",
    "Certify the parent": "Prepare the certification that the parent meets Basel-consistent home capital standards (12 CFR 252.154).",
    "Reg K exemptions": "Before signing, map which non-banking holdings outside the U.S. rely on the exemptions, and consider asking the Fed for a specific determination of eligibility (12 CFR 211.23(e)) or restructuring the deal.",
    "Reg K test": "Confirm the Reg K tests with revenue and net income from the annual report; consider asking the Fed for a specific determination (12 CFR 211.23(e)).",
    "Holdings the parent may have to sell": "Run or finish the holdings review; for each holding marked 'likely must sell', confirm the facts and plan the sale or restructuring (12 CFR 211.23).",
    "Parent's capital ratios": "Load the parent's Pillar 3 report to check its OSFI ratios.",
    "Four-quarter average size": "Upload the other three quarters of FR Y-9C data to confirm the size category.",
}


FLAGGED = ("not_met", "newly_applies", "warning", "unknown", "review")


def workflow_findings(d, rows):
    """Everything the workflow found, as text for the issues list and the memo - and which parts were included."""
    a, t = d["a"], d["t"]
    who = f"{saved('parent_key')} (through its U.S. arm {nice_name(a['name'])})" if saved("canadian") else nice_name(a["name"])
    deal_line = f"DEAL: {who} buying {nice_name(t['name'])}. Data as of {', '.join(d['quarters'])}."
    if closing_date():
        deal_line += f" Expected closing {closing_date():%d %B %Y}."
    parts = [deal_line]
    included = {}
    reads = [S["ai_cache"].get(fp("read-filing", b["rssd"], b["quarter"], len(b.get("raw") or {}))) for b in (a, t)]
    if all(reads):
        m = sum(r["check"]["counts"]["match"] for r in reads)
        c = sum(r["check"]["checked"] for r in reads)
        parts.append(f"FILINGS: the AI read both FR Y-9C filings; the app confirmed {m} of {c} figures exactly against the filed values.")
        included["Filings read by AI"] = True
    for b in (a, t):
        prof, sh = E.bank_profile(b)
        bits = [f"total assets {E.bn(b['total_assets'])}", f"CET1 ratio {pct(b['cet1_ratio'])}"]
        if "AOCI as % of CET1" in sh:
            bits.append(f"AOCI {E.bn(prof['AOCI'])} = {sh['AOCI as % of CET1']:.1f}% of CET1"
                        + (" (AOCI opt-out elected)" if prof.get("AOCI opt-out election (1 = opted out)") == 1 else ""))
        if "Goodwill as % of equity" in sh:
            bits.append(f"goodwill {sh['Goodwill as % of equity']:.1f}% of equity")
        parts.append(f"BANK - {nice_name(b['name'])}: " + "; ".join(bits) + ".")
    sig = E.holding_signals(t)
    if sig:
        parts.append(f"BANK BEING BOUGHT - balance-sheet lines a U.S. holding company may need to sell or conform (exact, from its "
                     f"FR Y-9C): " + "; ".join(f"{s['label']} {E.money(s['value'])}" for s in sig) + ".")
    parts.append("RESULTS (status | check | detail | source):\n" + "\n".join(
        f"- {E.STATUS[r['status']][1]} | {r['check']} | {r['detail']} | {r['src']}" for r in rows))
    cmp_, rules = rule_cmp(d), S["ai_cache"].get(rule_facts(d)[1])
    if cmp_:
        parts.append(f"RULES: the AI applied 12 CFR 252.5 and the requirement sections itself and agreed with the built-in rulebook on "
                     f"{cmp_['agree']} of {cmp_['total']} points. Other triggers the app cannot test: "
                     + "; ".join(f"{x.get('trigger')} ({x.get('threshold')})" for x in (rules.get("other_triggers") or [])[:4]) + ".")
        included["Rules applied by AI"] = True
    if saved("canadian"):
        parts.append("REG K CHOICE: " + re.sub(r"<[^>]+>", "", two_ways_out(canadian(d)["q"])[1]))
        disp = disposal_current()
        if disp:
            groups = {k: [nice_name(r["name"]) for r in disp["rows"] if r["verdict"] == k] for k in E.VERDICTS}
            parts.append("HOLDINGS DISPOSAL REVIEW (AI verdicts checked by the app): " + "; ".join(
                f"{E.VERDICTS[k][0]}: {', '.join(v[:6])}" for k, v in groups.items() if v) + ".")
            included["Disposal review"] = True
        else:
            included["Disposal review"] = False
    an = S.get("analyst_last")
    if an and an["deal"] == fp(saved("acq"), saved("tgt")):
        parts.append("AI ANALYST FINDINGS (numbers from the app's calculator):\n" + an["report"])
        included["AI analyst"] = True
    else:
        included["AI analyst"] = False
    opt = S.get("options_result")
    if opt and opt["deal"] == fp(saved("acq"), saved("tgt")):
        parts.append(f"DEAL OPTIONS ({opt['preset']} background), tested by the app: " + (
            "; ".join(f"{t_} - {m_}" for t_, m_ in opt["works"]) + " - these keep it under the line" if opt["works"]
            else "none of the tested restructurings cleared every line") + ".")
        included["Deal options"] = True
    else:
        included["Deal options"] = False
    return "\n\n".join(p for p in parts if p), included


def memo_passages(d, rows):
    q = [("section", "12 CFR 252.5", None, 2), ("section", "12 CFR 225.8", "$100 billion asset threshold", 1),
         ("section", "12 CFR 217.10", "supplementary leverage ratio of 3 percent", 1), ("section", "12 CFR 217.11", "capital conservation buffer", 1),
         ("section", "12 CFR 217.22", "AOCI opt-out election", 1), ("section", "12 CFR 251.3", "consolidated liabilities", 1)]
    if saved("canadian"):
        q += [("section", "12 CFR 211.23", None, 4), ("section", "12 CFR 252.153", "intermediate holding company", 1),
              ("section", "12 CFR 252.154", "combined U.S. assets of $100 billion", 1)]
    passages = ai.fetch_sections(q, LIB)
    flagged = " ".join(r["check"] for r in rows if r["status"] in FLAGGED)[:300]
    for p in LIB.search(flagged, k=3) if flagged else []:
        if p["id"] not in {x["id"] for x in passages}:
            passages.append(p)
    return passages


def build_issues(d, rows, facts, passages):
    rows_text = "\n".join(f"[R{i}] {E.STATUS[r['status']][1]} | {r['check']} | {r['detail']} | {r['src']}" for i, r in enumerate(rows, 1))
    issues = ai.issues_list("Summary", rows_text, facts, passages)
    need = {i for i, r in enumerate(rows, 1) if r["status"] in FLAGGED}
    covered = {c for it in issues for c in it["covers"]}
    missing = sorted(need - covered)
    if missing:   # code's safety net: nothing flagged may be dropped
        acts = []
        for i in missing:
            r = rows[i - 1]
            text = next((t for k, t in NEXT_STEPS.items() if r["check"].startswith(k)), f"Review: {r['detail']}.")
            acts.append(f"{r['check']}: {text}")
        issues.append({"title": "Also flagged — added by the app", "severity": "medium", "why": "The AI's list did not cover these results.",
                       "action": " ".join(acts), "interacts_with": [], "covers": missing, "added_by_app": True})
    return {"issues": issues, "missing": missing, "need": len(need)}


def issues_text(issues):
    return "\n".join(f"{i}. [{it['severity']}] {it['title']} - {it['why']} Action: {it['action']}" for i, it in enumerate(issues, 1))


def memo_body(m, passages):
    """The memo's words with real citations (no greeting/sign-off) - for the word count and the number check."""
    lines = [law(m["bottom_line"], passages)] + [f"{f.get('heading', '')}. {law(f.get('text', ''), passages)}" for f in m["findings"]]
    return "\n".join(lines + [law(r, passages) for r in m["recommendations"]] + [law(m["caveat"], passages)])


def build_memo(facts, issues, passages):
    """Draft -> (tighten until it fits one page) -> second-AI check -> revise what it flags -> repeat, a bounded number of times."""
    it_text = issues_text(issues)
    m = ai.partner_memo("Summary", facts, it_text, passages)
    count = lambda mm: len(memo_body(mm, passages).split())
    strip = lambda mm: json.dumps({k: mm[k] for k in mm if k != "citations"})
    raw = lambda mm: "\n".join([mm["bottom_line"]] + [f"{f.get('heading', '')}. {f.get('text', '')}" for f in mm["findings"]]
                                + mm["recommendations"] + [mm["caveat"]])
    shortened, revised, verdict = False, 0, None

    def tighten(mm):
        nonlocal shortened
        for _ in range(2):
            if count(mm) <= ai.MEMO_WORD_LIMIT:
                break
            m2 = ai.partner_memo("Summary", facts, it_text, passages, shorten_from=strip(mm), words=count(mm))
            if m2["bottom_line"] and m2["findings"]:
                mm, shortened = m2, True
        return mm

    m = tighten(m)
    for round_ in range(3):
        verdict = ai.check_memo("Summary", raw(m), facts, passages)
        if verdict["supported"] or round_ == 2:
            break
        m2 = ai.partner_memo("Summary", facts, it_text, passages, fix={"unsupported": verdict["unsupported"], "memo": strip(m)})
        if not (m2["bottom_line"] and m2["findings"]):
            break
        m, revised = tighten(m2), revised + 1
    nums = E.verify_numbers(memo_body(m, passages), facts + it_text)
    return {"memo": m, "words": count(m), "shortened": shortened, "revised": revised, "verdict": verdict, "numbers": nums}


def memo_email(m, passages, to, frm, client):
    """The memo as an email: (subject, plain text, html)."""
    subj = (f"{client} — " if client else "") + m["subject"]
    first = (to or "").split()[0] if (to or "").strip() else ""
    L = lambda x: law(x, passages)
    plain = [f"Hi {first}," if first else "Hi,", "", f"Bottom line: {L(m['bottom_line'])}", "", "Key findings"]
    plain += [f"{i}. {f.get('heading', '')}. {L(f.get('text', ''))}" for i, f in enumerate(m["findings"], 1)]
    plain += ["", "Recommended next steps"] + [f"- {L(r)}" for r in m["recommendations"]]
    plain += ["", L(m["caveat"]), "", "Best,", frm or ""]
    esc = lambda x: (x or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = (f"<p>{'Hi ' + esc(first) + ',' if first else 'Hi,'}</p><p><b>Bottom line:</b> {esc(L(m['bottom_line']))}</p>"
            "<p style='margin-bottom:4px'><b>Key findings</b></p><ol style='margin-top:0'>"
            + "".join(f"<li><b>{esc(f.get('heading', ''))}.</b> {esc(L(f.get('text', '')))}</li>" for f in m["findings"]) + "</ol>"
            "<p style='margin-bottom:4px'><b>Recommended next steps</b></p><ul style='margin-top:0'>"
            + "".join(f"<li>{esc(L(r))}</li>" for r in m["recommendations"]) + "</ul>"
            f"<p style='color:#6b7280'><i>{esc(L(m['caveat']))}</i></p><p>Best,<br>{esc(frm)}</p>")
    return subj, "\n".join(plain), html


def make_eml(subj, plain, html, to_addr=""):
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["Subject"] = subj
    msg["To"] = to_addr or ""
    msg["X-Unsent"] = "1"          # opens as a draft ready to send in Outlook
    msg.set_content(plain)
    msg.add_alternative(f"<html><body style='font-family:Calibri,Arial,sans-serif;font-size:11pt'>{html}</body></html>", subtype="html")
    return msg.as_bytes()


def make_memo_docx(m, passages, to, frm, client, d):
    """One-page memorandum in Word."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, Inches, RGBColor
    doc = Document()
    for sec in doc.sections:
        sec.top_margin = sec.bottom_margin = Inches(0.75)
        sec.left_margin = sec.right_margin = Inches(0.95)
    st_ = doc.styles["Normal"]
    st_.font.name, st_.font.size = "Calibri", Pt(10.5)
    st_.paragraph_format.space_after, st_.paragraph_format.space_before = Pt(4), Pt(0)
    st_.paragraph_format.line_spacing = 1.05
    L = lambda x: law(x, passages)

    def para(text="", bold_lead=None, size=None, italic=False, color=None, align=None, after=None):
        p = doc.add_paragraph()
        if bold_lead:
            r = p.add_run(bold_lead)
            r.bold = True
        r = p.add_run(text)
        r.italic = italic
        if size:
            for run in p.runs:
                run.font.size = Pt(size)
        if color:
            for run in p.runs:
                run.font.color.rgb = RGBColor(*color)
        if align:
            p.alignment = align
        if after is not None:
            p.paragraph_format.space_after = Pt(after)
        return p

    para("PRIVILEGED & CONFIDENTIAL — ATTORNEY WORK PRODUCT", size=8, color=(107, 114, 128), align=WD_ALIGN_PARAGRAPH.RIGHT, after=2)
    t = para("MEMORANDUM", size=15, after=4)
    t.runs[0].bold = True
    for lead, val in (("TO:\t", to or "Supervising partner"), ("FROM:\t", frm or ""), ("DATE:\t", datetime.date.today().strftime("%d %B %Y")),
                      ("RE:\t", (f"{client} — " if client else "") + m["subject"])):
        para(val, bold_lead=lead, after=0)
    rule = para(after=6)
    pPr = rule._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for k, v in (("w:val", "single"), ("w:sz", "6"), ("w:space", "1"), ("w:color", "1F3A93")):
        bottom.set(qn(k), v)
    bdr.append(bottom)
    pPr.append(bdr)
    para(L(m["bottom_line"]), bold_lead="Bottom line. ", after=5)
    h = para("Key findings", after=2)
    h.runs[0].bold = True
    for i, f in enumerate(m["findings"], 1):
        para(L(f.get("text", "")), bold_lead=f"{i}. {f.get('heading', '')}. ", after=3)
    h = para("Recommended next steps", after=2)
    h.runs[0].bold = True
    for r in m["recommendations"]:
        p = doc.add_paragraph(L(r), style="List Bullet")
        p.paragraph_format.space_after = Pt(1)
    para(L(m["caveat"]), italic=True, size=8.5, color=(107, 114, 128), after=0)
    para(f"Prepared with the Bank Merger Regulatory Check app from FR Y-9C data as of {', '.join(d['quarters'])}. "
         "Figures calculated by the app; drafting by AI and checked by the app — verify before relying on it.",
         italic=True, size=8, color=(107, 114, 128))
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def page_summary():
    header("summary")
    if not ready():
        return need_banks()
    d = deal()
    rows = summary_rows(d)
    st.markdown(f'<p class="lede"><b>{nice_name(d["a"]["name"])}</b> buying <b>{nice_name(d["t"]["name"])}</b> · '
                f'data as of {", ".join(d["quarters"])}</p>', unsafe_allow_html=True)
    counts(rows)
    show_summary_table(rows)
    facts, included = workflow_findings(d, rows)

    # ---- what feeds the memo ----
    missing_parts = [k for k, v in included.items() if not v]
    not_run = lambda k: f'<span class="pill" style="background:#6b72801a;color:#6b7280">○&nbsp; {k} — not run</span>'
    st.markdown("**In this summary:** " + " ".join(badge(True, k) if v else not_run(k) for k, v in included.items()),
                unsafe_allow_html=True)
    if missing_parts:
        target = {"AI analyst": "analyst", "Deal options": "options", "Disposal review": "canadian"}
        cols = st.columns(len(missing_parts) + 1)
        for col, k in zip(cols, missing_parts):
            col.button(f"Run: {k} →", key=f"run_{k}", on_click=go, args=(target[k],), width="stretch")
        st.caption("Optional — run them and this page updates to include their findings.")

    # ---- next steps: the issues list ----
    st.markdown("### Next steps")
    passages = memo_passages(d, rows)
    if not ai.ready():
        st.info("Add your API key in the left-hand panel for the AI's issues list and the partner memo.")
        return
    ikey = fp("issues", facts)
    (iss,) = run_many([(ikey, lambda: build_issues(d, rows, facts, passages))],
                      "The AI is weighing every result into a ranked issues list, and the app is checking nothing was dropped…")
    if not iss:
        return
    st.markdown(f'<span class="ai-tag">✨ Ranked by AI</span> <span class="code-tag">checked by the app</span>&nbsp; '
                + badge(not iss["missing"], f"all {iss['need']} flagged results are covered" if not iss["missing"] else
                        f"the app added {len(iss['missing'])} result(s) the AI missed"), unsafe_allow_html=True)
    sev_col = {"high": "#b42318", "medium": "#b26a00", "low": "#6b7280"}
    for i, it in enumerate(iss["issues"], 1):
        colour = sev_col.get(it["severity"], "#6b7280")
        links = (f"<br><span class='muted'>Interacts with: {'; '.join(it['interacts_with'])}</span>" if it["interacts_with"] else "")
        covers = ", ".join(rows[c - 1]["check"] for c in it["covers"] if 0 < c <= len(rows))
        st.markdown(f'<div class="card" style="margin-bottom:10px;border-left:4px solid {colour}">'
                    f'<b>{i}. {it["title"]}</b> &nbsp;<span class="pill" style="background:{colour}1a;color:{colour}">'
                    f'{it["severity"].capitalize()}</span>{" &nbsp;" + badge(None, "added by the app") if it.get("added_by_app") else ""}'
                    f'<br>{law(it["why"], passages)}<br><b>Next step:</b> {law(it["action"], passages)}{links}'
                    f'<br><span class="muted" style="font-size:13px">Covers: {covers or "—"}</span></div>', unsafe_allow_html=True)

    # ---- the partner memo ----
    st.markdown("### Memo to the partner")
    st.markdown('<p class="lede">One page, ready to email: the AI drafts it from everything above; the app converts its citations to '
                'the real regulations, keeps it to one page, checks every figure against the app\'s results, and a second AI call '
                'checks every legal statement against its source.</p>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    to = c1.text_input("To", value=saved("memo_to", ""), placeholder="e.g. Jane Smith")
    frm = c2.text_input("From", value=saved("memo_from", ""), placeholder="Your name")
    client = c3.text_input("Client / matter", value=saved("memo_client", ""), placeholder="e.g. Project Maple")
    keep("memo_to", to)
    keep("memo_from", frm)
    keep("memo_client", client)
    mkey = fp("memo", facts, issues_text(iss["issues"]))
    (memo,) = run_many([(mkey, lambda: build_memo(facts, iss["issues"], passages))],
                       "The AI is drafting the partner memo; then the app and a second AI call are checking it…")
    if not memo:
        return
    m = memo["memo"]
    v = memo["verdict"]
    nums = memo["numbers"]
    checks = [badge(memo["words"] <= ai.MEMO_WORD_LIMIT, f"one page — {memo['words']} words" + (" (tightened by AI)" if memo["shortened"] else "")),
              badge(not nums["unverified"], f"all {nums['checked']} figures match the app's results" if not nums["unverified"]
                    else f"check: {', '.join(nums['unverified'][:3])}"),
              badge(not m["citations"]["invalid"], "every citation is a regulation in the library"),
              badge(True if v.get("supported") else None,
                    ("second AI check: every statement supported"
                     + (f" (after {memo['revised']} revision{'s' if memo['revised'] > 1 else ''})" if memo.get("revised") else ""))
                    if v.get("supported") else f"second AI check: {len(v.get('unsupported', []))} statement(s) to verify — see below")]
    st.markdown(" ".join(checks), unsafe_allow_html=True)
    subj, plain, html = memo_email(m, passages, to, frm, client)
    st.markdown(f'<div class="card" style="margin-top:10px"><div class="muted" style="border-bottom:1px solid var(--line);'
                f'padding-bottom:8px;margin-bottom:10px"><b>To:</b> {to or "—"} &nbsp;·&nbsp; <b>Subject:</b> {subj}</div>'
                f'<div style="font-size:15.5px;line-height:1.55">{html}</div></div>', unsafe_allow_html=True)
    if not v.get("supported") and v.get("unsupported"):
        st.warning("Before sending, verify: " + " ".join(f"“{u['sentence']}” — {u.get('problem', '')}" for u in v["unsupported"][:3]))
    st.write("")
    c1, c2, c3 = st.columns(3)
    c1.download_button("⬇ Memo as Word (1 page)", make_memo_docx(m, passages, to, frm, client, d), file_name="memo_to_partner.docx",
                       type="primary", width="stretch")
    c2.download_button("✉ Open as email draft", make_eml(subj, plain, html), file_name="memo_to_partner.eml",
                       width="stretch", help="Opens in Outlook or Mail as a draft, ready to address and send.")
    if c3.button("↻ Redraft the memo", width="stretch"):
        S["ai_cache"].pop(mkey, None)
        st.rerun()
    with st.expander("Copy the email text"):
        st.code(f"Subject: {subj}\n\n{plain}", language=None, wrap_lines=True)

    st.markdown("### Full report")
    c1, c2 = st.columns(2)
    c1.download_button("Download the full report (Word)", make_docx(d, rows, iss["issues"], plain, passages),
                       file_name="merger_regulatory_report.docx", width="stretch")
    c2.download_button("Download the AI audit trail", json.dumps(S.get("audit", []), indent=2), file_name="ai_audit_trail.json",
                       width="stretch")
    chat_box("5 Summary", facts)


def make_docx(d, rows, issues, memo_plain, passages):
    from docx import Document
    doc = Document()
    doc.add_heading("Bank merger regulatory check", 0)
    doc.add_paragraph(f"{nice_name(d['a']['name'])} buying {nice_name(d['t']['name'])}. Data as of {', '.join(d['quarters'])}.")
    doc.add_heading("Results", 1)
    tbl = doc.add_table(rows=1, cols=4)
    tbl.style = "Light Grid Accent 1"
    for i, h in enumerate(["Status", "Check", "Detail", "Source"]):
        tbl.rows[0].cells[i].text = h
    for r in rows:
        cells = tbl.add_row().cells
        for i, val in enumerate([E.STATUS[r["status"]][1], r["check"], r["detail"], r["src"]]):
            cells[i].text = val
    doc.add_heading("Issues and next steps (ranked by AI, checked by the app)", 1)
    for it in issues:
        p = doc.add_paragraph(style="List Number")
        p.add_run(f"{it['title']} [{it['severity']}]. ").bold = True
        p.add_run(f"{law(it['why'], passages)} Next step: {law(it['action'], passages)}")
    doc.add_heading("Memo to the partner (AI-drafted, checked by the app)", 1)
    for para in memo_plain.split("\n"):
        if para.strip():
            doc.add_paragraph(para.strip())
    doc.add_paragraph("Screening tool, not legal advice. The combined bank is a simple sum of the two banks; verify against the filings and rules cited.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def page_sizes():
    header("sizes")
    st.markdown('<p class="lede">Which category a merger lands in depends mainly on the combined bank\'s average total assets. '
                'These made-up pairs show each step of the ladder.</p>', unsafe_allow_html=True)
    examples = [
        ("Below $100bn — no category", "Harbor Bancorp ($45bn) + Prairie Financial ($30bn)", 75e6, False),
        ("Category IV", "Lakeshore Bancorp ($85bn) + Summit Bank ($40bn)", 125e6, False),
        ("Category III", "Pacific Crest Financial ($190bn) + Gulf Coast Bancshares ($85bn)", 275e6, False),
        ("Category II", "Atlantic National ($480bn) + Continental Trust ($260bn)", 740e6, False),
        ("Category I (GSIB)", "A U.S. GSIB ($2.5tn) + Riverbend Bank ($30bn)", 2530e6, True),
    ]
    rows = []
    for label, pair, total, gsib in examples:
        cat = E.category(total, gsib)[0]
        rows.append({"Lands in": f"<b>{label}</b>", "Example deal (fictitious)": pair, "Combined": E.bn(total),
                     "What switches on": ", ".join(r[0].split(" (")[0] for r in E.REQUIREMENTS if r[1][cat] not in ("No", "Optional opt-out")) or "Base rules only"})
    table(rows, ["Lands in", "Example deal (fictitious)", "Combined", "What switches on"])
    st.markdown('<span class="muted">There is no "Category 5": below $100bn a bank simply has no category. Category I is only for '
                'U.S. GSIBs, which are identified by the Fed\'s GSIB method, not size alone. Source: 12 CFR 252.5.</span>',
                unsafe_allow_html=True)
    st.markdown("### Try your own")
    c1, c2, c3 = st.columns(3)
    x = c1.number_input("Buyer ($bn)", 0.0, value=120.0, step=5.0)
    y = c2.number_input("Bank bought ($bn)", 0.0, value=60.0, step=5.0)
    g = c3.checkbox("Buyer is a GSIB")
    cat, why = E.category((x + y) * 1e6, g)
    st.markdown(f"**{E.cat_label(cat)}** — {why}")


# ======================================================================================
if S["page"] == "canadian" and not saved("canadian"):
    S["page"] = "summary"
{"home": page_home, "setup": page_setup, "glance": page_glance, "capital": page_capital, "leverage": page_leverage,
 "canadian": page_canadian, "analyst": page_analyst, "options": page_options, "summary": page_summary, "sizes": page_sizes}[S["page"]]()
nav_buttons()
counter.markdown(f'<span class="muted">AI calls this session: <b>{S.get("ai_calls", 0)}</b></span>', unsafe_allow_html=True)
