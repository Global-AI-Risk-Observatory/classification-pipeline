"""Functional fragmentation of AI disclosure passages, without Evalet.

The method (Kim et al., "Evalet", CHI 2026, arXiv 2509.11206): take fragments of text, give
each fragment a short abstract description of the function it serves, embed those descriptions,
cluster them, name the clusters. Evalet is a browser tool built around it; this is the method
alone, as a script over the US pipeline's labelled passages.

The fragments are the evidence quotes the classifier stored with every label (one to three
verbatim quotes per passage), so the expensive step of Evalet, extracting fragments from long
text, is already done. A subset is chosen by label (an MIT subdomain, a role, a trait), not by a
free-text criterion.

Steps, each one a sub-command writing one file under work/<subset>/:

    fetch     read the run's labels and chunks from the bucket, keep the subset -> quotes.jsonl
    describe  one function sentence per quote (Gemini, 40 quotes per request)   -> functions.jsonl
    embed     embed the function sentences (Vertex AI)                           -> embeddings.npy
    cluster   HDBSCAN on the embeddings, UMAP to 2-D for the plot                -> clusters.jsonl
    name      a name and a one-sentence summary per cluster (Gemini)            -> names.jsonl
    assign    per cluster, the reference categories it fits (Gemini; --question only) -> assignments.jsonl
    report    cluster table and plots                                           -> results/<subset>/

    python functional_fragmentation.py all --run gs://<bucket>/<run> --subdomain <value> \
        --project <gcp project> [--location us-central1]

--question runs one of the research plan's questions instead of a single label; it splits the
subset into groups where the question asks for it and writes work/<question>/<group>/ and
results/<question>/<group>/:

    residual    1.1  risk passages whose only MIT subdomain is `other`
    governance  1.2  governance passages, one group per governance response; clusters assigned
                     to the AI risk mitigation subcategories (MITIGATIONS)
    hedging     1.3  passages with the trait `hedging`; clusters assigned to the five traits or none
    adoption    1.4  adoption passages with business function `not_stated`, `rd_product`,
                     `operations`; `not_stated` clusters assigned to the business functions or none

Model calls go through Vertex AI in the given project. Quotes stay in work/ (git-ignored); the
results folder holds counts, names, summaries and plots only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

MODEL = "gemini-2.5-flash"
EMBEDDING_MODEL = "gemini-embedding-001"
BATCH = 40

# AI risk mitigation subcategories: number -> (name, definition).
# 1.1 to 4.6: Saeri, Lloyd George, Graham, Lacarriere, Slattery, Noetel, Thompson, "Mapping AI Risk
# Mitigations: Evidence Scan and Preliminary AI Risk Mitigation Taxonomy", arXiv 2512.11931, Table 1
# (4 categories, 23 subcategories; also airisk.mit.edu/ai-risk-mitigations, CC BY 4.0).
# 3.7, 4.7 and 5.1 to 8.1: Popchanovska, Gjorgjevikj, Rizinski, Chitkushev, Vodenska, Trajanov,
# "When AI Fails, What Works? A Data-Driven Taxonomy of Real-World AI Risk Mitigation Strategies",
# arXiv 2603.04259v1, Appendix A (nine subcategories added from incident reports; 32 in total).
# `other` is this analysis's open category for a measure that fits none of them.
MITIGATION_CATEGORIES = {
    "1": "Governance & Oversight",
    "2": "Technical & Security",
    "3": "Operational Process",
    "4": "Transparency & Accountability",
    "5": "Corrective & Restrictive Actions",
    "6": "Legal, Regulatory & Enforcement Actions",
    "7": "Financial, Economic & Market Controls",
    "8": "Avoidance & Denial",
}
MITIGATIONS: dict[str, tuple[str, str]] = {
    "1.1": ("Board Structure & Oversight",
            "Governance structures and leadership roles that establish executive accountability for AI safety and "
            "risk management."),
    "1.2": ("Risk Management",
            "Systematic methods that identify, evaluate, and manage AI risks for comprehensive risk governance "
            "across organizations."),
    "1.3": ("Conflict of Interest Protections",
            "Governance mechanisms that manage financial interests and organizational structures to ensure "
            "leadership can prioritize safety over profit motives in critical situations."),
    "1.4": ("Whistleblower Reporting & Protection",
            "Policies and systems that enable confidential reporting of safety concerns or ethical violations to "
            "prevent retaliation and encourage disclosure of risks."),
    "1.5": ("Safety Decision Frameworks",
            "Protocols and commitments that constrain decision-making about model development, deployment, and "
            "capability scaling, and govern safety-capability resource allocation to prevent unsafe AI advancement."),
    "1.6": ("Environmental Impact Management",
            "Processes for measuring, reporting, and reducing the environmental footprint of AI systems to ensure "
            "sustainability and responsible resource use."),
    "1.7": ("Societal Impact Assessment",
            "Processes that assess AI systems' effects on society, including impacts on employment, power "
            "dynamics, political processes, and cultural values."),
    "2.1": ("Model & Infrastructure Security",
            "Technical and physical safeguards that secure AI models, weights, and infrastructure to prevent "
            "unauthorized access, theft, tampering, and espionage."),
    "2.2": ("Model Alignment",
            "Technical methods to ensure AI systems understand and adhere to human values and intentions."),
    "2.3": ("Model Safety Engineering",
            "Technical methods and safeguards that constrain model behaviors and protect against exploitation and "
            "vulnerabilities."),
    "2.4": ("Content Safety Controls",
            "Technical systems and processes that detect, filter, and label AI-generated content to identify misuse "
            "and enable content provenance tracking."),
    "3.1": ("Testing & Auditing",
            "Systematic internal and external evaluations that assess AI systems, infrastructure, and compliance "
            "processes to identify risks, verify safety, and ensure performance meets standards."),
    "3.2": ("Data Governance",
            "Policies and procedures that govern responsible data acquisition, curation, and usage to ensure "
            "compliance, quality, user privacy, and removal of harmful content."),
    "3.3": ("Access Management",
            "Operational policies and verification systems that govern who can use AI systems and for what "
            "purposes to prevent safety circumvention, deliberate misuse, and deployment in high-risk contexts."),
    "3.4": ("Staged Deployment",
            "Implementation protocols that deploy AI systems in stages, requiring safety validation before "
            "expanding user access or capabilities."),
    "3.5": ("Post-Deployment Monitoring",
            "Ongoing monitoring processes that track AI behavior, user interactions, and societal impacts "
            "post-deployment to detect misuse, emergent dangerous capabilities, and harmful effects."),
    "3.6": ("Incident Response & Recovery",
            "Protocols and technical systems that respond to security incidents, safety failures, or capability "
            "misuse to contain harm and restore safe operations."),
    "3.7": ("Incident Investigation",
            "Post-incident analyses and investigations that assess system behavior, organizational processes, and "
            "third-party contributions to identify causes and prevent recurrence."),
    "4.1": ("System Documentation",
            "Comprehensive documentation protocols that record technical specifications, intended uses, "
            "capabilities, and limitations of AI systems to enable informed evaluation and governance."),
    "4.2": ("Risk Disclosure",
            "Formal reporting protocols and notification systems that communicate risk information, mitigation "
            "plans, safety evaluations, and significant AI activities to enable external oversight and inform "
            "stakeholders."),
    "4.3": ("Incident Reporting",
            "Formal processes and protocols that document and share AI safety incidents, security breaches, "
            "near-misses, and relevant threat intelligence with appropriate stakeholders to enable coordinated "
            "responses and systemic improvements."),
    "4.4": ("Governance Disclosure",
            "Formal disclosure mechanisms that communicate governance structures, decision frameworks, and safety "
            "commitments to enhance transparency and enable external oversight of high-stakes AI decisions."),
    "4.5": ("Third-Party System Access",
            "Mechanisms granting controlled system access to vetted external parties to enable independent "
            "assessment, validation, and safety research of AI models and capabilities."),
    "4.6": ("User Rights & Recourse",
            "Frameworks and procedures that enable users to identify and understand AI system interactions, report "
            "issues, request explanations, and seek recourse or remediation when affected by AI systems."),
    "4.7": ("Training & Supportive Measures",
            "Human-centered measures for training and supporting, including help for workers, users of systems, "
            "the public, etc."),
    "5.1": ("System & Feature Restrictions",
            "Technical or product-level actions that limit, disable, or remove AI system capabilities or features "
            "to reduce harm, prevent misuse, or manage risk."),
    "5.2": ("Usage & Access Limitations",
            "Organizational or operational actions that restrict, pause, or limit the deployment or use of AI "
            "systems in specific contexts, regions, sectors, or high-risk scenarios, to manage risk."),
    "6.1": ("Court & Law Enforcement Interventions",
            "AI-incident mitigations involving courts and law-enforcement authorities that enforce legally binding "
            "accountability through litigation, criminal proceedings, or coercive legal powers."),
    "6.2": ("Regulatory Policy & Legal Mandates",
            "AI-incident mitigations imposed by regulators or governments to ensure compliance, restrict AI use, "
            "or reshape the legal and market environment."),
    "7.1": ("Financial, Economic & Compensation Remedies",
            "AI-incident mitigations that impose financial costs, economic constraints, or monetary redress to "
            "deter harm or compensate affected parties."),
    "7.2": ("Market Access & Commercial Restrictions",
            "AI-incident mitigations that limit or prohibit participation in commercial or institutional markets "
            "to reduce risk or exposure."),
    "8.1": ("Denial & Defensive-Based Actions",
            "Defensive actions or actions and statements referring to refusal of risks and harms."),
    "other": ("Open category",
              "A measure that fits none of the subcategories above."),
}

# The research plan's questions: per question, the groups to cluster separately, each with its
# selection on a passage's label, its description for the prompts, and the reference list its
# clusters are assigned to (None: no assignment).
GOVERNANCE_GROUPS = ("policies_processes", "oversight_structure", "technical_controls", "workforce_measures",
                     "third_party_controls", "transparency_accountability")
QUESTIONS = ("residual", "governance", "hedging", "adoption")


def question_groups(question: str) -> list[dict]:
    if question == "residual":
        return [{"name": "residual", "reference": None,
                 "select": lambda r: (r.get("mit_subdomains") or []) == ["other"],
                 "description": "a risk whose only MIT AI Risk Repository subdomain is `other` (it fits none of the 24)"}]
    if question == "governance":
        return [{"name": g, "reference": "mitigations",
                 "select": lambda r, g=g: g in (r.get("governance_responses") or []),
                 "description": f"governance response `{g}` (what the company does to manage AI)"}
                for g in GOVERNANCE_GROUPS]
    if question == "hedging":
        return [{"name": "hedging", "reference": "traits",
                 "select": lambda r: "hedging" in (r.get("disclosure_traits") or []),
                 "description": "disclosure trait `hedging` (uncertainty language that avoids commitment)"}]
    if question == "adoption":
        return [{"name": f, "reference": "functions" if f == "not_stated" else None,
                 "select": lambda r, f=f: "adoption" in (r.get("roles") or []) and f in (r.get("business_functions") or []),
                 "description": f"the company's own AI use, business function `{f}`"}
                for f in ("not_stated", "rd_product", "operations")]
    raise ValueError(question)


def taxonomy():
    """The US pipeline's taxonomy module (src/airo/taxonomy.py), for the trait and function definitions."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from airo import taxonomy as t
    return t


