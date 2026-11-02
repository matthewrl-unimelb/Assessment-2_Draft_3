"""
ai.py - every AI call in the app goes through this file.

Design rule:  AI READS AND EXPLAINS - engine.py CALCULATES AND DECIDES.
So the AI is never asked to do arithmetic or decide pass/fail. It is given:
  * facts the app already computed (numbers, categories, test results), and
  * passages retrieved from the closed-world regulation library (library.py),
and asked to explain, flag or draft - citing the passages by their ID, e.g. [C41].

"Closed world" is enforced in four layers:
  1. Retrieve first: only library passages are ever sent to the AI.
  2. Instructions: answer ONLY from those passages, otherwise say so.
  3. Code check: every [C#] citation must be one of the passages actually sent.
  4. Relevance floor: if the library has nothing relevant, the AI is not called at all.
Plus (Lab 2) a REFLECTION step: a second AI call checks the answer against its passages,
and if it fails, the app LOOPS - rewrites the search, retrieves again and retries.

Providers: Anthropic (Claude Haiku - cheap, for testing) or OpenAI (for submission).
No web access is ever switched on for either provider.
"""

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import streamlit as st

DEFAULT_MODELS = {"Anthropic (Claude)": "claude-haiku-5-5", "OpenAI": "gpt-4o-mini"}
RELEVANCE_FLOOR = 4.0     # minimum BM25 score for the best passage before the AI is called
MAX_LOOPS = 2             # reflection retries for the question box

CLOSED_WORLD_RULES = (
    "You are an assistant to a U.S./Canadian banking M&A lawyer. Rules you must follow:\n"
    "1. Use ONLY the numbered passages and the APP FACTS provided in this message. Do not use outside "
    "knowledge, do not mention cases, rules or numbers that are not in them.\n"
    "2. After every sentence that relies on a passage, cite it in square brackets with its ID, e.g. [C41]. Do not cite the app facts.\n"
    "3. Never do arithmetic and never decide pass/fail yourself - the APP FACTS already contain the "
    "computed numbers and results; repeat them, do not change them.\n"
    "4. If the passages cannot answer the question you were asked, say so once: 'The loaded regulations do not cover this.' "
    "Do not add such remarks about side points - simply leave them out.\n"
    "5. Plain English for a busy senior lawyer. No preamble."
)


# --------------------------------------------------------------------------------------
# Session bookkeeping: call counter and audit trail (shown in the sidebar and exported)
# --------------------------------------------------------------------------------------
def _log(step, purpose, prompt, output, passages=None, seconds=0.0):
    st.session_state.setdefault("audit", []).append({
        "time": time.strftime("%Y-%m-%d %H:%M:%S"), "step": step, "purpose": purpose,
        "passages_sent": [p["id"] + " " + p["cite"] for p in (passages or [])],
        "prompt_chars": len(prompt), "output": output, "seconds": round(seconds, 1),
    })
    st.session_state["ai_calls"] = st.session_state.get("ai_calls", 0) + 1


def ready():
    return bool(st.session_state.get("api_key")) or os.environ.get("APP_DEV_MOCK") == "1"


# --------------------------------------------------------------------------------------
# The one function that actually talks to an AI provider
# --------------------------------------------------------------------------------------
def chat(system, user, step, purpose, passages=None, max_tokens=900, want_json=False):
    provider = st.session_state.get("provider", "Anthropic (Claude)")
    model = st.session_state.get("model") or DEFAULT_MODELS[provider]
    key = st.session_state.get("api_key")
    started = time.time()

    if os.environ.get("APP_DEV_MOCK") == "1" and not key:
        text = _mock(user, passages, want_json)
    elif provider == "OpenAI":
        from openai import OpenAI
        client = OpenAI(api_key=key)
        kwargs = {"response_format": {"type": "json_object"}} if want_json else {}
        resp = client.chat.completions.create(
            model=model, max_completion_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], **kwargs)
        text = resp.choices[0].message.content or ""
    else:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        # Low effort: extended "thinking" is switched off. Otherwise the model can spend the whole
        # token allowance thinking and return no text at all (found in live testing).
        resp = client.messages.create(
            model=model, max_tokens=max_tokens, system=system, thinking={"type": "disabled"},
            messages=[{"role": "user", "content": user}])
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    if not text.strip():
        text = "The AI returned an empty answer. Press the step again or try a shorter question."
    # the AI sometimes "cites" the prompt's own section labels - those are not sources, so drop them
    text = re.sub(r"\s?\[(?:APP FACTS|RESULTS|CONTEXT|DEAL BACKGROUND|FACTS|PASSAGES|DEAL FACTS|WORKFLOW FINDINGS|ISSUES LIST)\]", "", text)

    _log(step, purpose, system + user, text, passages, time.time() - started)
    return text


def _parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return {}


def json_call(system, user, step, purpose, passages=None, max_tokens=1500, need="", retries=1):
    """An AI call that must return JSON containing `need`. If the reply is cut off or malformed, ask once more."""
    data = {}
    for attempt in range(retries + 1):
        data = _parse_json(chat(system, user, step, purpose + ("" if attempt == 0 else " (retry)"), passages,
                                max_tokens=max_tokens, want_json=True))
        if not need or data.get(need):
            return data
    return data


def _passages_block(passages):
    return "\n\n".join(f"[{p['id']}] {p['cite']} - {p['title']} (status: {p['status']})\n{p['text']}" for p in passages)


def check_citations(text, passages):
    """Layer 3 of closed world: every passage ID the AI cites - e.g. [C41] or [C41, C63] - must be one we sent."""
    sent = {p["id"] for p in passages}
    cited = set()
    for group in re.findall(r"\[([^\]]*C\d+[^\]]*)\]", text):
        cited.update(re.findall(r"C\d+", group))
    return {"cited": sorted(cited), "invalid": sorted(cited - sent), "has_citations": bool(cited)}


# --------------------------------------------------------------------------------------
# 1. Grounded explanation for a page (one AI call + code citation check)
# --------------------------------------------------------------------------------------
def explain(step, task, facts, query, lib, k=6):
    passages = lib.search(query, k=k)
    if not passages or passages[0]["score"] < RELEVANCE_FLOOR:
        return {"text": "The loaded regulations do not contain material relevant to this step.", "passages": [], "check": None}
    user = (f"TASK: {task}\n\nAPP FACTS (computed by the app - do not change):\n{facts}\n\n"
            f"PASSAGES:\n{_passages_block(passages)}")
    text = chat(CLOSED_WORLD_RULES, user, step, task[:80], passages)
    check = check_citations(text, passages)
    if check["invalid"]:
        text = _strip_invalid(text, check["invalid"])
    return {"text": text, "passages": passages, "check": check}


