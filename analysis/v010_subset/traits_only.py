"""Disclosure traits alone: a call that asks for `disclosure_traits` and nothing else.

Round 11 of the v0.10 subset test. Two codebooks that differ only in the traits:
    current   the definitions and criteria of `taxonomy.py`
    revised   loosened criteria for boilerplate, externalisation and vagueness (hedging keeps its criteria),
              and one constructed example for and one against each trait

The tasks are the passages of the V3 human validation that gemini-2.5-flash called `explicit` in
round 5; the others get no traits. The role condition on `externalisation` is applied afterwards
with round 5's roles. The examples are constructed; none comes from the 290 passages. The criteria
were loosened after looking at trait frequencies on these same passages, so the test is not held out.
The revised codebook was adopted (docs/changes.md, entry 24): `current` now resolves to it, and the run's
`current` is the taxonomy before that entry (the bucket keeps its codebook_current.md).

    python analysis/v010_subset/traits_only.py --project <project> --out gs://<bucket>/<folder>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "human_validation"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pydantic import BaseModel, Field  # noqa: E402

from airo import classify, taxonomy as tx  # noqa: E402
from airo.coders import gemini  # noqa: E402
from human_validation import kappa  # noqa: E402

RUN = "gs://airo-pipeline-data/us-2025h1_V3"
TASKS = "gs://version10test/tasks.jsonl"
ROUND5 = "gs://version10test/round5_examples_source/hope_only.jsonl"
FIVE_RATERS = (2, 3, 4, 5, 7)
EXTERNALISATION_ROLES = {"adoption", "offering", "governance", "risk", "incident"}

REVISED: dict[str, tx.Definition] = {
    "boilerplate": (
        "Generic language that could appear unchanged in any company's report.",
        (
            "no company-specific system, counterparty, figure, date or action",
            "the sentence would remain equally fitting in another company's report",
        ),
    ),
    "hedging": tx.DISCLOSURE_TRAITS["hedging"],
    "externalisation": (
        "Responsibility or origin of the AI risk is placed outside the company.",
        (
            "the AI or its risk is attributed to vendors, service providers, customers, developers or attackers",
            "the statement presents them, not the company's own decisions, as the source of the risk",
        ),
    ),
    "vagueness": (
        "The AI referent is left undefined.",
        (
            "AI is named only as a category (\"emerging technologies such as AI\", \"AI tools\")",
            "no function, process or purpose is given",
        ),
    ),
}

EXAMPLES = """Constructed examples, one for and one against each trait:

- `boilerplate`
  applies: "Artificial intelligence may affect our business and the markets in which we operate."
  does not apply: "Our claims unit uses a machine-learning model to route incoming claims."
- `hedging`
  applies: "Our use of AI could fail to deliver the benefits we expect."
  does not apply: "We deployed an AI assistant to our support staff in March and it handled 12% of tickets." (nothing is uncertain)