def reference_list(reference: str) -> tuple[str, str]:
    """The reference categories as prompt text, and the key that stands for "none fits"."""
    if reference == "mitigations":
        return "\n".join(f"- `{k}` {n}: {d}" for k, (n, d) in MITIGATIONS.items()), "other"
    t = taxonomy()
    if reference == "traits":
        rows = [f"- `{k}`: {d} Criteria: {'; '.join(c)}." for k, (d, c) in t.DISCLOSURE_TRAITS.items()]
        rows.append("- `none`: the sentences show none of the traits above.")
        return "\n".join(rows), "none"
    if reference == "functions":
        rows = [f"- `{k}`: {d} Criteria: {'; '.join(c)}." for k, (d, c) in t.BUSINESS_FUNCTIONS.items()
                if k != "not_stated"]
        rows.append("- `none`: the sentences name no business function, process or purpose of the AI use.")
        return "\n".join(rows), "none"
    raise ValueError(reference)

# Evalet's step 4 ("Abstract Fragments into Features"), with the evaluation criterion replaced by
# the question what the sentence states, because the passages are not rated, only described.
DESCRIBE_PROMPT = """You read sentences quoted from the annual reports (Form 10-K) of US companies. Every sentence
was selected because it states something about artificial intelligence for the company that
wrote it; the subset you see shares one label: {subset_description}

For each sentence, describe the function it serves in the disclosure: what the sentence does for
the company's statement, not what topic it mentions. The description must be:
- Distinct: clearly differentiable from other descriptions.
- Generalizable: applicable to sentences of other companies.
- Abstract: not tied to the specific details, names or figures of the sentence.
- Interpretable: clearly understandable by a reader who has not seen the sentence.
- Concise: one short sentence, at most 15 words, no company names.

Examples of the form:
- "Attributes potential bias to training data rather than to the company's own design choices"
- "Lists discrimination among several possible harms without explaining any of them"
- "Commits to a named review process for AI outputs that affect individuals"

Return exactly one JSON object with a field "functions": a list with one entry per sentence, in
the order given, each entry {{"id": <id as given>, "function": "<description>"}}. No other text.

{sentences}"""