def explain_multi(step, task, facts, queries, lib, per_query=2):
    """Like explain(), but gathers passages topic by topic, so a guide that covers several terms gets the
    defining text of each one (still closed world). Each item in `queries` is either a search string, or a
    ("section", cite, phrase) tuple that fetches the exact section that defines the term."""
    seen, passages = set(), []
    for q in queries:
        found = lib.section(q[1], q[2], limit=1) if isinstance(q, tuple) else lib.search(q, k=per_query)
        for p in found:
            if p["id"] not in seen and p["score"] >= RELEVANCE_FLOOR:
                seen.add(p["id"])
                passages.append(p)
    if not passages:
        return {"text": "The loaded regulations do not contain material relevant to this.", "passages": [], "check": None}
    user = (f"TASK: {task}\n\nAPP FACTS (computed by the app - do not change):\n{facts}\n\n"
            f"PASSAGES:\n{_passages_block(passages)}")
    text = chat(CLOSED_WORLD_RULES, user, step, task[:80], passages, max_tokens=1400)
    check = check_citations(text, passages)
    if check["invalid"]:
        text = _strip_invalid(text, check["invalid"])
    return {"text": text, "passages": passages, "check": check}


def _strip_invalid(text, invalid):
    for cid in invalid:
        text = re.sub(rf"\b{cid}\b", "citation removed - not in sources", text)
    return text


# --------------------------------------------------------------------------------------
# 2. Reflection (Lab 2): does each sentence follow from the cited passages?
# --------------------------------------------------------------------------------------
def reflect(step, answer, passages, question):
    user = (
        "You are a strict checker. Compare the ANSWER with the PASSAGES it cites.\n"
        "Return JSON only: {\"supported\": true/false, \"answered\": true/false, \"unsupported\": [\"sentence\", ...], "
        "\"better_search\": \"keywords likely to appear in the regulation text that would answer the question, "
        "e.g. section topics and defined terms\"}.\n"
        "supported = every statement is backed by its cited passage (saying the regulations do not cover something "
        "counts as supported). answered = the passages actually answered the question asked.\n\n"
        f"QUESTION: {question}\n\nANSWER:\n{answer}\n\nPASSAGES:\n{_passages_block(passages)}")
    verdict = _parse_json(chat("Return only valid JSON.", user, step, "Reflection check", passages, max_tokens=800, want_json=True))
    verdict.setdefault("supported", False)
    verdict.setdefault("answered", True)
    verdict.setdefault("unsupported", [])
    verdict.setdefault("better_search", "")
    return verdict


# --------------------------------------------------------------------------------------
# 3. The question box: retrieve -> answer -> reflect -> loop (Lab 2 RAG + looping + reflection)
# --------------------------------------------------------------------------------------
def ask(step, question, facts, lib):
    query, trail, best = question, [], None
    for attempt in range(1, MAX_LOOPS + 1):
        passages = lib.search(query, k=6)
        if not passages or passages[0]["score"] < RELEVANCE_FLOOR:
            trail.append(f"Attempt {attempt}: nothing relevant found for '{query}' - AI not called.")
            return {"text": "I couldn't find that in the regulations loaded into this app.", "passages": [], "trail": trail, "verified": True}
        user = (f"QUESTION: {question}\n\nAPP FACTS about the deal on screen (computed by the app):\n{facts}\n\n"
                f"PASSAGES:\n{_passages_block(passages)}")
        answer = chat(CLOSED_WORLD_RULES, user, step, f"Q&A attempt {attempt}", passages)
        cites = check_citations(answer, passages)
        if cites["invalid"]:
            answer = _strip_invalid(answer, cites["invalid"])
        verdict = reflect(step, answer, passages, question)
        trail.append(f"Attempt {attempt}: searched '{query}', cited {', '.join(cites['cited']) or 'nothing'}; "
                     f"reflection says {'SUPPORTED' if verdict['supported'] else 'NOT SUPPORTED'}"
                     f"{'' if verdict['answered'] else ' but the passages did NOT answer the question'}.")
        ok = verdict["supported"] and not cites["invalid"]
        if ok:
            best = {"text": answer, "passages": passages, "trail": trail, "verified": True}
            if verdict["answered"]:
                return best
        # LOOP: search again with the checker's better keywords
        query = verdict["better_search"] or question + " definition requirement"
    if best:
        return best
    return {"text": answer + "\n\n_⚠️ The checker could not confirm every sentence of this answer against the regulations. "
            "Treat it as a lead, not a conclusion._", "passages": passages, "trail": trail, "verified": False,
            "unsupported": verdict.get("unsupported", [])}


# --------------------------------------------------------------------------------------
# 4. Data review of an uploaded bank (no passages - the AI only looks at the figures)
# --------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------
# 5. Extracting figures from a PDF (e.g. a Canadian parent's Pillar 3 / capital disclosure)
# --------------------------------------------------------------------------------------
PARENT_FIELDS = {
    "bank_name": "Name of the bank",
    "period": "Quarter-end date of the most recent column",
    "total_assets": "Total consolidated assets (balance sheet / LR1 'total consolidated assets as per published financial statements')",
    "cet1": "Common Equity Tier 1 (CET1) capital",
    "tier1": "Tier 1 capital",
    "total_capital": "Total capital",
    "rwa": "Total risk-weighted assets (RWA)",
    "leverage_exposure": "Total leverage ratio exposure measure",
    "cet1_ratio": "CET1 ratio (%)",
    "leverage_ratio": "Leverage ratio (%)",
}
AMOUNT_FIELDS = ("total_assets", "cet1", "tier1", "total_capital", "rwa", "leverage_exposure")


def extract_parent_figures(step, pages_text):
    """AI reads the KM1 'key metrics' and LR1 tables. Code then checks the result (verify_parent)."""
    user = (
        "Below are pages from a Canadian bank's Pillar 3 / supplementary regulatory capital disclosure. "
        "Tables have several quarter columns: use ONLY the FIRST (most recent) column. "
        "Amounts are in millions of Canadian dollars - copy them exactly as numbers (no commas). "
        "Ratios as percentages (e.g. 13.5). If a figure is not shown, use null. Never calculate or guess. "
        "For each figure give a short quote of the row you used.\n"
        "Return JSON only, in this shape: {"
        + ", ".join(f'"{k}": {{"value": ..., "found_as": "..."}}' for k in PARENT_FIELDS)
        + "}\n\nFIGURES WANTED:\n" + "\n".join(f"- {k}: {v}" for k, v in PARENT_FIELDS.items())
        + f"\n\nPAGES:\n{pages_text[:40000]}")
    raw = _parse_json(chat("Return only valid JSON.", user, step, "Read parent's Pillar 3 report", max_tokens=1500, want_json=True))
    out = {}
    for k in PARENT_FIELDS:
        item = raw.get(k) if isinstance(raw.get(k), dict) else {"value": raw.get(k), "found_as": ""}
        v = item.get("value")
        if k in AMOUNT_FIELDS or k in ("cet1_ratio", "leverage_ratio"):
            try:
                v = float(str(v).replace(",", "").replace("%", "")) if v not in (None, "", "null") else None
            except ValueError:
                v = None
        out[k] = {"value": v, "found_as": item.get("found_as", "")}
    return out


