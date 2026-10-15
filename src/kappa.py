"""Cohen's kappa between Jev and Gemini labels; prints a table and writes one JSON line per result.
Usage (from src): python kappa.py labels/jev.jsonl classified_chunks.jsonl [kappa.jsonl]"""
import json
import re
import sys
from sklearn.metrics import cohen_kappa_score
from airo.taxonomy import MIT_SUBDOMAINS

SUBST = ["boilerplate", "generic", "specific", "detailed", "quantified"]   # ordinal order, low -> high
SINGLE = ["frame", "adoption_stage", "substantiveness"]
MULTI = ["roles", "risk_types", "mit_subdomains", "ai_kinds", "business_functions",
         "governance_responses", "disclosure_traits"]
MIT_DOMAINS = {"1": "Discrimination & toxicity", "2": "Privacy & security", "3": "Misinformation",
               "4": "Malicious actors & misuse", "5": "Human-computer interaction",
               "6": "Socioeconomic & environmental", "7": "AI system safety & limitations"}
DOMAIN_OF = {k: m[0] for k, (d, _) in MIT_SUBDOMAINS.items() if (m := re.findall(r"\b(\d)\.\d\b", d))}


def load(path):
    rows = {}
    for line in open(path, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            if "error" not in r:
                rows[r.get("passage_id") or r.get("chunk_id")] = r
    return rows


def kappa(a, b, **kw):
    if len(set(a) | set(b)) < 2:          # one value on both sides: kappa undefined
        return None
    return round(float(cohen_kappa_score(a, b, **kw)), 3)


def single(field, a, b, scope, **extra):
    return {"field": field, "value": None, "scope": scope, "n": len(a), "kappa": kappa(a, b),
            "agree": round(sum(x == y for x, y in zip(a, b)) / len(a), 3) if a else None, **extra}


def yes_no(field, value, a, b, scope):
    return {"field": field, "value": value, "scope": scope, "n": len(a), "kappa": kappa(a, b),
            "jev": sum(a), "gemini": sum(b), "both": sum(x and y for x, y in zip(a, b))}


jev_path, gem_path = sys.argv[1], sys.argv[2]
out_path = sys.argv[3] if len(sys.argv) > 3 else "kappa.jsonl"
jev, gem = load(jev_path), load(gem_path)
ids = sorted(jev.keys() & gem.keys())
both = [i for i in ids if jev[i]["ai_reference"] == "explicit" and gem[i]["ai_reference"] == "explicit"]
risky = lambda r: bool({"risk", "incident"} & set(r.get("roles") or []))
rk = [i for i in both if risky(jev[i]) and risky(gem[i])]
results = []

# 1. ai_reference, on every passage in both files
results.append(single("ai_reference", [jev[i]["ai_reference"] for i in ids], [gem[i]["ai_reference"] for i in ids],
                      "all passages"))

# 2. single-value fields, on passages both call explicit
for f in SINGLE:
    pairs = [(jev[i][f], gem[i][f]) for i in both if jev[i].get(f) is not None and gem[i].get(f) is not None]
    if not pairs:
        continue
    a, b = map(list, zip(*pairs))
    extra = {}
    if f == "substantiveness" and set(a) | set(b) <= set(SUBST):   # ordinal: near misses count partly
        extra["weighted_kappa"] = kappa([SUBST.index(x) for x in a], [SUBST.index(x) for x in b], weights="linear")
    results.append(single(f, a, b, "both explicit", **extra))

# 3. multi-value fields, one yes/no per value (MIT subdomains only where both coders see a risk)
for f in MULTI:
    rows, scope = (rk, "both risk/incident") if f == "mit_subdomains" else (both, "both explicit")
    for v in sorted({v for i in rows for v in (jev[i].get(f) or []) + (gem[i].get(f) or [])}):
        results.append(yes_no(f, v, [v in (jev[i].get(f) or []) for i in rows],
                              [v in (gem[i].get(f) or []) for i in rows], scope))

# 4. MIT's 7 domains
doms = lambda r: {DOMAIN_OF[s] for s in (r.get("mit_subdomains") or []) if s in DOMAIN_OF}
for d, name in MIT_DOMAINS.items():
    results.append(yes_no("mit_domains", f"{d}. {name}", [d in doms(jev[i]) for i in rk],
                          [d in doms(gem[i]) for i in rk], "both risk/incident"))

# print and save
fmt = lambda k: "  n/a" if k is None else f"{k:5.2f}"
print(f"{len(ids)} passages in both files; {len(both)} both explicit; {len(rk)} both risk/incident\n")
last = None
for r in results:
    if r["field"] != last and r["value"] is not None:
        print(f"\n{r['field']}  ({r['scope']}, one yes/no per value)")
    last = r["field"]
    if r["value"] is None:
        line = f"{r['field']:24} kappa {fmt(r['kappa'])}   agree {100 * r['agree']:5.1f}%   n={r['n']}"
        if "weighted_kappa" in r:
            line += f"   weighted kappa {fmt(r['weighted_kappa'])}"
        print(line)
    else:
        print(f"  {r['value']:42} kappa {fmt(r['kappa'])}   Jev {r['jev']:4}  Gemini {r['gemini']:4}  both {r['both']:4}")

with open(out_path, "w", encoding="utf-8") as fh:
    for r in results:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"\n{len(results)} results written to {out_path}")