# Evalet's base-cluster prompt, lightly edited: "statements" are function descriptions here.
NAME_PROMPT = """You are tasked with summarizing a group of related statements into a short, precise and
accurate description and name. Each statement describes the function a sentence serves in a
company's AI disclosure. The group shares the label: {subset_description}

Summarize all the statements of the group into one clear, precise sentence that says what these
sentences do in the disclosure and distinguishes the group from the contrastive groups. Then
give the group a name of at most ten words, specific but reflective of most statements.

Return exactly one JSON object: {{"summary": "<one sentence>", "name": "<at most ten words>"}}.

### Statements of the group
{statements}

### Contrastive statements from other groups
{contrast}"""

ASSIGN_PROMPT = """A group of sentences quoted from the annual reports (Form 10-K) of US companies shares the label:
{subset_description}. The group was formed by clustering what the sentences do in the disclosure.
Its name is "{name}"; its summary: {summary}

Assign the group to the reference categories below that fit most of its sentences: one or more
keys, or `{none}` if none fits. If you give `{none}` or `other`, propose in "proposed" a name of at
most eight words for the category these sentences would need; otherwise leave "proposed" empty.

### Reference categories
{reference}

### Sample sentences of the group
{quotes}

Return exactly one JSON object: {{"values": ["<key>", ...], "proposed": "<name or empty>", "reason": "<one sentence>"}}."""


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def gcs_lines(url: str):
    """Lines of a JSONL object in Cloud Storage, streamed through gcloud."""
    proc = subprocess.Popen(["gcloud", "storage", "cat", url], stdout=subprocess.PIPE)
    for line in proc.stdout:
        if line.strip():
            yield json.loads(line)
    proc.wait()


