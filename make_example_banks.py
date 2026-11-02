"""
make_example_banks.py - builds test_data/EXAMPLE_BANKS_2026Q2.txt: FICTIONAL bank holding companies sized just
below the category lines, so example deals actually cross them. Same layout as the Fed's bulk FR Y-9C file.
All names are invented and marked (FICTIONAL); the figures are internally consistent but not real:
  * the balance sheet adds up (Schedule HC items 1-11 = item 12; liabilities + equity = item 29);
  * CET1 = equity - goodwill - other intangibles + the AOCI loss that the opt-out election removes (HC-R Part I);
  * every reported ratio can be recomputed from its parts.
Each bank has its own story (e.g. a large unrealised securities loss, or heavy goodwill) for the AI's review to find.
"""
import os

BANKS = [
    # rssd,     name,                                    city,          state, total $bn, CET1%, AT1%, T2%, AOCI loss % assets, story
    ("9000001", "GREAT LAKES FINANCIAL CORP (FICTIONAL)", "CLEVELAND", "OH", 88.0, 10.6, 0.6, 1.8, 0.4, "plain"),
    ("9000002", "PRAIRIE TRUST BANCORP (FICTIONAL)",     "OMAHA",     "NE", 62.0, 11.2, 0.0, 1.5, 0.3, "plain"),
    ("9000003", "SUN BELT BANCSHARES (FICTIONAL)",       "ATLANTA",   "GA", 228.0, 10.1, 0.9, 2.0, 1.4, "aoci"),
    ("9000004", "ATLANTIC HARBOR BANCORP (FICTIONAL)",   "BOSTON",    "MA", 41.0, 7.4, 0.5, 1.6, 0.6, "goodwill"),
    ("9000005", "PACIFIC CREST FINANCIAL (FICTIONAL)",   "SAN FRANCISCO", "CA", 655.0, 11.4, 1.0, 2.1, 0.9, "trading"),
    ("9000006", "CASCADE BANCORP (FICTIONAL)",           "SEATTLE",   "WA", 95.0, 10.9, 0.4, 1.7, 0.5, "plain"),
    ("9000007", "KEYSTONE NATIONAL BANCORP (FICTIONAL)", "PHILADELPHIA", "PA", 470.0, 11.0, 1.1, 2.2, 1.1, "htm"),
    ("9000008", "LIBERTY SQUARE HOLDINGS (FICTIONAL)",   "NEW YORK",  "NY", 58.0, 12.0, 0.0, 1.4, 0.2, "plain"),
]
CODES = ["RSSD9001", "RSSD9017", "RSSD9130", "RSSD9200", "RSSD9999",
         # Schedule HC - assets
         "BHCK0081", "BHCK0395", "BHCKJJ34", "BHCK1773", "BHCKJA22", "BHCKB528", "BHCK3123", "BHCKB529", "BHCK3545", "BHCK2145",
         "BHCK2150", "BHCK2130", "BHCK3656", "BHCK2160", "BHCK2170",
         # Schedule HC - liabilities and equity
         "BHDM6631", "BHDM6636", "BHCKB995", "BHCK3190", "BHCK4062", "BHCK2750", "BHCK2948",
         "BHCK3230", "BHCK3240", "BHCK3247", "BHCKB530", "BHCK3210", "BHCK3000", "BHCKG105", "BHCK3300",
         # Schedule HC-M - goodwill
         "BHCK3163",
         # Schedule HC-R Part I - capital
         "BHCAP742", "BHCAKW00", "BHCAB530", "BHCAP838", "BHCAP839", "BHCAP840", "BHCAP841", "BHCAP842", "BHCAP843", "BHCAP852",
         "BHCAP858", "BHCAP859", "BHCAP865", "BHCA8274", "BHCAKW03", "BHCAP875", "BHCAB596", "BHCAA224", "BHCA7204",
         "BHCA5311", "BHCA3792", "BHCAA223", "BHCAP793", "BHCA7206", "BHCA7205", "BHCAH036"]


