"""
build_structure.py - run ONCE on your own computer (not by the app).

Reads the Federal Reserve's National Information Center (NIC) bulk structure files
(XML_ATTRIBUTES_ACTIVE.XML, XML_RELATIONSHIPS.XML, XML_ATTRIBUTES_BRANCHES.XML) and saves a
small summary of each Canadian bank's U.S. footprint to library/us_structure.json:

  * the parent and its U.S. intermediate holding company (IHC)
  * every U.S. company it controls - and whether it sits UNDER the IHC or OUTSIDE it
  * its U.S. branches and agencies (which stay outside the IHC by design)

Usage:  python3 build_structure.py <folder containing the NIC XML files>
The XML files are about 1GB in total, so they are NOT uploaded to GitHub - only the small JSON is.
"""

import json
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

PARENTS = {  # the four Canadian banks that buy U.S. banks (name in NIC)
    "ROYAL BANK OF CANADA": "RBC",
    "BANK OF MONTREAL": "BMO",
    "TORONTO-DOMINION BANK, THE": "TD",
    "CANADIAN IMPERIAL BANK OF COMMERCE": "CIBC",
}


def activity(naics):
    """Group a NAICS activity code (NIC field act_prim_cd) into a plain-English business line."""
    n = (naics or "").strip()
    if not n or n == "0":
        return "Not classified"
    for prefix, label in (("5221", "Banking"), ("5511", "Holding company"), ("5222", "Lending / finance"), ("5223", "Lending / finance"),
                          ("523", "Securities & investment"), ("524", "Insurance"), ("525", "Funds & trusts"), ("531", "Real estate"),
                          ("52", "Other financial")):
        if n.startswith(prefix):
            return label
    return "Non-financial (commercial)"


NONBANK = {"Insurance", "Real estate", "Non-financial (commercial)", "Securities & investment", "Funds & trusts", "Lending / finance", "Other financial"}
ENTITY_TYPES = {
    "BHC": "Bank holding company", "IHC": "Intermediate holding company", "FHD": "Financial holding company",
    "NAT": "National bank", "SMB": "State member bank", "NMB": "State non-member bank", "SSB": "State savings bank",
    "FSB": "Federal savings bank", "NTC": "Non-deposit trust company", "DEO": "Other U.S. company", "SBD": "Securities broker-dealer",
    "DPS": "Data processing / services", "FNC": "Finance company", "EDB": "Edge corporation (banking)", "EDI": "Edge corporation (investment)",
    "AGB": "Agency of a foreign bank", "IBR": "Insured branch of a foreign bank", "UIB": "Uninsured branch of a foreign bank",
    "FBH": "Foreign bank holding company", "FHF": "Foreign financial holding company", "FBK": "Foreign bank", "FEO": "Foreign company",
    "INB": "International non-bank", "AGI": "Agreement corporation", "REP": "Representative office",
    "USB": "U.S. branch (state licence)", "USA": "U.S. agency (state licence)", "UFB": "U.S. branch (federal licence)",
    "UFA": "U.S. agency (federal licence)", "IFB": "Insured U.S. branch (federal licence)", "ISB": "Insured U.S. branch (state licence)",
    "MTC": "Trust company (Fed member)",
}
US = "UNITED STATES"
# Reg K (12 CFR 211.23, footnote 10) treats U.S. territories as "the United States"
US_TERRITORIES = {"PUERTO RICO", "GUAM", "AMERICAN SAMOA", "VIRGIN ISLANDS (U.S.)", "VIRGIN ISLANDS, U.S.", "NORTHERN MARIANA ISLANDS"}


def text(el, tag):
    t = el.find(tag)
    return (t.text or "").strip() if t is not None and t.text else ""


def read_attributes(path, keep=None):
    out = {}
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "attributes":
            continue
        if text(el, "d_dt_end").startswith("9999"):
            rid = el.get("id_rssd")
            if keep is None or keep(el):
                out[rid] = {"rssd": rid, "name": text(el, "nm_lgl"), "type": text(el, "entity_type"), "naics": text(el, "act_prim_cd"),
                            "country": text(el, "cntry_nm"), "city": text(el, "city").title(), "state": text(el, "state_abbr_nm"),
                            "head_office": text(el, "id_rssd_hd_off")}
        el.clear()
    return out


def read_relationships(path):
    children = defaultdict(list)
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "relationship":
            continue
        if text(el, "dt_end") == "99991231" and text(el, "ctrl_ind") == "1":
            children[el.get("id_rssd_parent")].append((el.get("id_rssd_offspring"), text(el, "pct_equity")))
        el.clear()
    return children