def client(project: str, location: str):
    from google import genai
    # A request without a timeout can hang forever; 120 s lets the retries in ask_json take over.
    return genai.Client(vertexai=True, project=project, location=location, http_options={"timeout": 120_000})


def ask_json(c, prompt: str, retries: int = 5) -> dict:
    """One request at temperature 0 with JSON output; retried on transient errors."""
    for attempt in range(retries + 1):
        try:
            r = c.models.generate_content(
                model=MODEL, contents=prompt,
                config={"temperature": 0, "response_mime_type": "application/json",
                        "max_output_tokens": 8192, "thinking_config": {"thinking_budget": 0}},
            )
            return json.loads(r.text)
        except Exception as e:  # noqa: BLE001 - transient errors and bad JSON are retried
            if attempt == retries:
                raise
            time.sleep(2 ** attempt)
    return {}


# --------------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------------


def fetch(args) -> None:
    """The quotes of each group, with the passage's labels and the filing's industry and month.

    One pass over the run serves all groups of a question; a passage can fall in several groups.
    """
    docs = {}
    manifest = json.loads(subprocess.run(["gcloud", "storage", "cat", f"{args.run}/documents_manifest.json"],
                                         capture_output=True, check=True).stdout)["documents"]
    for d in manifest:
        docs[d["document_id"]] = d
    keep = {}
    for r in gcs_lines(f"{args.run}/results/classified_chunks.jsonl"):
        if r.get("ai_reference") != "explicit":
            continue
        groups = [g["name"] for g in args.groups if g["select"](r)]
        if groups:
            keep[r["chunk_id"]] = (r, groups)
    rows = defaultdict(list)
    for c in gcs_lines(f"{args.run}/chunks.jsonl"):
        r, groups = keep.get(c["chunk_id"], (None, None))
        if r is None:
            continue
        d = docs.get(c["document_id"], {})
        for i, q in enumerate(r.get("evidence") or []):
            row = {
                "id": f"{c['chunk_id']}#{i}", "chunk_id": c["chunk_id"], "quote": q,
                "roles": r.get("roles"), "risk_types": r.get("risk_types"), "mit_subdomains": r.get("mit_subdomains"),
                "business_functions": r.get("business_functions"), "governance_responses": r.get("governance_responses"),
                "disclosure_traits": r.get("disclosure_traits"), "substantiveness": r.get("substantiveness"),
                "isic_division": d.get("isic_division"), "month": (d.get("filing_date") or "")[:7] or None,
                "form": d.get("form"),
            }
            for g in groups:
                rows[g].append(row)
    for g in args.groups:
        write_jsonl(g["work"] / "quotes.jsonl", rows[g["name"]])
        passages = sum(1 for _, gs in keep.values() if g["name"] in gs)
        print(f"fetch: {g['name']}: {passages} passages, {len(rows[g['name']])} quotes -> {g['work'] / 'quotes.jsonl'}")