def row(rssd, name, city, state, total_bn, cet1_pct, at1_pct, t2_pct, aoci_pct, story):
    ta = round(total_bn * 1e6)                      # thousands of dollars
    avg = round(ta * 0.975)
    rwa = round(ta * 0.71)
    cet1 = round(rwa * cet1_pct / 100)
    t1 = cet1 + round(rwa * at1_pct / 100)
    t2 = round(rwa * t2_pct / 100)
    tot = t1 + t2
    slr = f"{100 * t1 / (ta * 1.12):.4f}" if total_bn >= 250 else ""   # leverage exposure ~ 112% of assets
    liab = round(ta * 0.905)
    equity = ta - liab                                # Schedule HC item 27.a (no minority interest)
    aoci = -round(ta * aoci_pct / 100)                # an unrealised loss
    intang = round(ta * 0.003)
    pref = t1 - cet1                                  # additional tier 1 = perpetual preferred (kept in surplus line for simplicity)
    # CET1 = (equity - preferred) - goodwill - intangibles - AOCI (the opt-out reverses the loss)  => solve for goodwill
    goodwill = (equity - pref) - intang - aoci - cet1
    assert goodwill > 0, name
    # assets: cash, securities, loans, trading, premises, goodwill sits in other assets
    cash_nib, cash_ib = round(ta * 0.015), round(ta * 0.055)
    htm = round(ta * (0.12 if story == "htm" else 0.07))
    afs = round(ta * (0.19 if story == "aoci" else 0.13))
    trading = round(ta * (0.06 if story == "trading" else 0.0))
    loans = round(ta * 0.62) - (htm + afs + trading - round(ta * 0.20))
    allowance = round(loans * 0.012)
    premises = round(ta * 0.008)
    # lines a holding company may have to sell or conform (Keystone carries some, for the holdings review to find)
    big = story == "htm"
    equity_sec = round(ta * (0.0006 if big else 0.0001))
    oreo = round(ta * (0.0002 if big else 0.00005))
    unconsol = round(ta * (0.0035 if big else 0.0))
    re_ventures = round(ta * (0.0015 if big else 0.0))
    other = ta - (cash_nib + cash_ib + htm + afs + equity_sec + (loans - allowance) + trading + premises + oreo + unconsol + re_ventures)
    assert other > goodwill + intang, name
    # liabilities
    dep_nib, dep_ib = round(ta * 0.18), round(ta * 0.56)
    repo, sub = round(ta * 0.04), round(ta * 0.01)
    other_liab = round(ta * 0.035)
    borrowed = liab - (dep_nib + dep_ib + repo + sub + other_liab)
    common, retained = round((equity - pref - aoci) * 0.35), None
    retained = equity - pref - aoci - common
    kw03 = avg + goodwill + intang                    # average total consolidated assets, before deductions
    v = {"RSSD9001": rssd, "RSSD9017": name, "RSSD9130": city, "RSSD9200": state, "RSSD9999": "20260630",
         "BHCK0081": cash_nib, "BHCK0395": cash_ib, "BHCKJJ34": htm, "BHCK1773": afs, "BHCKB528": loans, "BHCK3123": allowance,
         "BHCKJA22": equity_sec, "BHCKB529": loans - allowance, "BHCK3545": trading, "BHCK2145": premises, "BHCK2150": oreo,
         "BHCK2130": unconsol, "BHCK3656": re_ventures, "BHCK2160": other, "BHCK2170": ta,
         "BHDM6631": dep_nib, "BHDM6636": dep_ib, "BHCKB995": repo, "BHCK3190": borrowed, "BHCK4062": sub, "BHCK2750": other_liab,
         "BHCK2948": liab, "BHCK3230": common, "BHCK3240": pref, "BHCK3247": retained, "BHCKB530": aoci, "BHCK3210": equity,
         "BHCK3000": 0, "BHCKG105": equity, "BHCK3300": ta, "BHCK3163": goodwill,
         "BHCAP742": common, "BHCAKW00": retained, "BHCAB530": aoci, "BHCAP838": 1, "BHCAP839": 0,
         "BHCAP840": common + retained + aoci, "BHCAP841": goodwill, "BHCAP842": intang, "BHCAP843": 0,
         "BHCAP852": cet1, "BHCAP858": 0, "BHCAP859": cet1, "BHCAP865": pref, "BHCA8274": t1, "BHCAKW03": kw03,
         "BHCAP875": goodwill + intang, "BHCAB596": 0, "BHCAA224": avg, "BHCA7204": f"{100 * t1 / avg:.4f}",
         "BHCA5311": t2, "BHCA3792": tot, "BHCAA223": rwa, "BHCAP793": f"{100 * cet1 / rwa:.4f}", "BHCA7206": f"{100 * t1 / rwa:.4f}",
         "BHCA7205": f"{100 * tot / rwa:.4f}", "BHCAH036": slr}
    # sanity: HC adds up; CET1 reconciles (item 5 - 6 - 7 + AOCI removed under the opt-out = item 19)
    assert v["BHCK2948"] + v["BHCKG105"] == ta
    assert v["BHCAP840"] - goodwill - intang - aoci == cet1, name
    return "^".join(str(v[c]) for c in CODES)


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_data", "EXAMPLE_BANKS_2026Q2.txt")
    with open(out, "w") as fh:
        fh.write("^".join(CODES) + "\n" + "\n".join(row(*b) for b in BANKS) + "\n")
    print("wrote", out)