def verify_parent(fig):
    """CODE check of the AI's extraction: do the amounts reproduce the bank's own reported ratios?"""
    v = {k: fig.get(k, {}).get("value") for k in fig}
    checks = []
    for label, num, den, reported in (("CET1 ratio", "cet1", "rwa", "cet1_ratio"), ("Leverage ratio", "tier1", "leverage_exposure", "leverage_ratio")):
        if v.get(num) and v.get(den) and v.get(reported):
            calc = 100 * v[num] / v[den]
            checks.append({"check": label, "ok": abs(calc - v[reported]) < 0.15,
                           "result": f"{calc:.2f}% recomputed vs {v[reported]:.2f}% reported"})
        else:
            checks.append({"check": label, "ok": None, "result": "a figure is missing"})
    if v.get("tier1") and v.get("cet1"):
        checks.append({"check": "Tier 1 ≥ CET1", "ok": v["tier1"] >= v["cet1"], "result": "consistent" if v["tier1"] >= v["cet1"] else "inconsistent"})
    return checks


def find_capital_pages(pdf_reader):
    """CODE (not AI) finds the KM1 key-metrics and LR1 leverage pages, skipping the table of contents,
    so the AI reads 2-4 pages instead of 100."""
    import re
    keep = []
    for i, page in enumerate(pdf_reader.pages):
        t = page.extract_text() or ""
        head = t[:400].upper()
        if "TABLE OF CONTENTS" in head or "INDEX" in head:
            continue
        is_km1 = re.search(r"KM1", t) and re.search(r"Common Equity Tier 1", t, re.I) and re.search(r"leverage", t, re.I)
        is_lr1 = re.search(r"LR1", t) and re.search(r"[Tt]otal consolidated assets", t)
        if is_km1 or is_lr1:
            keep.append((i, t))
        if len(keep) >= 4:
            break
    if not keep:  # fall back: pages that mention the key words most
        scored = sorted(((sum(t.lower().count(w) for w in ("cet1", "risk-weighted", "leverage")), i, t)
                         for i, t in ((i, p.extract_text() or "") for i, p in enumerate(pdf_reader.pages))), reverse=True)[:4]
        keep = sorted((i, t) for _, i, t in scored)
    return "\n\n".join(f"--- page {i + 1} ---\n{t}" for i, t in keep), [i + 1 for i, _ in keep]


# --------------------------------------------------------------------------------------
# 6. Reading the parent's list of subsidiaries (annual report) for the Reg K holdings review.
#    find_subsidiary_pages keeps only the pages of a long PDF that list companies, for the holdings review.
# --------------------------------------------------------------------------------------
ACTIVITIES = ["Banking", "Holding company", "Lending / finance", "Securities & investment", "Insurance", "Funds & trusts",
              "Real estate", "Other financial", "Non-financial (commercial)", "Not classified"]


def find_subsidiary_pages(pdf_reader, max_pages=6):
    """CODE picks the pages that list subsidiaries, so the AI reads a few pages, not the whole annual report."""
    scored = []
    for i, page in enumerate(pdf_reader.pages):
        t = page.extract_text() or ""
        low = t.lower()
        score = low.count("subsidiar") * 3 + low.count("limited") + low.count("inc.") + low.count("llc")
        if "subsidiar" in low and score >= 8:
            scored.append((score, i, t))
    keep = sorted(sorted(scored, reverse=True)[:max_pages], key=lambda x: x[1])
    return "\n\n".join(f"--- page {i + 1} ---\n{t}" for _, i, t in keep), [i + 1 for _, i, _ in keep]


# --------------------------------------------------------------------------------------
# 7. Deal options ("stay under the line"): AI PROPOSES, code TESTS, AI REVISES, AI EXPLAINS
# --------------------------------------------------------------------------------------
OPTION_QUERIES = {
    "category": [("section", "12 CFR 252.5", None, 3)],
    "capital": [("section", "12 CFR 217.10", "common equity tier 1 capital ratio"), ("section", "12 CFR 217.11", "capital conservation buffer")],
    "liabilities": [("section", "12 CFR 251.3", "consolidated liabilities")],
    "regk": [("section", "12 CFR 211.23", "qualifying foreign banking organization"), ("section", "12 CFR 211.23", "loss of eligibility")],
    "subpart_o": [("section", "12 CFR 252.154", "combined U.S. assets of $100 billion"), ("section", "12 CFR 252.155", "combined U.S. assets of $100 billion"),
                  ("section", "12 CFR 252.153", "intermediate holding company")],
}


def option_passages(goal_ids, lib):
    seen, out = set(), []
    for gid in goal_ids:
        for q in OPTION_QUERIES.get(gid, []):
            for p in lib.section(q[1], q[2], limit=q[3] if len(q) > 3 else 1):
                if p["id"] not in seen:
                    seen.add(p["id"])
                    out.append(p)
    return out


def propose_options(step, story, client_note, menu_text, goals_text, facts, passages, feedback=None):
    """Returns {"options": [{"title", "levers": [{"lever", "business", "amount_bn"}], "why", "downside"}]}.
    The AI chooses the moves and amounts; it is told NOT to work out results - the app tests every option."""
    task = (
        "You are advising a bank M&A team on how to restructure a merger so it stays on the right side of the regulatory lines "
        "listed under GOALS. Propose exactly 3 genuinely different STRATEGIES (e.g. least disruption to the franchise; sell "
        "businesses; combine moves). For each, list the moves from the MENU in the order the client would prefer to use them. "
        "You do NOT choose amounts: the app sizes each move, using it only as far as needed (it stops once the goals are met), "
        "then tests the result. Leave max_bn null unless the client has EXPLICITLY limited that move (e.g. 'sell at most half "
        "of it'); never invent a limit. Respect "
        "the DEAL BACKGROUND. Skip goals marked CANNOT be reached. Do not state numbers or predict whether an option works.\n"
        "Return JSON only: {\"options\": [{\"title\": \"4-7 words\", \"moves\": [{\"lever\": \"one of the MENU keys\", "
        "\"business\": \"exact business name, only for sell_business\", \"max_bn\": null}], \"why\": \"one sentence on the idea "
        "and the rule it targets, citing passages like [C12]\", \"downside\": \"one sentence on what it costs the client\"}]}")
    if feedback:
        task += ("\n\nSECOND TRY. The app sized and tested your first strategies. RESULTS below says which goals each one missed "
                 "and by how much, even with every listed move used as far as allowed. Return 3 strategies again: keep any that "
                 "passed unchanged. Every strategy that fell short MUST add at least one more move from the MENU (and drop any "
                 "max_bn the client did not ask for); otherwise it will fail again.\n"
                 f"RESULTS:\n{feedback}")
    user = (f"{task}\n\nDEAL BACKGROUND:\n{story}\n{('Client also said: ' + client_note) if client_note else ''}\n\n"
            f"GOALS (worked out by the app):\n{goals_text}\n\nMENU:\n{menu_text}\n\nAPP FACTS:\n{facts}\n\n"
            f"PASSAGES:\n{_passages_block(passages)}")
    data = {}
    for attempt in (1, 2):   # if the JSON does not parse (e.g. cut off), ask once more
        text = chat(CLOSED_WORLD_RULES + "\nReturn only valid JSON. Keep each 'why' and 'downside' to one sentence. "
                    "Never write that the regulations do not cover something inside 'why' or 'downside'.", user, step,
                    ("Deal options - revised proposal" if feedback else "Deal options - proposal") + ("" if attempt == 1 else " (retry)"),
                    passages, max_tokens=2200, want_json=True)
        data = _parse_json(text)
        if data.get("options"):
            break
    opts = [o for o in data.get("options", []) if isinstance(o, dict)][:3]
    for o in opts:
        for k in ("why", "downside"):
            chk = check_citations(str(o.get(k, "")), passages)
            if chk["invalid"]:
                o[k] = _strip_invalid(str(o.get(k, "")), chk["invalid"])
    return {"options": opts}


