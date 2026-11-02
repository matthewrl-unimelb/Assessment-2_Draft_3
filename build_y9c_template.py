"""
build_y9c_template.py - run ONCE (not by the app).

Builds library/y9c_template.json: the lines of the FR Y-9C that the AI reads -
  * Schedule HC (balance sheet): read straight from a real FR Y-9C PDF, where each printed line carries
    its caption, item number and the code of the field that holds its value (e.g. "12. Total assets ... 2170 12.");
  * Schedule HC-M item 12.b (goodwill);
  * Schedule HC-R Part I (regulatory capital): typed in below from the form, because the PDF's text layer
    prints those codes apart from their captions. Every code was checked against a real filing's field values.

With the template, the app can lay out ANY bank's filing - from a PDF or from the Fed's bulk .txt file - as
"item, caption, code, value" lines, so the AI reads the filing the way an analyst would.

Usage:  python3 build_y9c_template.py test_data/TD_US_FRY9C_2026Q2.pdf
"""

import json
import os
import re
import sys

from pypdf import PdfReader

HC_PAGES = (15, 16)                 # 0-based page numbers of Schedule HC in the 2026 form
HC_M_PAGE, HC_M_CODES = 37, {"3163"}

LINE = re.compile(r"^(?P<cap>.*?)(?:\.{2,}|\s)\s*(?:(?P<pfx>BH[A-Z]{2})\s+)?(?P<code>[A-Z0-9]{4})\s+(?P<item>\d+\.[a-z0-9\.\(\)]*)\s*$")
ITEM_START = re.compile(r"^(\d+\.\s*)?([a-z]\.\s*)?(\(\d+\)\s*)?")

HC_R = [  # (item, caption as printed on the form, MDRM)
    ("1", "Common stock plus related surplus, net of treasury stock and unearned employee stock ownership plan (ESOP) shares", "BHCAP742"),
    ("2", "Retained earnings", "BHCAKW00"),
    ("3", "Accumulated other comprehensive income (AOCI)", "BHCAB530"),
    ("3.a", "AOCI opt-out election (enter \"1\" for Yes; enter \"0\" for No)", "BHCAP838"),
    ("4", "Common equity tier 1 minority interest includable in common equity tier 1 capital", "BHCAP839"),
    ("5", "Common equity tier 1 capital before adjustments and deductions (sum of items 1 through 4)", "BHCAP840"),
    ("6", "LESS: Goodwill net of associated deferred tax liabilities (DTLs)", "BHCAP841"),
    ("7", "LESS: Intangible assets (other than goodwill and mortgage servicing assets (MSAs)), net of associated DTLs", "BHCAP842"),
    ("8", "LESS: Deferred tax assets (DTAs) that arise from net operating loss and tax credit carryforwards, net of any related valuation allowances and net of DTLs", "BHCAP843"),
    ("12", "Subtotal (item 5 minus items 6 through 11)", "BHCAP852"),
    ("18", "Total adjustments and deductions for common equity tier 1 capital", "BHCAP858"),
    ("19", "Common equity tier 1 capital (item 12 minus item 18)", "BHCAP859"),
    ("25", "Additional tier 1 capital", "BHCAP865"),
    ("26", "Tier 1 capital (sum of items 19 and 25)", "BHCA8274"),
    ("27", "Average total consolidated assets", "BHCAKW03"),
    ("28", "LESS: Deductions from common equity tier 1 capital and additional tier 1 capital", "BHCAP875"),
    ("29", "LESS: Other deductions from (additions to) assets for leverage ratio purposes", "BHCAB596"),
    ("30", "Total assets for the leverage ratio (item 27 minus items 28 and 29)", "BHCAA224"),
    ("31", "Leverage ratio (item 26 divided by item 30) - percentage", "BHCA7204"),
    ("44.a", "Tier 2 capital", "BHCA5311"),
    ("45.a", "Total capital (sum of items 26 and 44.a)", "BHCA3792"),
    ("46.a", "Total risk-weighted assets (from Schedule HC-R, Part II item 31)", "BHCAA223"),
    ("47", "Common equity tier 1 capital ratio - percentage", "BHCAP793"),
    ("48", "Tier 1 capital ratio - percentage", "BHCA7206"),
    ("49", "Total capital ratio - percentage", "BHCA7205"),
    ("50", "Capital conservation buffer - percentage", "BHCAH311"),
    ("53", "Supplementary leverage ratio - percentage (advanced approaches and Category III holding companies only)", "BHCAH036"),
]