def main(folder):
    print("Reading active entities…")
    ents = read_attributes(os.path.join(folder, "XML_ATTRIBUTES_ACTIVE.XML"))
    print(f"  {len(ents):,} entities")
    print("Reading ownership relationships…")
    children = read_relationships(os.path.join(folder, "XML_RELATIONSHIPS.XML"))
    parents = {rid: PARENTS[e["name"]] for rid, e in ents.items() if e["name"] in PARENTS}
    print("  Canadian parents found:", {v: k for k, v in parents.items()})

    print("Reading branches (U.S. branches and agencies of the parents)…")
    head_offices = set(parents)
    branches = read_attributes(os.path.join(folder, "XML_ATTRIBUTES_BRANCHES.XML"),
                               keep=lambda el: text(el, "id_rssd_hd_off") in head_offices)
    branches.update({rid: e for rid, e in ents.items() if e["head_office"] in head_offices})

    result = {}
    for prid, short in parents.items():
        # walk down the ownership tree, remembering whether we passed through an IHC
        us_entities, foreign, stack, seen = [], [], [(prid, False, 0)], set()
        ihcs = []
        while stack:
            rid, under_ihc, depth = stack.pop()
            if rid in seen:
                continue
            seen.add(rid)
            e = ents.get(rid)
            if not e:
                continue
            is_ihc = e["type"] == "IHC"
            if is_ihc:
                ihcs.append({"rssd": rid, "name": e["name"]})
            if rid != prid and e["country"] == US:
                us_entities.append({"name": e["name"], "rssd": rid, "type": ENTITY_TYPES.get(e["type"], e["type"]),
                                    "code": e["type"], "where": f"{e['city']}, {e['state']}", "under_ihc": under_ihc or is_ihc,
                                    "is_ihc": is_ihc, "depth": depth})
            elif rid != prid and not is_ihc:
                # a non-U.S. holding: does it itself own anything in the U.S.?
                us_kids = [c for c, _ in children.get(rid, []) if ents.get(c, {}).get("country") == US]
                foreign.append({"name": e["name"], "country": e["country"].title(), "activity": activity(e["naics"]),
                                "type": ENTITY_TYPES.get(e["type"], e["type"]), "us_business": bool(us_kids),
                                "us_territory": e["country"].upper() in US_TERRITORIES})
            for child, _pct in children.get(rid, []):
                stack.append((child, under_ihc or is_ihc, depth + 1))
        brs = [{"name": b["name"], "type": ENTITY_TYPES.get(b["type"], b["type"]), "where": f"{b['city']}, {b['state']}"}
               for b in branches.values() if b["head_office"] == prid and b["country"] == US]
        outside = [x for x in us_entities if not x["under_ihc"]]
        result[short] = {"parent": ents[prid]["name"], "parent_rssd": prid, "ihcs": ihcs,
                         "us_entities_total": len(us_entities), "under_ihc": sum(x["under_ihc"] for x in us_entities),
                         "outside_ihc": sorted(outside, key=lambda x: x["name"]), "branches": sorted(brs, key=lambda x: x["name"]),
                         "by_type_under_ihc": dict(sorted(_count([x["type"] for x in us_entities if x["under_ihc"]]).items(), key=lambda kv: -kv[1])),
                         "parent_type": ENTITY_TYPES.get(ents[prid]["type"], ents[prid]["type"]), "parent_code": ents[prid]["type"],
                         "territory_holdings": sorted([f for f in foreign if f["us_territory"]], key=lambda f: f["name"]),
                         "foreign_total": len([f for f in foreign if not f["us_territory"]]),
                         "foreign_all": sorted([f for f in foreign if not f["us_territory"]], key=lambda f: f["name"])[:200],
                         "foreign_by_activity": dict(sorted(_count([f["activity"] for f in foreign if not f["us_territory"]]).items(), key=lambda kv: -kv[1])),
                         "foreign_by_country": dict(sorted(_count([f["country"] for f in foreign if not f["us_territory"]]).items(), key=lambda kv: -kv[1])[:8]),
                         "foreign_with_us_business": sorted([f for f in foreign if f["us_business"] and not f["us_territory"]], key=lambda f: f["name"])[:40],
                         "foreign_nonbank": sorted([f for f in foreign if f["activity"] in ("Insurance", "Real estate", "Non-financial (commercial)") and not f["us_territory"]],
                                                   key=lambda f: (f["activity"], f["name"]))[:60]}
        print(f"  {short}: {len(foreign)} non-U.S. holdings {result[short]['foreign_by_activity']}")
        print(f"  {short}: IHC {[i['name'] for i in ihcs]} · {result[short]['under_ihc']} U.S. companies under it · "
              f"{len(outside)} outside · {len(brs)} branches/agencies")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "library", "us_structure.json")
    with open(out, "w") as fh:
        json.dump(result, fh, indent=1)
    print("Saved", out)


def _count(items):
    c = defaultdict(int)
    for i in items:
        c[i] += 1
    return c


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