def explain_options(step, story, results_text, passages):
    task = ("The app has tested each restructuring option against the rules (RESULTS - the verdicts are final, do not change "
            "them). In under 220 words, for a senior M&A lawyer: which option best fits the client's DEAL BACKGROUND and why; "
            "what each option costs the client; and anything a regulator would look at (e.g. whether a sale must close before "
            "the four-quarter average falls, or that a branch keeps assets in the U.S.). Cite passages. No preamble.")
    user = f"TASK: {task}\n\nDEAL BACKGROUND:\n{story}\n\nRESULTS:\n{results_text}\n\nPASSAGES:\n{_passages_block(passages)}"
    text = chat(CLOSED_WORLD_RULES + "\nCite only passage IDs such as [C12] - never cite RESULTS or the app.", user, step,
                "Deal options - explanation", passages, max_tokens=900)
    text = re.sub(r"\s?\[(RESULTS|APP FACTS|DEAL BACKGROUND)\]", "", text)
    check = check_citations(text, passages)
    if check["invalid"]:
        text = _strip_invalid(text, check["invalid"])
    return {"text": text, "passages": passages, "check": check}


# --------------------------------------------------------------------------------------
# 8. Running independent AI calls at the same time (so a page with three AI tasks takes as long as one)
# --------------------------------------------------------------------------------------
def parallel(fns, workers=6):
    """Run callables at once and return their results in order. Each thread is attached to this Streamlit
    session, so the calls still count in the sidebar and land in the audit trail."""
    if len(fns) <= 1:
        return [f() for f in fns]
    try:
        from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
        ctx = get_script_run_ctx()
    except Exception:       # pragma: no cover - outside Streamlit
        add_script_run_ctx, ctx = None, None

    def wrap(fn):
        def run():
            if ctx is not None:
                add_script_run_ctx(threading.current_thread(), ctx)
            return fn()
        return run

    with ThreadPoolExecutor(max_workers=min(workers, len(fns))) as ex:
        futures = [ex.submit(wrap(f)) for f in fns]
        return [f.result() for f in futures]


def cites_to_law(text, passages):
    """For a partner-ready email: turn the app's passage IDs ([C914][C915]) into real citations ((12 CFR 211.23))."""
    by_id = {p["id"]: re.sub(r"\s*\(part \d+\)$", "", p["cite"]) for p in passages}

    def repl(m):
        ids = re.findall(r"C\d+", m.group(0))
        cites = list(dict.fromkeys(by_id[i] for i in ids if i in by_id))
        return f" ({'; '.join(cites)})" if cites else ""
    text = re.sub(r"(?:\s*\[[^\]]*C\d+[^\]]*\])+", repl, text)
    text = re.sub(r"(\([^()]*\))(?:\s*\1)+", r"\1", text)          # "(12 CFR 211.23) (12 CFR 211.23)" -> once
    return re.sub(r"\s+([.,;])", r"\1", text)


# --------------------------------------------------------------------------------------
# 9. READING THE FILING (#1). The AI reads the bank's FR Y-9C laid out line by line and finds each figure by
#    its MEANING. engine.check_ai_read then checks every figure against the exact value filed under its code.
# --------------------------------------------------------------------------------------
def read_filing(step, bank_name, filing_text):
    from engine import READ_TARGETS
    want = "\n".join(f"- {k}: {label}" for k, (label, _codes) in READ_TARGETS.items())
    user = (
        "You are reading a U.S. bank holding company's FR Y-9C regulatory filing, laid out line by line below. Find each "
        "figure listed under WANTED by its meaning. Copy each value EXACTLY as filed (thousands of dollars; percentages as "
        "shown) - never calculate, round or convert. For each figure give the schedule and item where you found it "
        "(e.g. 'HC item 12'). If a figure is not in the filing, use null. For deposit_lines give a LIST of every deposit "
        "line's value - do not add them up.\n"
        "Return JSON only: {\"figures\": {\"total_assets\": {\"value\": 123, \"line\": \"HC item 12\"}, ...}}\n\n"
        f"WANTED:\n{want}\n\n{filing_text}")
    raw = json_call("Return only valid JSON.", user, step, f"Read the filing: {bank_name}", max_tokens=2500, need="figures")
    figs = raw.get("figures") if isinstance(raw.get("figures"), dict) else raw
    return figs if isinstance(figs, dict) else {}


def reread_filing(step, bank_name, filing_text, misses):
    """Self-correction loop: the app tells the AI which of its figures did not match the filing (without giving the answer);
    the AI reads those lines again."""
    from engine import READ_TARGETS
    ask = "\n".join(f"- {k}: {READ_TARGETS[k][0]} (you gave {v!r}; that does not match the filing)" for k, v in misses.items())
    user = (
        "Some figures you read from this FR Y-9C filing did not match when the app checked them. Read the filing again, "
        "carefully, and find ONLY these figures. Copy each value exactly as filed - never calculate. Give the schedule and "
        "item. For deposit_lines give a LIST of every deposit line's value.\n"
        "Return JSON only: {\"figures\": {\"key\": {\"value\": 123, \"line\": \"HC item 12\"}}}\n\n"
        f"FIGURES TO RE-READ:\n{ask}\n\n{filing_text}")
    raw = json_call("Return only valid JSON.", user, step, f"Re-read the filing: {bank_name}", max_tokens=1200, need="figures")
    figs = raw.get("figures") if isinstance(raw.get("figures"), dict) else {}
    return {k: v for k, v in figs.items() if k in misses}


def review_bank(step, bank_name, figures_text, checks_text):
    user = (
        "Below are figures from a bank holding company's FR Y-9C filing, read exactly by the app, with some proportions the app "
        "worked out, and the app's checks of the AI's reading of the filing. As an experienced bank analyst, in short bullet "
        "points: (1) the bank's size, funding and capital position in plain English; (2) anything a deal lawyer should "
        "look at more closely - for example a large unrealised securities loss (AOCI) relative to CET1, which matters if the "
        "bank loses its AOCI opt-out; heavy goodwill; thin capital above the buffer; a reliance on wholesale funding; (3) any "
        "balance-sheet lines that may be holdings a bank holding company cannot keep indefinitely - real estate ventures, "
        "investments in unconsolidated companies, equity securities, other real estate owned - with their exact amounts, if "
        "material; (4) any figure the checks could not confirm. At most 6 bullets. Use only the numbers given, exactly as "
        "written. Do not cite law. No preamble.\n\n"
        f"BANK: {bank_name}\nFIGURES:\n{figures_text}\n\nCHECKS:\n{checks_text}")
    return chat("You are a careful bank-regulatory analyst.", user, step, f"Analyst review: {bank_name}", max_tokens=700)