def describe(args) -> None:
    """One function description per quote, 40 quotes per request."""
    quotes = read_jsonl(args.work / "quotes.jsonl")
    out = args.work / "functions.jsonl"
    done = {r["id"] for r in read_jsonl(out)} if out.exists() else set()
    todo = [q for q in quotes if q["id"] not in done]
    c = client(args.project, args.location)
    n = 0
    with open(out, "a", encoding="utf-8") as fh:
        for i in range(0, len(todo), BATCH):
            batch = todo[i:i + BATCH]
            sentences = "\n".join(f"{k + 1}. {q['quote']}" for k, q in enumerate(batch))
            try:
                answer = ask_json(c, DESCRIBE_PROMPT.format(subset_description=args.subset_description, sentences=sentences))
            except Exception as e:  # noqa: BLE001 - the batch is left undone; a rerun resumes it
                print(f"describe: batch {i // BATCH} skipped after retries: {type(e).__name__}: {e}", file=sys.stderr)
                continue
            by_id = {}
            for f in answer.get("functions") or []:
                try:
                    by_id[int(f["id"])] = str(f["function"]).strip()
                except (KeyError, ValueError, TypeError):
                    continue
            for k, q in enumerate(batch):
                fn = by_id.get(k + 1)
                if fn:
                    fh.write(json.dumps({**q, "function": fn}, ensure_ascii=False) + "\n")
                    n += 1
            fh.flush()
            print(f"describe: {min(i + BATCH, len(todo))}/{len(todo)}", file=sys.stderr)
    print(f"describe: {n} functions written, {len(todo) - n} quotes without one -> {out}")


def embed(args) -> None:
    rows = read_jsonl(args.work / "functions.jsonl")
    c = client(args.project, args.location)
    vectors = []
    for i in range(0, len(rows), 100):
        r = c.models.embed_content(model=EMBEDDING_MODEL, contents=[x["function"] for x in rows[i:i + 100]])
        vectors += [e.values for e in r.embeddings]
        print(f"embed: {min(i + 100, len(rows))}/{len(rows)}", file=sys.stderr)
    np.save(args.work / "embeddings.npy", np.array(vectors, dtype=np.float32))
    print(f"embed: {len(vectors)} vectors of {len(vectors[0])} dims -> {args.work / 'embeddings.npy'}")