- `externalisation`
  applies: "Third-party AI vendors may introduce errors into the tools we rely on."
  does not apply: "Our decision to build our own AI models exposes us to errors in those models." (the source is the company's own decision)
- `vagueness`
  applies: "We continue to invest in emerging technologies such as AI."
  does not apply: "We use AI to forecast demand for spare parts." (a purpose is given)
"""

INTRO = """# Codebook: disclosure traits of AI statements in corporate reports

Every passage below contains a statement about artificial intelligence. Give two fields for each:
`passage_id`, copied from the task, and `disclosure_traits`.

"""
LEAD = ("Zero or more values. Judged on the AI-related statements of the passage: a trait applies if any "
        "AI-related statement meets all its criteria. `[]` means none of the traits apply.")


def codebook(defs: dict, examples: str = "") -> str:
    table = tx._table("Which disclosure traits does the AI statement show?", "disclosure_traits", LEAD, defs)
    return INTRO + table + ("\n" + examples if examples else "")


class TraitLabel(BaseModel):
    passage_id: str
    disclosure_traits: list[tx.DisclosureTrait] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)  # read by the acceptance check; not asked for


class TraitLabels(BaseModel):
    labels: list[TraitLabel]


def cat(url: str) -> str:
    return subprocess.run(["gcloud", "storage", "cat", url], capture_output=True, check=True).stdout.decode("utf-8")


def rj(url: str) -> list[dict]:
    return [json.loads(line) for line in cat(url).splitlines() if line.strip()]


def put(url: str, text: str) -> None:
    subprocess.run(["gcloud", "storage", "cp", "-q", "-", url], input=text.encode("utf-8"), check=True)


def score(humans: list[dict], traits: dict[str, list[str]]) -> dict[str, tuple[float, float, int, int]]:
    """Per trait and for the exact set: kappa, share identical, how often the person and the model give it."""
    out = {}
    for t in tx.DISCLOSURE_TRAITS:
        p = [(t in (h.get("disclosure_traits") or []), t in traits.get(h["passage_id"], [])) for h in humans]
        s = [(str(a), str(b)) for a, b in p]
        out[t] = (kappa(s), sum(a == b for a, b in p) / len(p), sum(a for a, _ in p), sum(b for _, b in p))
    s = [(",".join(sorted(h.get("disclosure_traits") or [])), ",".join(sorted(traits.get(h["passage_id"], [])))) for h in humans]
    out["exact set"] = (kappa(s), sum(a == b for a, b in s) / len(s), 0, 0)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--location", default="us-central1")
    args = ap.parse_args()
    out = args.out.rstrip("/")

    classify.Label, gemini.Label, gemini.Labels = TraitLabel, TraitLabel, TraitLabels
    gemini.request_config.__defaults__ = (None, gemini.MAX_OUTPUT_TOKENS, TraitLabel)

    round5 = {l["passage_id"]: l for l in rj(ROUND5)}
    tasks = [t for t in rj(TASKS) if round5.get(t["passage_id"], {}).get("ai_reference") == "explicit"]
    client = gemini.make_client(args.project, args.location)
    variants: dict[str, dict[str, list[str]]] = {
        "full call, round 5": {p: l.get("disclosure_traits") or [] for p, l in round5.items()},
    }
    books = {"current": codebook(tx.DISCLOSURE_TRAITS), "revised": codebook(REVISED, EXAMPLES)}
    report = []
    for name, book in books.items():
        put(f"{out}/codebook_{name}.md", book)
        start = time.perf_counter()
        results = gemini.code(tasks, book, model="gemini-2.5-flash", client=client, workers=4, max_retries=5,
                              max_repairs=2, batch_size=40, thinking_budget=0)
        summary = gemini.run_summary(results, prices=None, wall_time_s=time.perf_counter() - start)
        labels = [r["label"] for r in results if r["error"] is None and r["label"] is not None]
        put(f"{out}/{name}.jsonl", "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in labels))
        put(f"{out}/{name}.jsonl.run.json", json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
        report.append(f"- {name}: {summary['succeeded']} of {summary['tasks']} labelled, {summary['tokens']['input_tokens']:,} in / "
                      f"{summary['tokens']['output_tokens']:,} out, {summary['wall_time_s']} s, failures "
                      f"{[f['passage_id'] for f in summary['failures']]}")
        traits = {}
        for l in labels:
            got = list(l["disclosure_traits"])
            if not set(round5[l["passage_id"]].get("roles") or []) & EXTERNALISATION_ROLES:
                got = [t for t in got if t != "externalisation"]
            traits[l["passage_id"]] = got
        variants[name] = traits

    done = set.intersection(*[set(v) for k, v in variants.items() if k != "full call, round 5"])
    explicit = {t["passage_id"] for t in tasks} & done
    keep = explicit | {p for p, l in round5.items() if l.get("ai_reference") != "explicit"}
    for v in variants.values():
        for p in keep:
            v.setdefault(p, [])
    raw = {k: rj(f"{RUN}/human_validation/labels/human_{k}.jsonl") for k in range(1, 8)}
    strip = lambda h: {**h, "disclosure_traits": [t for t in (h.get("disclosure_traits") or []) if t != "safe_harbour"]}
    groups = {"five raters": FIVE_RATERS, "seven raters": tuple(range(1, 8))}
    md = ["# Round 11: disclosure traits alone, current against revised criteria and examples", "",
          f"gemini-2.5-flash, thinking off, 40 per request. Scored on {len(keep)} passages with labels from every variant; "
          "`safe_harbour` is taken out of the ratings. Not held out: see the script's docstring.", "", *report, ""]
    names = list(variants)
    for g, ks in groups.items():
        humans = [strip(h) for k in ks for h in raw[k] if h["passage_id"] in keep]
        scores = {n: score(humans, variants[n]) for n in names}
        md += [f"## {g}, {len(humans)} ratings", "",
               "| Trait | Person yes | " + " | ".join(f"{n}: kappa (agree), model yes" for n in names) + " |",
               "|---|---|" + "---|" * len(names)]
        for t in [*tx.DISCLOSURE_TRAITS, "exact set"]:
            first = scores[names[0]][t]
            person = "" if t == "exact set" else str(first[2])
            cells = [f"{scores[n][t][0]:.2f} ({scores[n][t][1]:.2f})" + ("" if t == "exact set" else f", {scores[n][t][3]}") for n in names]
            md.append(f"| {t} | {person} | " + " | ".join(cells) + " |")
        md.append("")
    md += ["## Labels with no trait", ""]
    for n in names:
        md.append(f"- {n}: {sum(not variants[n].get(p) for p in explicit)} of {len(explicit)} passages about AI")
    text = "\n".join(md) + "\n"
    put(f"{out}/agreement.md", text)
    put(f"{out}/traits_only.py", Path(__file__).read_text(encoding="utf-8"))
    print(text)


if __name__ == "__main__":
    main()
