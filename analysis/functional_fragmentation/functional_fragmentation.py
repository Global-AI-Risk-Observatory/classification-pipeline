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
    report    cluster table and plots                                           -> results/<subset>/

    python functional_fragmentation.py all --run gs://<bucket>/<run> --subdomain <value> \
        --project <gcp project> [--location us-central1]

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
    return genai.Client(vertexai=True, project=project, location=location)


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
    """The quotes of the subset, with the passage's labels and the filing's industry and month."""
    docs = {}
    manifest = json.loads(subprocess.run(["gcloud", "storage", "cat", f"{args.run}/documents_manifest.json"],
                                         capture_output=True, check=True).stdout)["documents"]
    for d in manifest:
        docs[d["document_id"]] = d
    keep = {}
    for r in gcs_lines(f"{args.run}/results/classified_chunks.jsonl"):
        if r.get("ai_reference") != "explicit":
            continue
        if args.subdomain and args.subdomain not in (r.get("mit_subdomains") or []):
            continue
        if args.role and args.role not in (r.get("roles") or []):
            continue
        if args.trait and args.trait not in (r.get("disclosure_traits") or []):
            continue
        keep[r["chunk_id"]] = r
    rows = []
    for c in gcs_lines(f"{args.run}/chunks.jsonl"):
        r = keep.get(c["chunk_id"])
        if r is None:
            continue
        d = docs.get(c["document_id"], {})
        for i, q in enumerate(r.get("evidence") or []):
            rows.append({
                "id": f"{c['chunk_id']}#{i}", "chunk_id": c["chunk_id"], "quote": q,
                "roles": r.get("roles"), "risk_types": r.get("risk_types"), "mit_subdomains": r.get("mit_subdomains"),
                "disclosure_traits": r.get("disclosure_traits"), "substantiveness": r.get("substantiveness"),
                "isic_division": d.get("isic_division"), "month": (d.get("filing_date") or "")[:7] or None,
                "form": d.get("form"),
            })
    write_jsonl(args.work / "quotes.jsonl", rows)
    print(f"fetch: {len(keep)} passages, {len(rows)} quotes -> {args.work / 'quotes.jsonl'}")


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
            answer = ask_json(c, DESCRIBE_PROMPT.format(subset_description=args.subset_description, sentences=sentences))
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
    x10 = umap.UMAP(n_components=10, n_neighbors=15, min_dist=0.0, random_state=42, metric="cosine").fit_transform(x)
    labels = HDBSCAN(min_cluster_size=min_size, min_samples=5).fit_predict(x10)
    xy = umap.UMAP(n_components=2, random_state=42, metric="cosine").fit_transform(x)
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

    # Cluster table: name, size, share, industries, months, example functions (model text, no quotes).
    table = []
    for k, members in sorted(by_cluster.items(), key=lambda kv: -len(kv[1])):
        divisions = Counter(m["isic_division"] or "?" for m in members).most_common(3)
        passages = len({m["chunk_id"] for m in members})
        table.append({
            "cluster": k, "name": names[k]["name"], "summary": names[k]["summary"],
            "quotes": len(members), "passages": passages, "share": round(len(members) / total, 3),
            "top_isic_divisions": [f"{d} ({n})" for d, n in divisions],
            "months": dict(sorted(Counter(m["month"] for m in members).items())),
            "example_functions": [m["function"] for m in members[:3]],
        })
    write_jsonl(out / "clusters.jsonl", table)
    with open(out / "clusters.md", "w", encoding="utf-8") as fh:
        fh.write(f"# Functional fragmentation: {args.subset_description}\n\n")
        fh.write(f"{total} quotes from {len({r['chunk_id'] for r in rows})} passages; {len(table)} clusters; "
                 f"{noise} quotes ({noise / total:.0%}) in no cluster.\n\n")
        fh.write("| # | Cluster | Quotes | Share | Top ISIC divisions | Summary |\n|---|---|---|---|---|---|\n")
        for t in table:
            fh.write(f"| {t['cluster']} | {t['name']} | {t['quotes']} | {t['share']:.0%} | "
                     f"{', '.join(t['top_isic_divisions'])} | {t['summary']} |\n")

    # Plot 1: the 2-D map, one colour per cluster, the ten largest clusters labelled.
    fig, ax = plt.subplots(figsize=(11, 8))
    cmap = plt.get_cmap("tab20")
    noise_rows = [r for r in rows if r["cluster"] < 0]
    ax.scatter([r["x"] for r in noise_rows], [r["y"] for r in noise_rows], s=6, c="#c8c8c8", label=f"no cluster ({noise})")
    for i, t in enumerate(table):
        m = by_cluster[t["cluster"]]
        ax.scatter([r["x"] for r in m], [r["y"] for r in m], s=8, color=cmap(i % 20))
        if i < 10:
            cx, cy = np.mean([r["x"] for r in m]), np.mean([r["y"] for r in m])
            ax.annotate(f"{t['cluster']}: {t['name']}", (cx, cy), fontsize=8,
                        bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=cmap(i % 20), alpha=0.9))
    ax.set_title(f"Functions of {total} quotes, {args.subset_description}\n{len(table)} HDBSCAN clusters on function embeddings, UMAP for display")
    ax.set_xticks([]); ax.set_yticks([])
    fig.tight_layout(); fig.savefig(out / "map.png", dpi=150); plt.close(fig)

    # Plot 2: cluster sizes.
    fig, ax = plt.subplots(figsize=(10, max(4, 0.35 * len(table) + 1)))
    ax.barh([f"{t['cluster']}: {t['name'][:60]}" for t in table][::-1], [t["quotes"] for t in table][::-1], color="#4c72b0")
    ax.set_xlabel("quotes"); ax.set_title(f"Cluster sizes\n{args.subset_description}", fontsize=10)
    fig.tight_layout(); fig.savefig(out / "sizes.png", dpi=150); plt.close(fig)
    print(f"report: {len(table)} clusters, {noise} unclustered -> {out}/clusters.md, map.png, sizes.png")