def cluster(args) -> None:
    """UMAP to ten dimensions (cosine), HDBSCAN there; a second UMAP to two dimensions for the plot.

    Density clustering straight on 3,072-dimensional embeddings leaves most points in no
    cluster; Evalet clusters on a 2-D projection, which over-merges. Ten dimensions keep the
    neighbourhoods and give HDBSCAN something to work with.
    """
    from sklearn.cluster import HDBSCAN
    from sklearn.preprocessing import normalize
    import umap

    rows = read_jsonl(args.work / "functions.jsonl")
    x = normalize(np.load(args.work / "embeddings.npy"))
    min_size = args.min_cluster_size or max(5, len(rows) // 100)
    if len(rows) >= 50:
        x10 = umap.UMAP(n_components=10, n_neighbors=15, min_dist=0.0, random_state=42, metric="cosine").fit_transform(x)
        xy = umap.UMAP(n_components=2, random_state=42, metric="cosine").fit_transform(x)
    else:  # too few points for UMAP's neighbourhood graph: principal components instead
        from sklearn.decomposition import PCA
        x10 = PCA(n_components=min(10, len(rows) - 1), random_state=42).fit_transform(x)
        xy = PCA(n_components=2, random_state=42).fit_transform(x)
    labels = HDBSCAN(min_cluster_size=min(min_size, len(rows)), min_samples=min(5, len(rows))).fit_predict(x10)
    for r, lab, p in zip(rows, labels, xy):
        r["cluster"] = int(lab)
        r["x"], r["y"] = float(p[0]), float(p[1])
    write_jsonl(args.work / "clusters.jsonl", rows)
    sizes = Counter(int(l) for l in labels)
    noise = sizes.pop(-1, 0)
    print(f"cluster: {len(sizes)} clusters (min size {min_size}), {noise} of {len(rows)} in no cluster "
          f"-> {args.work / 'clusters.jsonl'}")


def name(args) -> None:
    rows = read_jsonl(args.work / "clusters.jsonl")
    by_cluster = defaultdict(list)
    for r in rows:
        if r["cluster"] >= 0:
            by_cluster[r["cluster"]].append(r["function"])
    rng = np.random.default_rng(0)
    c = client(args.project, args.location)
    names = []
    for k in sorted(by_cluster):
        members = by_cluster[k]
        sample = list(rng.choice(members, size=min(40, len(members)), replace=False))
        others = [f for j, fs in by_cluster.items() if j != k for f in fs]
        contrast = list(rng.choice(others, size=min(20, len(others)), replace=False)) if others else []
        answer = ask_json(c, NAME_PROMPT.format(
            subset_description=args.subset_description,
            statements="\n".join(f"- {s}" for s in sample),
            contrast="\n".join(f"- {s}" for s in contrast) or "(none)",
        ))
        names.append({"cluster": k, "size": len(members), "name": answer.get("name"), "summary": answer.get("summary")})
        print(f"name: cluster {k} ({len(members)}): {answer.get('name')}", file=sys.stderr)
    write_jsonl(args.work / "names.jsonl", names)
    print(f"name: {len(names)} clusters named -> {args.work / 'names.jsonl'}")


def assign(args) -> None:
    """Per cluster, the reference categories its sentences fit, from its name, summary and 15 quotes."""
    if not args.reference:
        return
    rows = read_jsonl(args.work / "clusters.jsonl")
    by_cluster = defaultdict(list)
    for r in rows:
        if r["cluster"] >= 0:
            by_cluster[r["cluster"]].append(r["quote"])
    reference, none = reference_list(args.reference)
    rng = np.random.default_rng(0)
    c = client(args.project, args.location)
    out = []
    for n in read_jsonl(args.work / "names.jsonl"):
        quotes = by_cluster[n["cluster"]]
        sample = list(rng.choice(quotes, size=min(15, len(quotes)), replace=False))
        answer = ask_json(c, ASSIGN_PROMPT.format(
            subset_description=args.subset_description, name=n["name"], summary=n["summary"], none=none,
            reference=reference, quotes="\n".join(f"- {q}" for q in sample)))
        out.append({"cluster": n["cluster"], "values": answer.get("values") or [],
                    "proposed": answer.get("proposed") or "", "reason": answer.get("reason") or ""})
        print(f"assign: cluster {n['cluster']}: {out[-1]['values']} {out[-1]['proposed']}", file=sys.stderr)
    write_jsonl(args.work / "assignments.jsonl", out)
    print(f"assign: {len(out)} clusters against {args.reference} -> {args.work / 'assignments.jsonl'}")


def report(args) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = read_jsonl(args.work / "clusters.jsonl")
    names = {n["cluster"]: n for n in read_jsonl(args.work / "names.jsonl")}
    out = args.results
    out.mkdir(parents=True, exist_ok=True)
    total = len(rows)
    by_cluster = defaultdict(list)
    for r in rows:
        by_cluster[r["cluster"]].append(r)
    noise = len(by_cluster.pop(-1, []))

    assigned = ({a["cluster"]: a for a in read_jsonl(args.work / "assignments.jsonl")}
                if (args.work / "assignments.jsonl").exists() else {})

    # Cluster table: name, size, share, industries, months, risk types, assigned reference
    # categories, example functions (model text, no quotes).
    table = []
    for k, members in sorted(by_cluster.items(), key=lambda kv: -len(kv[1])):
        divisions = Counter(m["isic_division"] or "?" for m in members).most_common(3)
        passages = len({m["chunk_id"] for m in members})
        risk_types = Counter(t for m in members for t in m.get("risk_types") or []).most_common(3)
        table.append({
            "cluster": k, "name": names[k]["name"], "summary": names[k]["summary"],
            "quotes": len(members), "passages": passages, "share": round(len(members) / total, 3),
            "top_isic_divisions": [f"{d} ({n})" for d, n in divisions],
            "top_risk_types": [f"{t} ({n})" for t, n in risk_types],
            "months": dict(sorted(Counter(m["month"] for m in members).items())),
            "assigned": assigned.get(k, {}).get("values", []), "proposed": assigned.get(k, {}).get("proposed", ""),
            "example_functions": [m["function"] for m in members[:3]],
        })
    write_jsonl(out / "clusters.jsonl", table)
    with_risk = any(t["top_risk_types"] for t in table)
    months = sorted({m for t in table for m in t["months"] if m})
    with open(out / "clusters.md", "w", encoding="utf-8") as fh:
        fh.write(f"# Functional fragmentation: {args.subset_description}\n\n")
        fh.write(f"{total} quotes from {len({r['chunk_id'] for r in rows})} passages; {len(table)} clusters; "
                 f"{noise} quotes ({noise / max(total, 1):.0%}) in no cluster.\n\n")
        cols = ["#", "Cluster", "Quotes", "Share", "Top ISIC divisions"]
        cols += ["Top risk types"] if with_risk else []
        cols += ["Assigned (model)", "Proposed category"] if assigned else []
        cols += ["Summary"]
        fh.write("| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n")
        for t in table:
            cells = [str(t["cluster"]), t["name"], str(t["quotes"]), f"{t['share']:.0%}", ", ".join(t["top_isic_divisions"])]
            cells += [", ".join(t["top_risk_types"])] if with_risk else []
            cells += [", ".join(f"`{v}`" for v in t["assigned"]), t["proposed"]] if assigned else []
            cells += [t["summary"]]
            fh.write("| " + " | ".join(cells) + " |\n")
        if months:
            fh.write("\n## Quotes per filing month\n\nShare of each cluster's quotes by the month the filing was "
                     "submitted.\n\n| # | Cluster | " + " | ".join(months) + " |\n|---|---|" + "---|" * len(months) + "\n")
            for t in table:
                fh.write(f"| {t['cluster']} | {t['name']} | "
                         + " | ".join(f"{t['months'].get(m, 0) / t['quotes']:.0%}" for m in months) + " |\n")

    # Example quotes per cluster: filing text, so in work/ (git-ignored), not in results/.
    rng = np.random.default_rng(0)
    with open(args.work / "examples.md", "w", encoding="utf-8") as fh:
        fh.write(f"# Example quotes: {args.subset_description}\n\n")
        for t in table:
            members = by_cluster[t["cluster"]]
            fh.write(f"## {t['cluster']}: {t['name']} ({t['quotes']} quotes)\n\n")
            for i in rng.choice(len(members), size=min(5, len(members)), replace=False):
                m = members[i]
                fh.write(f"- \"{m['quote']}\" (ISIC {m['isic_division']}, {m['month']}; function: {m['function']})\n")
            fh.write("\n")

    # Plot 1: the 2-D map, one colour per cluster, the ten largest clusters labelled. Labels are
    # wrapped, anchored towards the centre of the plot and moved back inside the frame if they overflow.
    import textwrap
    fig, ax = plt.subplots(figsize=(14, 10))
    cmap = plt.get_cmap("tab20")
    noise_rows = [r for r in rows if r["cluster"] < 0]
    ax.scatter([r["x"] for r in noise_rows], [r["y"] for r in noise_rows], s=6, c="#c8c8c8", label=f"no cluster ({noise})")
    xs, ys = [r["x"] for r in rows], [r["y"] for r in rows]
    mid_x, mid_y = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    labels = []
    for i, t in enumerate(table):
        m = by_cluster[t["cluster"]]
        ax.scatter([r["x"] for r in m], [r["y"] for r in m], s=8, color=cmap(i % 20))
        if i < 10:
            cx, cy = np.mean([r["x"] for r in m]), np.mean([r["y"] for r in m])
            labels.append(ax.text(
                cx, cy, textwrap.fill(f"{t['cluster']}: {t['name']}", 26), fontsize=16,
                ha="left" if cx < mid_x else "right", va="bottom" if cy < mid_y else "top",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=cmap(i % 20), alpha=0.9)))
    ax.set_title(f"Functions of {total} quotes, {args.subset_description}\n{len(table)} HDBSCAN clusters on function embeddings, "
                 f"{'UMAP' if total >= 50 else 'PCA'} for display",
                 fontsize=17)
    ax.set_xticks([]); ax.set_yticks([])
    fig.tight_layout()
    fig.canvas.draw()
    # Place labels one by one, largest cluster first: each takes the nearest offset from its
    # cluster centre (in pixels) at which its box lies inside the frame and clear of every label
    # placed before it. The box is the text extent plus the bbox padding and a small gap.
    renderer = fig.canvas.get_renderer()
    frame = ax.get_window_extent(renderer)
    pad = 0.3 * 16 * fig.dpi / 72 + 4
    step = 6
    offsets = sorted(((dx, dy) for dx in range(-60, 61, step) for dy in range(-600, 601, step)),
                     key=lambda o: o[0] ** 2 + o[1] ** 2)
    placed = []
    for label in labels:
        anchor = ax.transData.transform(label.get_position())
        for dx, dy in offsets:
            label.set_position(ax.transData.inverted().transform((anchor[0] + dx, anchor[1] + dy)))
            b = label.get_window_extent(renderer).expanded(1, 1)
            x0, y0, x1, y1 = b.x0 - pad, b.y0 - pad, b.x1 + pad, b.y1 + pad
            if x0 < frame.x0 or x1 > frame.x1 or y0 < frame.y0 or y1 > frame.y1:
                continue
            if any(x0 < p[2] and p[0] < x1 and y0 < p[3] and p[1] < y1 for p in placed):
                continue
            placed.append((x0, y0, x1, y1))
            break
    fig.savefig(out / "map.png", dpi=150); plt.close(fig)

    # Plot 2: cluster sizes.
    fig, ax = plt.subplots(figsize=(10, max(4, 0.35 * len(table) + 1)))
    ax.barh([f"{t['cluster']}: {t['name'][:60]}" for t in table][::-1], [t["quotes"] for t in table][::-1], color="#4c72b0")
    ax.set_xlabel("quotes"); ax.set_title(f"Cluster sizes\n{args.subset_description}", fontsize=10)
    fig.tight_layout(); fig.savefig(out / "sizes.png", dpi=150); plt.close(fig)
    print(f"report: {len(table)} clusters, {noise} unclustered -> {out}/clusters.md, map.png, sizes.png")


