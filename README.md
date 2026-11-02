# Bank Merger Regulatory Check

An AI-powered Streamlit app for a banking M&A lawyer. Choose a U.S. bank to be bought and its buyer, which is either another U.S. bank or one of the four Canadian banks that buy U.S. banks (TD, RBC, BMO, CIBC).

The AI does the analyst's and the associate's work:
- it reads both banks' Fed filings;
- it applies the regulations itself;
- it reviews the buyer's holdings for anything that may have to be sold;
- it investigates the deal with the app's calculator;
- it ranks the issues;
- it drafts a one-page memo ready to email to the partner.

The app checks everything the AI reads or writes: every figure against the filing, every rule against a built-in rulebook, every citation against the library, and every number in the memo against the app's own results.

**Deployed app:** _add the Streamlit Cloud URL here_

## Workflow
| Page | What the AI does | What the app checks |
|---|---|---|
| Home | — | Explains the design ("so you only have to double-check the work, not triple-check it") |
| 1 Getting started | Choose the two banks: upload FR Y-9Cs (PDF or the Fed's bulk .txt), pick example banks, or load an example deal. For a Canadian buyer, pick TD/RBC/BMO/CIBC and its Pillar 3 report. **AI reads each filing line by line** (balance sheet and capital schedule) and finds 21 figures by their meaning; then writes an analyst's review (AOCI against CET1, goodwill, funding, and balance-sheet holdings a holding company may have to sell) | Every figure the AI read against the exact value filed under its Fed code, and the AI's figures must reproduce the reported ratios. **Self-correction loop:** the AI re-reads any figure that does not match |
| 2 At a glance | **AI applies the rules from the regulation text**, in two rounds: first the size category and whether the bank uses the "advanced approaches" (12 CFR 252.5, 217.2, 217.100); then the seven requirements, with a quote of who each rule covers and a test of the bank against it. **Three independent readings run at once**, and the majority answer is taken on each point. It also lists the other triggers (cross-jurisdictional activity, wholesale funding…) the app cannot test | Each point against the built-in rulebook: "agree on 9 of 9 points" |
| 3 Capital ratios | Optional plain-English guide | Minimums, buffers, each category's requirements |
| 4 Leverage & liabilities | Optional plain-English guide | 4% leverage, 3% SLR, 10% liabilities limit (with deal debt) |
| 5 Canadian buyer | *Only for a Canadian buyer.* **Holdings — what it may have to sell:** upload the parent's holdings register (CSV, Excel, PDF, Word or text) and the **AI gives each holding a reasoned verdict under Reg K and Regulation Y** (can keep / keep with conditions / at risk if Reg K status is lost / likely must sell / needs Fed approval). "Must sell" is used only where nothing in the text lets it be kept; the Fed's records for the parent are always included | U.S. footprint, IHC and Subpart O, the Reg K tests, OSFI ratios. A **"two ways out"** line from the app's own numbers: keep Reg K status by shedding $X of U.S. banking assets, or let it go and sell the holdings that depend on it. The **bank being bought's own** real-estate ventures, minority investments, equity securities and foreclosed property, exact from its FR Y-9C. Every verdict checked against the app's Reg K result; disposal timing from the closing date (12 CFR 211.23(d)); downloadable disposal schedule |
| 6 AI analyst | **The AI investigates the deal**: it decides what to test, calls the app's calculator (how close to every line, what would flip each result, what-if scenarios, quarter-by-quarter timeline), reads the result and decides the next call (up to 6), then writes findings and questions for the client | Every calculation; every $ figure and % in the write-up must trace to a calculator result |
| 7 Deal options | **AI proposes, code proves.** Pick a preset deal background; AI chooses three restructuring strategies, revises any that fall short, and explains which fits | Which lines the deal crosses and whether each can be avoided; sizes and tests every strategy |
| 8 Summary & next steps | **AI writes the ranked issues list**, then **drafts the one-page partner memo** from everything above. A **second AI call** checks the memo; any error it finds goes back for revision (up to two rounds) | Every flagged result must be covered by an issue (the app adds any the AI missed); citations turned into real ones ("12 CFR 211.23"); one page (≤430 words, tightened by the AI if longer); every figure matches the app's results. **Downloads:** memo as Word (one page), as an email draft (.eml, opens in Outlook), or copy the text; full report; AI audit trail |
| Size examples | — | Fictitious deals landing in each category |

## Design: AI analyses, code checks
| File | Role | Class technique |
|---|---|---|
| `engine.py` | Every number and every result, as if-then rules citing the regulation. Also: the filing layout the AI reads, the checks of the AI's reading, the analyst's calculator tools, disposal timing, and the number checker | Lab 1: if-then logic |
| `library.py` | Closed-world library: 14 regulation documents (incl. Reg K and Reg Y) in ~1,160 section-level chunks; keyword search (BM25 + phrase bonus) | Lab 2: retrieval (RAG) |
| `ai.py` | Every AI call, each **only** from what it is given (filing lines, passages, app results). Techniques: chain of thought in JSON (reasoning before the answer), self-consistency (3 readings, majority vote), tool use (the analyst calls the calculator), self-correction (re-reading the filing), reflection (Q&A and memo checks), and revision loops (memo, deal options). Code verifies every `[C#]` citation | Lab 2: RAG + looping + reflection |
| `build_y9c_template.py` | Run once: the FR Y-9C lines (Schedule HC, HC-M goodwill, HC-R Part I) with captions and Fed codes → `library/y9c_template.json` | Data preparation |
| `build_structure.py` | Run once: the Fed's NIC ownership files → `library/us_structure.json` | Data preparation |

The AI never browses the web, never does the arithmetic and never has the last word on a result: the app checks it. A full run makes **about 30 AI calls**:

| Step | AI calls |
|---|---|
| Getting started | 4–6 (read and review each filing, plus re-reads) |
| At a glance | 7 (headline, plus 3 + 3 rule readings) |
| Each page's "what this means" | 1 per page |
| AI analyst | 4–7 |
| Deal options | 2–3 |
| Summary | about 6 (issues list, memo draft, tightening, check, revisions) |
| Canadian buyer | 3–6 more (Pillar 3, reading the holdings register, disposal batches) |
| Each question asked | 2–4 |

## Data sources
- **FR Y-9C** (Fed National Information Center), PDF reports or the bulk .txt download. The app keeps each line's exact value under its Fed (MDRM) code; the AI reads the same lines with their captions.
- **Pillar 3** of the Canadian parent. Code finds the key-metrics pages, the AI reads them, and code checks the figures against the bank's reported ratios.
- **NIC ownership data** (`library/us_structure.json`): each Canadian bank's U.S. holding company, its U.S. companies inside and outside it, its U.S. branches, and the foreign companies it reports to the Fed.
- **Regulations** (`library/chunks.json`):
  - 12 CFR Parts 211 (Reg K), 217, 225 (Reg Y), 249, 251 and 252
  - 12 U.S.C. 1828, 1842, 1852
  - OSFI CAR (2027) and the Leverage Requirements Guideline
  - the Bank Act (Parts IX–X)
  - the Fed's March 2026 capital proposals

## Test cases
_Files are in `test_data/`. The example banks (`EXAMPLE_BANKS_2026Q2.txt`, built by `make_example_banks.py`) and `ILLUSTRATIVE_holdings_register.csv` are **fictional**. The banks are sized just below the category lines, with complete, internally consistent filings._

1. **U.S. deals that cross every line (works well).** Getting started → **Or load a ready-made example deal**:
   - Great Lakes ($88bn) + Prairie Trust ($62bn) = $150bn → **below $100bn to Category IV**;
   - Sun Belt ($228bn) + Atlantic Harbor ($41bn) = $269bn → **IV to III**;
   - Pacific Crest ($655bn) + Cascade ($95bn) = $750bn → **III to II**.

   Expected:
   - Getting started: "40 of 40 figures match the filing exactly". The analyst's review notes Sun Belt's unrealised securities loss (about 20% of its CET1) and Atlantic Harbor's heavy goodwill.
   - At a glance: "AI and rulebook agree on 9 of 9 points", with the three readings unanimous.
   - Summary: every flagged result covered; a one-page memo with "all figures match the app's results".
2. **Canadian buyer that fails Reg K (works well).** Load **"Canadian buyer — TD buys Keystone National"**. Expected:
   - **Size:** $509bn + $470bn = $979bn → Category III to II. The rule check gets 9 of 9, including that Category II makes the holding company an "advanced approaches" bank, so the SLR, countercyclical buffer and AOCI apply.
   - **Reg K:** the U.S. share of TD's banking assets becomes **53.8%**, so test 2 is **not met**.
   - **Holdings:** the "two ways out" line reads: keep Reg K status by shedding more than **$137.6bn** of U.S. banking assets, or let it go and sell the holdings that depend on it. Keystone's own balance sheet shows $705m of real-estate ventures and $1.65bn of minority investments. Canadian buyer → **Use the example register** → **Review the holdings**: about 21 holdings get verdicts (most "at risk if Reg K status is lost"; few or none "must sell", e.g. U.S. bond underwriting), each checked against the Reg K result, with timing (about Oct 2029 for a July 2027 closing).
   - **AI analyst:** it typically checks headroom, then break-even, then the timeline (Category III in the first quarter after closing, Category II from the second), then capital stress scenarios.
   - **Summary:** the memo leads with the Reg K failure and the Category II move, names the holdings, and cites 12 CFR 211.23 and 252.5. For contrast, "RBC buys Liberty Square" passes Reg K comfortably.
3. **Deal options (works well).** Sun Belt + Atlantic Harbor → Deal options → **"Cash deal funded with debt"** → **Find ways to stay under the line**. The deal is $19.0bn over the $250bn line. Single-sale strategies fall short, the AI revises, and a combined sale lands around $248bn (Category IV). With "Friendly all-stock merger" the app says the line cannot be avoided, without calling the AI.
4. **Where it struggles.**
   - **Run-to-run variation (Haiku).** On the hardest rule question (a Canadian holding company becoming Category II), one AI reading sometimes misses the advanced-approaches link. The three-reading vote and the rulebook comparison catch this, and the page shows how many readings agreed.
   - **Memo checker.** The second AI check sometimes still flags one subtle statement after two revisions. The page shows "1 statement to verify" and quotes it, so the lawyer can fix it before sending.
   - **Older report layout.** TD's example Pillar 3 is a 2023 layout, so CET1 is "not found" and the OSFI ratios show "can't tell" until typed in. For CIBC, Reg K test 2 is "can't tell" without its Pillar 3.
   - **Off-topic question.** Ask "Who won the World Series?": the app declines.

## Run
```
pip install -r requirements.txt
python3 -m streamlit run app.py
```
Paste an API key into the left-hand panel. To rebuild the data:
- `python3 library.py build <folder of regulation PDFs>`
- `python3 build_structure.py <folder of NIC XML files>`
- `python3 build_y9c_template.py test_data/TD_US_FRY9C_2026Q2.pdf`
- `python3 make_example_banks.py`

Other test files: `BHCF20260930.txt` is a real Fed bulk file (18 smaller banks); `TD_illustrative_subsidiaries.txt` is a fictional subsidiaries list (it also works as a holdings register upload).

_Screening tool, not legal advice. The combined bank is the two banks added together (no purchase premium). The Reg K test uses assets from the filings and entered (or estimated) revenue and income shares. Disposal timing is a rough guide. Deal options use fictional preset terms. Verify against the filings and the rules cited._