# --------------------------------------------------------------------------------------
# 10. APPLYING THE RULES FROM THE REGULATION TEXT (#2). Two calls: the category (and other triggers the app's
#     size-only rulebook does not test), then what applies in that category. Code compares with the rulebook.
# --------------------------------------------------------------------------------------
RULE_QUERIES_CATEGORY = [("section", "12 CFR 252.5", None, 3), ("section", "12 CFR 252.2", "Category IV", 1),
                         ("section", "12 CFR 217.2", "Category III Board-regulated institution means", 1),
                         ("section", "12 CFR 217.2", "Advanced approaches Board-regulated institution means", 1),
                         ("section", "12 CFR 217.100", "Category II banking organization", 1)]
RULE_QUERIES_REQUIREMENTS = [("section", "12 CFR 217.10", "supplementary leverage ratio of 3 percent", 1),
                             ("section", "12 CFR 217.11", "countercyclical capital buffer amount", 2),
                             ("section", "12 CFR 217.22", "AOCI opt-out election", 2),
                             ("section", "12 CFR 225.8", "$100 billion asset threshold", 1),
                             ("section", "12 CFR 225.8", "Category IV", 2),
                             ("section", "12 CFR 252.44", None, 2),
                             ("section", "12 CFR 249.1", None, 1), ("section", "12 CFR 249.30", None, 2)]


def fetch_sections(queries, lib):
    seen, out = set(), []
    for q in queries:
        for p in lib.section(q[1], q[2], limit=q[3] if len(q) > 3 else 1):
            if p["id"] not in seen:
                seen.add(p["id"])
                out.append(p)
    return out


RULE_VOTES = 3   # independent readings; the app takes the majority on each point ("self-consistency")


def _vote(values):
    """Majority value and how many readings gave it."""
    vals = [v for v in values if v not in (None, "")]
    if not vals:
        return None, 0
    best = max(set(vals), key=vals.count)
    return best, vals.count(best)


def _norm_cat(c):
    c = str(c or "").replace("Category", "").replace("category", "").strip().upper()
    return "None" if c in ("NONE", "NO CATEGORY", "N/A", "") or "BELOW" in c else c


def read_rules(step, facts, requirement_names, lib, votes=RULE_VOTES, questions=None):
    """The AI applies the regulation text itself, in two rounds, each run as `votes` independent readings at once.
    Returns {"category", "advanced_approaches", "other_triggers", "requirements", "passages", "votes": {...}}."""
    p_cat = fetch_sections(RULE_QUERIES_CATEGORY, lib)
    u1 = (
        "Apply the regulation PASSAGES to the bank in APP FACTS. Work out which size category (I, II, III, IV, or None if "
        "below $100 billion) the bank is in BEFORE the deal and AFTER it, using the asset size given. Work it out in "
        "'reasoning' FIRST, testing each category from the top (I, then II, III, IV) against the asset figure for each date, "
        "and only then fill in 'before' and 'after' so they match your reasoning. Next, in 'advanced_approaches', decide for "
        "each date whether the bank is an 'advanced approaches Board-regulated institution', testing the definition in 12 CFR "
        "217.2 and the list in 12 CFR 217.100(b)(1)(i) clause by clause against APP FACTS and your category answer. Then list the OTHER "
        "ways the passages say a bank of this size can be placed in a HIGHER category (e.g. cross-jurisdictional activity, "
        "nonbank assets, weighted short-term wholesale funding, off-balance-sheet exposure) - the app does not have those "
        "figures, so state the threshold and what the lawyer must check. Cite passages like [C12].\n"
        "Return JSON only: {\"category\": {\"reasoning\": \"step by step, with citations\", \"before\": \"II|III|IV|None\", "
        "\"after\": \"II|III|IV|None\", \"why\": \"two sentences for the lawyer, with citations\"}, "
        "\"advanced_approaches\": {\"reasoning\": \"clause by clause, with citations\", \"before\": true, \"after\": true}, "
        "\"other_triggers\": [{\"trigger\": \"...\", \"threshold\": \"...\", \"effect\": \"which category it would mean\", "
        "\"check\": \"what to ask the client\", \"cite\": \"[C#]\"}]}\n\n"
        f"APP FACTS:\n{facts}\n\nPASSAGES:\n{_passages_block(p_cat)}")
    runs1 = parallel([lambda i=i: json_call(CLOSED_WORLD_RULES + "\nReturn only valid JSON.", u1, step,
                                            f"Rule reading: size category (reading {i + 1} of {votes})", p_cat,
                                            max_tokens=2600, need="category") for i in range(votes)])
    cats = [r.get("category") if isinstance(r.get("category"), dict) else {} for r in runs1]
    before, nb = _vote([_norm_cat(c.get("before")) for c in cats])
    after, na = _vote([_norm_cat(c.get("after")) for c in cats])
    pick = next((i for i, c in enumerate(cats) if _norm_cat(c.get("before")) == before and _norm_cat(c.get("after")) == after), 0)
    c = dict(cats[pick], before=before, after=after)
    trig = [t for t in runs1[pick].get("other_triggers", []) if isinstance(t, dict)][:6]
    aas = [r.get("advanced_approaches") if isinstance(r.get("advanced_approaches"), dict) else {} for r in runs1]
    aa_b, _ = _vote([str(x.get("before")).lower() for x in aas if x.get("before") is not None])
    aa_a, n_aa = _vote([str(x.get("after")).lower() for x in aas if x.get("after") is not None])
    aa = next((x for x in aas if str(x.get("after")).lower() == aa_a), {})
    yesno = lambda v: "IS" if v == "true" else ("is NOT" if v == "false" else "may or may not be")

    p_req = fetch_sections(RULE_QUERIES_REQUIREMENTS, lib)
    questions = questions or requirement_names
    names = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
    yn = lambda v: "YES" if v == "true" else ("NO" if v == "false" else "UNCLEAR")
    u2 = (
        "SETTLED FACTS (from the first round of readings):\n"
        f"- BEFORE the deal: Category {before}; advanced approaches Board-regulated institution: {yn(aa_b)}.\n"
        f"- AFTER the deal: Category {after}; advanced approaches Board-regulated institution: {yn(aa_a)}.\n"
        "A rule that covers 'X or Y' covers the bank on any date where EITHER X or Y is true for it.\n"
        "Answer each numbered QUESTION for the bank, before and after the deal, using ONLY the PASSAGES and those "
        "settled facts. Work like a lawyer, in this order for each question: (1) 'covers' - quote the words in the passage "
        "that say WHO the rule applies to; (2) 'test' - for each date, restate the bank's category and advanced-approaches status from SETTLED FACTS and "
        "check them against those words; "
        "(3) only then the answers. Use exactly one of: \"applies\", \"does not apply\", \"conditional\" (only if another "
        "test is met), \"optional\" (the bank may elect) - never any other words in those fields.\n"
        "Return JSON only: {\"requirements\": [{\"n\": 1, \"covers\": \"quote [C#]\", \"test\": \"...\", "
        "\"before\": \"...\", \"after\": \"...\", \"why\": \"one sentence for the lawyer, with a citation like [C12]\"}]} "
        "(one entry per numbered question)\n\n"
        f"QUESTIONS:\n{names}\n\nAPP FACTS:\n{facts}\n\nPASSAGES:\n{_passages_block(p_req)}")
    runs2 = parallel([lambda i=i: json_call(CLOSED_WORLD_RULES + "\nReturn only valid JSON.", u2, step,
                                            f"Rule reading: what applies (reading {i + 1} of {votes})", p_req,
                                            max_tokens=3500, need="requirements") for i in range(votes)])
    by_run = []
    for r in runs2:
        m = {}
        for x in r.get("requirements", []) if isinstance(r.get("requirements"), list) else []:
            try:
                m[int(x.get("n"))] = x
            except (TypeError, ValueError):
                pass
        by_run.append(m)
    reqs, agree_counts = [], {}
    for n, name in enumerate(requirement_names, 1):
        answers = [str(m.get(n, {}).get("after", "")).strip().lower() for m in by_run]
        best, k = _vote(answers)
        src = next((m[n] for m in by_run if n in m and str(m[n].get("after", "")).strip().lower() == best), {})
        b_best, _ = _vote([str(m.get(n, {}).get("before", "")).strip().lower() for m in by_run])
        reqs.append({"n": n, "name": name, "after": best or "", "before": b_best or "", "why": src.get("why", ""),
                     "votes": f"{k} of {len(by_run)}"})
        agree_counts[name] = k
    passages = p_cat + p_req
    out = {"category": c, "advanced_approaches": aa, "other_triggers": trig, "requirements": reqs, "passages": passages,
           "votes": {"n": votes, "before": nb, "after": na, "requirements": agree_counts,
                     "unanimous": sum(1 for v in [nb, na] if v == votes) + sum(1 for v in agree_counts.values() if v == len(by_run)),
                     "points": 2 + len(requirement_names)}}
    out["citations"] = check_citations(json.dumps(out["category"]) + json.dumps(trig) + json.dumps(reqs), passages)
    return out