STEPS = {"fetch": fetch, "describe": describe, "embed": embed, "cluster": cluster, "name": name, "report": report}


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("step", choices=[*STEPS, "all"])
    p.add_argument("--run", required=True, help="gs://bucket/run folder with chunks.jsonl, documents_manifest.json, results/")
    p.add_argument("--subdomain", help="keep passages with this MIT subdomain value")
    p.add_argument("--role", help="keep passages with this role")
    p.add_argument("--trait", help="keep passages with this disclosure trait")
    p.add_argument("--project", help="Google Cloud project for Vertex AI (describe, embed, name)")
    p.add_argument("--location", default="us-central1")
    p.add_argument("--min-cluster-size", type=int, default=None, help="HDBSCAN minimum cluster size (default: quotes/60, at least 5)")
    p.add_argument("--work", type=Path, default=None, help="working directory (default: work/<subset>)")
    args = p.parse_args(argv)
    subset = args.subdomain or args.role or args.trait or "all"
    args.subset_description = (
        f"MIT AI Risk Repository subdomain `{args.subdomain}`" if args.subdomain
        else f"role `{args.role}`" if args.role else f"disclosure trait `{args.trait}`" if args.trait
        else "all passages about AI"
    )
    args.work = args.work or Path("work") / re.sub(r"[^a-z0-9_]+", "_", subset.lower())
    args.results = Path("results") / args.work.name
    args.work.mkdir(parents=True, exist_ok=True)
    for step in (list(STEPS) if args.step == "all" else [args.step]):
        if step in ("describe", "embed", "name") and not args.project:
            p.error(f"{step} needs --project")
        STEPS[step](args)


if __name__ == "__main__":
    main()