STEPS = {"fetch": fetch, "describe": describe, "embed": embed, "cluster": cluster, "name": name, "assign": assign,
         "report": report}


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("step", choices=[*STEPS, "all"])
    p.add_argument("--run", required=True, help="gs://bucket/run folder with chunks.jsonl, documents_manifest.json, results/")
    p.add_argument("--question", choices=QUESTIONS, help="a question of the research plan (see the module docstring)")
    p.add_argument("--group", help="with --question: run only this group")
    p.add_argument("--subdomain", help="keep passages with this MIT subdomain value")
    p.add_argument("--role", help="keep passages with this role")
    p.add_argument("--trait", help="keep passages with this disclosure trait")
    p.add_argument("--project", help="Google Cloud project for Vertex AI (describe, embed, name, assign)")
    p.add_argument("--location", default="us-central1")
    p.add_argument("--min-cluster-size", type=int, default=None, help="HDBSCAN minimum cluster size (default: quotes/100, at least 5)")
    p.add_argument("--work", type=Path, default=None, help="working directory (default: work/<subset>; not with --question)")
    args = p.parse_args(argv)
    if args.question:
        groups = question_groups(args.question)
        if args.group:
            groups = [g for g in groups if g["name"] == args.group] or p.error(f"no group {args.group}")
        for g in groups:
            g["work"] = Path("work") / args.question / g["name"]
            g["results"] = Path("results") / args.question / g["name"]
    else:
        subset = args.subdomain or args.role or args.trait or "all"
        description = (
            f"MIT AI Risk Repository subdomain `{args.subdomain}`" if args.subdomain
            else f"role `{args.role}`" if args.role else f"disclosure trait `{args.trait}`" if args.trait
            else "all passages about AI"
        )
        work = args.work or Path("work") / re.sub(r"[^a-z0-9_]+", "_", subset.lower())
        groups = [{
            "name": subset, "description": description, "reference": None, "work": work,
            "results": Path("results") / work.name,
            "select": lambda r: ((not args.subdomain or args.subdomain in (r.get("mit_subdomains") or []))
                                 and (not args.role or args.role in (r.get("roles") or []))
                                 and (not args.trait or args.trait in (r.get("disclosure_traits") or []))),
        }]
    for g in groups:
        g["work"].mkdir(parents=True, exist_ok=True)
    steps = list(STEPS) if args.step == "all" else [args.step]
    for step in steps:
        if step in ("describe", "embed", "name", "assign") and not args.project:
            p.error(f"{step} needs --project")
    if "fetch" in steps:
        args.groups = groups
        fetch(args)
    for g in groups:
        quotes = g["work"] / "quotes.jsonl"
        if quotes.exists() and not quotes.stat().st_size:
            print(f"{g['name']}: no quotes, nothing to cluster")
            continue
        args.work, args.results = g["work"], g["results"]
        args.subset_description, args.reference = g["description"], g["reference"]
        for step in steps:
            if step != "fetch":
                STEPS[step](args)


if __name__ == "__main__":
    main()