# --------------------------------------------------------------------------------------
# 11. THE HOLDINGS REGISTER AND THE DISPOSAL REVIEW (#3). The AI reads any register (spreadsheet, PDF, Word, text)
#     into rows, then gives each holding a reasoned verdict under Reg K and Regulation Y. Code checks each verdict.
# --------------------------------------------------------------------------------------
def extract_register(step, text, parent_name):
    user = (
        f"Below is a holdings register for {parent_name} (a spreadsheet, list or annual-report extract). For EACH company: "
        "name; country (where incorporated or mainly operating); business (a short plain description, as given); activity, "
        f"chosen ONLY from {ACTIVITIES}; ownership_pct (the parent's voting stake as a number, null if not given); "
        "us_activity (what it does in the United States, as given, or \"\"); us_business = true if it does any business in the "
        "United States or a U.S. territory. Copy facts as given - do not invent. Return JSON only: "
        '{"holdings": [{"name": "...", "country": "...", "business": "...", "activity": "...", "ownership_pct": 100, '
        '"us_activity": "", "us_business": false}]}'
        f"\n\nREGISTER:\n{text[:40000]}")
    raw = json_call("Return only valid JSON.", user, step, "Read the holdings register", max_tokens=5000, need="holdings")
    out = []
    for h in raw.get("holdings", []) if isinstance(raw.get("holdings"), list) else []:
        if isinstance(h, dict) and h.get("name"):
            pct = h.get("ownership_pct")
            try:
                pct = float(str(pct).replace("%", "")) if pct not in (None, "", "null") else None
            except ValueError:
                pct = None
            out.append({"name": str(h["name"]).strip(), "country": str(h.get("country") or "Unknown"),
                        "business": str(h.get("business") or ""), "ownership_pct": pct,
                        "activity": h.get("activity") if h.get("activity") in ACTIVITIES else "Not classified",
                        "us_activity": str(h.get("us_activity") or ""), "us_business": bool(h.get("us_business"))})
    return out


DISPOSAL_QUERIES = [("section", "12 CFR 211.23", None, 5), ("section", "12 CFR 225.86", None, 4),
                    ("section", "12 CFR 225.28", "closely related to banking", 2)]


def disposal_passages(holdings, lib):
    passages = fetch_sections(DISPOSAL_QUERIES, lib)
    words = " ".join(sorted({h.get("business", "") + " " + h.get("activity", "") for h in holdings}))[:400]
    for p in lib.search("closely related to banking permissible activities " + words, k=4):
        if p["id"] not in {x["id"] for x in passages} and p["cite"].startswith(("12 CFR 225.28", "12 CFR 225.86", "12 CFR 211")):
            passages.append(p)
    return passages


def analyse_holdings(step, holdings, context, passages, batch=8):
    """One AI call per batch of holdings, run at the same time. Returns {name: verdict dict}."""
    from engine import VERDICTS

    def one(chunk):
        listing = "\n".join(f"{i + 1}. {h['name']} | {h.get('country')} | {h.get('business') or h.get('activity')} | owned "
                            f"{'?' if h.get('ownership_pct') is None else str(round(h['ownership_pct'])) + '%'} | U.S. activity: "
                            f"{h.get('us_activity') or ('yes' if h.get('us_business') else 'none')}" for i, h in enumerate(chunk))
        user = (
            "You are a U.S. bank regulatory lawyer. A Canadian bank is buying a U.S. bank. For EACH holding below, decide what "
            "U.S. law requires of the Canadian parent, using ONLY the PASSAGES: Regulation K's exemptions for qualifying foreign "
            "banking organizations (12 CFR 211.23: the qualifying tests, what a qualifying bank may own outside the U.S., the "
            "limits on foreign companies that also do business in the U.S., loss of eligibility) and Regulation Y's lists of "
            "activities a U.S. bank holding company may do (closely related to banking; financial in nature). Treat U.S. "
            "territories as the United States: a company there is a U.S. company, judged by what a U.S. bank holding company may own. Use the app's Reg K result in CONTEXT as given - do not redo it.\n"
            "verdict must be one of these keys, used strictly as defined:\n"
            "- \"keep\": the passages allow it whatever happens to the parent's Reg K status (e.g. banking outside the U.S., or an "
            "activity a U.S. bank holding company may itself do). A permission given to a 'qualifying foreign banking "
            "organization' (e.g. 'may engage in activities of any kind outside the United States') DEPENDS on Reg K status, so a "
            "holding allowed only by such a permission is \"at_risk\", never \"keep\".\n"
            "- \"keep_conditions\": allowed only if a condition holds - name it (e.g. more than half of the company's assets and "
            "revenue outside the U.S.).\n"
            "- \"at_risk\": allowed only while the parent keeps Reg K status.\n"
            "- \"approval\": allowed only with the Fed's approval or after notice to the Fed.\n"
            "- \"sell\": ONLY if no provision in the PASSAGES lets the parent keep it even while it keeps Reg K status. Before "
            "choosing \"sell\", test the routes the passages give - the Reg K exemptions and their conditions, the timing rule on "
            "loss of eligibility (which catches activities started after the first failing year), a specific determination of "
            "eligibility, an exemption the Board may grant case by case, holdings in a fiduciary capacity - and say in the reason "
            "why each relevant route fails. If any route might work, use \"at_risk\", \"keep_conditions\" or \"approval\" instead.\n"
            "Return JSON only: {\"verdicts\": [{\"n\": 1, \"verdict\": \"...\", \"reason\": \"one or two sentences with a "
            "citation like [C12]\", \"action\": \"the next step for the lawyer, one sentence\"}]}\n\n"
            f"CONTEXT:\n{context}\n\nHOLDINGS:\n{listing}\n\nPASSAGES:\n{_passages_block(passages)}")
        raw = json_call(CLOSED_WORLD_RULES + "\nReturn only valid JSON.", user, step,
                        f"Disposal review ({len(chunk)} holdings)", passages, max_tokens=3000, need="verdicts")
        out = {}
        for v in raw.get("verdicts", []) if isinstance(raw.get("verdicts"), list) else []:
            try:
                h = chunk[int(v.get("n")) - 1]
            except (TypeError, ValueError, IndexError):
                continue
            text = f"{v.get('reason', '')}"
            chk = check_citations(text, passages)
            if chk["invalid"]:
                text = _strip_invalid(text, chk["invalid"])
            out[h["name"]] = {"verdict": v.get("verdict") if v.get("verdict") in VERDICTS else None,
                              "reason": text, "action": str(v.get("action") or ""), "cited": chk["cited"]}
        return out

    chunks = [holdings[i:i + batch] for i in range(0, len(holdings), batch)]
    merged = {}
    for part in parallel([lambda c=c: one(c) for c in chunks]):
        merged.update(part)
    return merged