def _clean(cap):
    cap = re.sub(r"\.{2,}", "", cap).strip(" .")
    cap = re.sub(r"(?<=[\)a-z])\d(,\s*\d)*$", "", cap)          # footnote markers, e.g. "resell5, 6"
    cap = re.sub(r":\d(,\s*\d)*$", "", cap).rstrip(":")
    return re.sub(r"\s+", " ", cap)


def read_page_lines(reader, page, schedule, keep_codes=None):
    text = reader.pages[page].extract_text() or ""
    head = re.search(r"Dollar Amounts in Thousands\s+(BH[A-Z]{2})", text)
    prefix = head.group(1) if head else "BHCK"
    headers, subs, out, prev, last_num = {}, {}, [], "", ""
    for raw in text.split("\n"):
        line = raw.strip()
        m0 = re.match(r"^(BH[A-Z]{2})(?=\s|\d|$)", line)          # a prefix printed at the start of a line
        if m0:
            prefix, line = m0.group(1), line[4:].strip()
        m1 = re.search(r":\s*(BH[A-Z]{2})\s*$", line)              # ... or at the end of a heading
        if m1:
            prefix = m1.group(1)
        m = LINE.match(line)
        if not m:
            hm = re.match(r"^(\d+)\.\s+(.*)$", line)
            if hm and not re.search(r"\d{4}\s+\d+\.", line):
                headers.setdefault(hm.group(1), _clean(re.sub(r":\s*BH[A-Z]{2}\s*$", "", hm.group(2))))   # first wins (not footnotes)
                last_num = hm.group(1)
            sm = re.match(r"^([a-z])\.\s+(.*)$", line)
            if sm and last_num:
                subs.setdefault(f"{last_num}.{sm.group(1)}", _clean(re.sub(r":\s*BH[A-Z]{2}\s*$", "", sm.group(2))).rstrip(":"))
            prev = line
            continue
        code = m.group("code")
        if keep_codes and code not in keep_codes:
            continue
        cap = _clean(m.group("cap"))
        if not re.match(r"^(\d+\.|[a-z]\.|\(\d+\))", cap) and prev:        # caption ran over two lines
            cap = _clean(re.sub(r"^BH[A-Z]{2}", "", prev) + " " + cap)
        item = m.group("item").rstrip(".")
        number = item.split(".")[0]
        last_num = number
        body = _clean(ITEM_START.sub("", cap))
        parent = headers.get(number, "") if "." in item and headers.get(number, "") != body else ""
        letter = ".".join(item.split(".")[:2])
        if item.count(".") >= 2 and subs.get(letter):
            parent = (parent.rstrip(":") + " — " if parent else "") + subs[letter]
        out.append({"schedule": schedule, "item": item, "caption": body, "parent": parent.rstrip(":"),
                    "mdrm": (m.group("pfx") or prefix) + code})
        prev = ""
    return out


def _order(item):
    return [int(p) if p.isdigit() else p for p in re.findall(r"\d+|[a-z]+", item)]


def build(pdf_path):
    r = PdfReader(pdf_path)
    hc = []
    for p in HC_PAGES:
        hc += read_page_lines(r, p, "HC")
    hc.sort(key=lambda x: _order(x["item"]))
    hcm = read_page_lines(r, HC_M_PAGE, "HC-M", HC_M_CODES)
    for x in hcm:
        x["caption"], x["parent"] = "Goodwill", "Intangible assets"
    hcr = [{"schedule": "HC-R Part I", "item": i, "caption": c, "parent": "", "mdrm": m} for i, c, m in HC_R]
    return {"schedules": {"HC": "Schedule HC - Consolidated Balance Sheet", "HC-M": "Schedule HC-M - Memoranda",
                          "HC-R Part I": "Schedule HC-R Part I - Regulatory Capital Components and Ratios"},
            "lines": hc + hcm + hcr}


if __name__ == "__main__":
    tpl = build(sys.argv[1] if len(sys.argv) > 1 else os.path.join("test_data", "TD_US_FRY9C_2026Q2.pdf"))
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "library", "y9c_template.json")
    with open(out, "w") as fh:
        json.dump(tpl, fh, indent=1)
    print(f"Saved {out}: {len(tpl['lines'])} lines")