# --------------------------------------------------------------------------------------
# 12. THE AI ANALYST (#5). The AI decides what to investigate and calls the app's calculator; it never does the
#     arithmetic itself. Code runs each tool, feeds the result back, and checks every number in the write-up.
# --------------------------------------------------------------------------------------
ANALYST_MAX_STEPS = 6


def analyst_next(step, facts, tools_doc, history, focus, n):
    hist = "\n\n".join(f"Call {i + 1}: {h['tool']} {json.dumps(h['args'])} - because: {h['why']}\nRESULT: {json.dumps(h['result'])}"
                       for i, h in enumerate(history)) or "(none yet)"
    may_finish = n >= 3
    user = (
        "You are a senior bank-regulatory analyst investigating a proposed merger for a deal partner. You cannot calculate: "
        "you call the app's calculator TOOLS and read their results. Decide the single most useful NEXT call. Good analysts "
        "check how close the deal is to each line, what could tip it over (growth, losses, more debt), when it bites (the "
        "four-quarter average), and capital resilience - and for a Canadian buyer, Reg K. Do not repeat a call with the same "
        "arguments. Use scenario arguments that answer a real question (e.g. a 2% CET1 loss: capital_loss_bn sized from the "
        "facts; or the target growing 10%)."
        + (" You may finish now if you have enough." if may_finish else f" You must make at least {3 - n} more call(s).") +
        "\nReturn JSON only: {\"why\": \"one sentence: the question this call answers\", \"tool\": \"tool name\", \"args\": {}}"
        + (" or {\"done\": true}" if may_finish else "") +
        f"\n\nTOOLS:\n{tools_doc}\n\nDEAL FACTS:\n{facts}\n\nPARTNER'S FOCUS: {focus or 'a general investigation'}\n\nCALLS SO FAR:\n{hist}")
    return json_call("Return only valid JSON.", user, step, f"Analyst: choose call {n + 1}", max_tokens=500)


def analyst_report(step, facts, history, focus):
    hist = "\n\n".join(f"Call {i + 1}: {h['tool']} {json.dumps(h['args'])} - {h['why']}\nRESULT: {json.dumps(h['result'])}"
                       for i, h in enumerate(history))
    user = (
        "Write the findings of your investigation for the deal partner, using ONLY the numbers in the RESULTS and DEAL FACTS, "
        "copied exactly as written (never compute a new number). Format in markdown:\n"
        "**Key findings** - 4 to 6 bullets, most important first; each one sentence with the figure that proves it.\n"
        "**What could change the picture** - 2 or 3 bullets.\n**Questions for the client** - 2 or 3 bullets.\n"
        "Do not put quotation marks around figures. Where a RESULT has a 'summary' line, rely on it. "
        "No legal citations, no preamble, under 300 words.\n\n"
        f"PARTNER'S FOCUS: {focus or 'a general investigation'}\n\nDEAL FACTS:\n{facts}\n\nRESULTS:\n{hist}")
    return chat("You are a senior bank-regulatory analyst.", user, step, "Analyst: findings", max_tokens=900)


# --------------------------------------------------------------------------------------
# 13. THE ISSUES LIST (#4) AND THE PARTNER MEMO
# --------------------------------------------------------------------------------------
def issues_list(step, rows_text, extra_text, passages):
    user = (
        "You are the senior associate on a bank merger. Below are the app's numbered results [R#] and other workflow "
        "findings. Write the ISSUES LIST the partner needs: group related results into issues, rank them by how much they "
        "matter to the deal (legal consequence, cost, timing), say which issues interact (e.g. a category crossing that also "
        "breaks Reg K), and give one specific action each. Every result with a status other than Met or Already applies must "
        "be covered by an issue (list its [R#] numbers in covers). Use statuses exactly as given. Cite PASSAGES like [C12] for "
        "legal points. " + MEMO_STYLE + "\n"
        "Return JSON only: {\"issues\": [{\"title\": \"6-10 words\", \"severity\": \"high|medium|low\", \"why\": \"two sentences "
        "with citations\", \"action\": \"one specific next step\", \"interacts_with\": [\"title of another issue\"], "
        "\"covers\": [1, 2]}]}  (3 to 8 issues)\n\n"
        f"RESULTS:\n{rows_text}\n\nOTHER FINDINGS:\n{extra_text}\n\nPASSAGES:\n{_passages_block(passages)}")
    raw = json_call(CLOSED_WORLD_RULES + "\nReturn only valid JSON.", user, step, "Issues list", passages,
                    max_tokens=3500, need="issues")
    out = []
    for it in raw.get("issues", []) if isinstance(raw.get("issues"), list) else []:
        if not isinstance(it, dict) or not it.get("title"):
            continue
        why = str(it.get("why", ""))
        chk = check_citations(why, passages)
        if chk["invalid"]:
            why = _strip_invalid(why, chk["invalid"])
        covers = []
        for c in it.get("covers", []) or []:
            try:
                covers.append(int(str(c).strip("R[] ")))
            except ValueError:
                pass
        out.append({"title": str(it["title"]), "severity": str(it.get("severity", "medium")).lower(), "why": why,
                    "action": str(it.get("action", "")), "interacts_with": [str(x) for x in it.get("interacts_with", []) or []],
                    "covers": covers})
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda x: order.get(x["severity"], 1))


def check_memo(step, memo_text, facts, passages):
    """Second AI call on the memo: legal statements must follow from their cited passage; facts and figures must come
    from the WORKFLOW FINDINGS (the app's results). Returns {"supported", "unsupported": [...]} ."""
    user = (
        "You are a careful senior reviewer. Check the MEMO sentence by sentence and flag only real problems:\n"
        "- 'error': a statement about what the LAW requires that its cited passage does not support or contradicts, a "
        "statement cited to the wrong passage, or a fact about this deal that the WORKFLOW FINDINGS do not support or "
        "contradict, or a conclusion the findings do not support (e.g. predicting whether the deal will be approved).\n"
        "- 'minor': anything else worth tidying (citation placement, wording).\n"
        "Do NOT flag a sentence that is supported. Do not flag recommendations or next steps.\n"
        "Return JSON only: {\"flags\": [{\"sentence\": \"...\", \"severity\": \"error|minor\", \"problem\": \"...\"}]} "
        "(an empty list if nothing is wrong)\n\n"
        f"MEMO:\n{memo_text}\n\nWORKFLOW FINDINGS:\n{facts}\n\nPASSAGES:\n{_passages_block(passages)}")
    v = json_call("Return only valid JSON.", user, step, "Memo check (second AI)", passages, max_tokens=1500)
    flags = [u for u in v.get("flags", []) if isinstance(u, dict) and u.get("sentence")]
    errors = [u for u in flags if str(u.get("severity", "")).lower() == "error"]
    return {"supported": not errors, "unsupported": errors, "minor": [u for u in flags if u not in errors]}


MEMO_WORD_LIMIT = 430
MEMO_STYLE = ("Write as a lawyer to a lawyer: state facts directly and confidently. Never mention 'passages', 'the loaded "
              "regulations', 'the findings', 'the app' or what the regulations 'do not cover' - if a point is not supported, "
              "leave it out. Where a result rests on an estimate, say so in one short clause. Do not predict whether the deal "
              "will or will not be approved. Put a citation only after a statement about what the law requires - not after "
              "facts about this deal.")


def partner_memo(step, facts, issues_text, passages, shorten_from=None, words=None, fix=None):
    """Returns the memo as parts (subject, bottom line, findings, recommendations, caveat); code assembles the email.
    shorten_from: tighten an over-long draft. fix: revise a draft whose statements the checker could not confirm."""
    if fix:
        problems = "\n".join(f"- \"{u['sentence']}\" - {u.get('problem', '')}" for u in fix["unsupported"])
        task = ("A reviewer could not confirm these statements in your memo:\n" + problems + "\nRevise the memo: correct each "
                "statement so it says only what its cited passage or the WORKFLOW FINDINGS support, or remove it. Keep "
                f"everything else, every figure exactly as written, and the same JSON shape. At most {MEMO_WORD_LIMIT - 60} "
                "words. " + MEMO_STYLE + "\n\nMEMO:\n" + fix["memo"])
    elif shorten_from:
        task = (f"This memo is {words or 'too many'} words - too long for one page. Rewrite it in at most {MEMO_WORD_LIMIT - 80} "
                "words: keep the bottom line, at most 4 findings of 2 sentences each and at most 4 one-sentence recommendations; "
                "keep every figure exactly as written and keep the citations; cut repetition first. Same JSON shape. "
                + MEMO_STYLE + "\n\nMEMO:\n" + shorten_from)
    else:
        task = (
            "Write a one-page internal memo, ready to email to the supervising partner at a law firm, on the regulatory "
            "screening of this bank merger. Lead with the answer. Plain, precise legal English; no hedging boilerplate. "
            "Use ONLY the facts and figures given, copied exactly (never compute a new number). Cite PASSAGES like [C12] for "
            f"each legal point. Whole memo under {MEMO_WORD_LIMIT - 60} words. " + MEMO_STYLE + "\n"
            "Return JSON only: {\"subject\": \"under 12 words\", \"bottom_line\": \"2-3 sentences: the answer\", "
            "\"findings\": [{\"heading\": \"3-6 words\", \"text\": \"2 sentences with figures and citations\"}] (3 or 4), "
            "\"recommendations\": [\"one sentence each\"] (3 or 4), \"caveat\": \"one sentence on what was not checked\"}")
    user = f"{task}\n\nWORKFLOW FINDINGS:\n{facts}\n\nISSUES LIST:\n{issues_text}\n\nPASSAGES:\n{_passages_block(passages)}"
    raw = json_call(CLOSED_WORLD_RULES + "\nReturn only valid JSON.", user, step,
                    "Partner memo - revised after check" if fix else ("Partner memo - shortened" if shorten_from else "Partner memo - draft"),
                    passages, max_tokens=3000, need="bottom_line")
    memo = {"subject": str(raw.get("subject", "Regulatory screen of the proposed merger")),
            "bottom_line": str(raw.get("bottom_line", "")),
            "findings": [f for f in raw.get("findings", []) if isinstance(f, dict) and f.get("text")][:5],
            "recommendations": [str(r) for r in raw.get("recommendations", []) if r][:5],
            "caveat": str(raw.get("caveat", ""))}
    blob = json.dumps(memo)
    chk = check_citations(blob, passages)
    if chk["invalid"]:
        memo = json.loads(_strip_invalid(blob, chk["invalid"]))
    memo["citations"] = chk
    return memo


# --------------------------------------------------------------------------------------
# Offline test mode (developer only: set APP_DEV_MOCK=1). Lets the plumbing be tested without a key.
# --------------------------------------------------------------------------------------
def _mock(user, passages, want_json):
    if want_json and "strict checker" in user:
        return json.dumps({"supported": True, "unsupported": [], "better_search": ""})
    if want_json and "FR Y-9C regulatory filing" in user:
        return json.dumps({"figures": {}})
    if want_json and "Work out which size category" in user:
        return json.dumps({"category": {"before": "IV", "after": "III", "why": "Mock."}, "other_triggers": []})
    if want_json and "decide for each REQUIREMENT" in user:
        return json.dumps({"requirements": []})
    if want_json and "holdings register" in user:
        return json.dumps({"holdings": [{"name": "Mock Insurance Co.", "country": "Canada", "business": "Insurance", "activity": "Insurance",
                                         "ownership_pct": 100, "us_activity": "", "us_business": False}]})
    if want_json and "For EACH holding below" in user:
        return json.dumps({"verdicts": [{"n": 1, "verdict": "at_risk", "reason": "Mock.", "action": "Mock."}]})
    if want_json and "single most useful NEXT call" in user:
        return json.dumps({"why": "Mock.", "tool": "headroom", "args": {}} if "(none yet)" in user else {"done": True})
    if want_json and "ISSUES LIST the partner needs" in user:
        return json.dumps({"issues": []})
    if want_json and "one-page internal memo" in user:
        return json.dumps({"subject": "Mock memo", "bottom_line": "Mock.", "findings": [{"heading": "Mock", "text": "Mock."}],
                           "recommendations": ["Mock."], "caveat": "Mock."})
    if want_json and "restructure a merger" in user:
        return json.dumps({"options": [{"title": "Sell the card book", "moves": [{"lever": "sell_business", "business": "Credit-card portfolio"}],
                                        "why": "Mock.", "downside": "Mock."}]})
    if want_json:
        return json.dumps({"bank_name": {"value": "Mock Bank"}, "period": {"value": "mock"}})
    cite = f" [{passages[0]['id']}]" if passages else ""
    return f"(Offline test mode - no AI was called.) This is placeholder text standing in for the AI's explanation{cite}."
