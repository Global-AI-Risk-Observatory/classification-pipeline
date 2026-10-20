"""Automated coder, batch mode: the requests of `airo.coders.gemini` through Vertex AI batch prediction.

    python -m airo.coders.gemini_batch submit --tasks data/tasks.jsonl --codebook data/codebook.md \\
        --model gemini-2.5-flash --project <gcp-project> --location us-central1 \\
        --dest gs://<bucket>/<run>/batch --job-file data/labels_in/gemini.batch.json [--thinking-budget 0]
    ... wait: Vertex AI promises the output within 24 hours, usually much sooner ...
    python -m airo.coders.gemini_batch collect --job-file data/labels_in/gemini.batch.json \\
        --tasks data/tasks.jsonl --out data/labels_in/gemini.jsonl --project <gcp-project> \\
        [--price-input X --price-output Y]

`submit` renders the same requests the synchronous coder sends (`build_batch_prompt`: the
codebook once and `--batch-size` tasks per request, JSON mode with the `Labels` schema,
temperature 0), writes them as one JSONL file to `--dest` (a Cloud Storage location: batch
prediction reads its input from there and writes its output next to it) and creates the batch
job. The job's name and the locations go to `--job-file`.

`collect` reads the job's state. While the job runs it prints the state and exits with 2.
When the job is done it reads the prediction files, matches the labels to the tasks by
`passage_id` and runs every label through the pipeline's acceptance check, exactly as the
synchronous coder does. Nothing is asked again here: a label that is rejected or missing,
and every task of a request that failed, goes to `<out>.deferred.jsonl`, the input of
`airo.coders.gemini --repairs-from` (synchronous) or of `submit --repairs-from` (a second
batch job). `<out>` and `<out>.run.json` have the same form as the synchronous coder's, with
`mode` "batch" and the job's name added, so `python -m airo accept <out> --coder gemini` and
the cost figures work unchanged.

Why batch: Vertex AI bills batch prediction at half the online price and has no request
rate limit, so a whole run goes out at once; the trade is latency (minutes to hours) and
that the requests must pass through a bucket. Prompt, codebook, schema, grouping and model
are the same as online, so the labels are comparable with the online runs.

The request lines use the REST form of a `GenerateContentRequest`: `contents`,
`generationConfig` with `responseSchema` as an OpenAPI schema (`vertex_schema` derives it
from the pydantic `Labels` class: `$ref`s inlined, `Optional` as `nullable`, types in upper
case). Each output line holds the `request` again, its `response` (a `GenerateContentResponse`)
or a `status` with the error, so a failed request is recognised and its tasks are deferred.
Written against the documented interface (`client.batches.create(model=, src=, config={"dest": ...})`,
`client.batches.get(name=)`, `BatchJob.state`) and tested with fakes only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from .. import fetch
from . import gemini
from .gemini import BATCH_SIZE, CODER, MAX_OUTPUT_TOKENS, Labels

REQUESTS = "requests.jsonl"
OUTPUT = "output"
DONE_STATES = {"JOB_STATE_SUCCEEDED", "JOB_STATE_PARTIALLY_SUCCEEDED"}
FAILED_STATES = {"JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"}
_PASSAGE_ID = re.compile(r"^passage_id: (\S+)$", re.MULTILINE)


# --------------------------------------------------------------------------
# Requests
# --------------------------------------------------------------------------


def vertex_schema(model: type[BaseModel] | dict) -> dict:
    """The OpenAPI schema Vertex AI takes as `responseSchema`, from a pydantic model.

    pydantic's JSON schema is rewritten: `$ref`s are inlined, `anyOf [X, null]` becomes X with
    `nullable`, a `const` becomes a one-value `enum`, types are upper case, and `title` and
    `default` are dropped. Supported keys only: type, enum, items, properties, required,
    nullable, description, minItems, maxItems.
    """
    schema = model if isinstance(model, dict) else model.model_json_schema()
    defs = schema.get("$defs", {})

    def convert(node: dict) -> dict:
        if "$ref" in node:
            node = {**defs[node["$ref"].rsplit("/", 1)[-1]], **{k: v for k, v in node.items() if k != "$ref"}}
        if "anyOf" in node:
            options = [o for o in node["anyOf"] if o.get("type") != "null"]
            if len(options) != 1:
                raise ValueError(f"cannot express anyOf with {len(options)} options in a Vertex schema")
            out = convert({**options[0], **{k: v for k, v in node.items() if k != "anyOf"}})
            if len(options) < len(node["anyOf"]):
                out["nullable"] = True
            return out
        out: dict[str, Any] = {}
        if "const" in node:
            out["type"], out["enum"] = "STRING", [node["const"]]
        for key in ("enum", "description", "minItems", "maxItems"):
            if key in node:
                out[key] = node[key]
        if "type" in node:
            out["type"] = node["type"].upper()
        if "items" in node:
            out["items"] = convert(node["items"])
        if "properties" in node:
            out["properties"] = {k: convert(v) for k, v in node["properties"].items()}
            out["required"] = list(node.get("required", []))
        return out

    return convert({k: v for k, v in schema.items() if k != "$defs"})


def generation_config(thinking_budget: Optional[int], max_output_tokens: int, schema: dict) -> dict:
    """The REST form of `gemini.request_config`: the same settings, camel-cased, schema inlined."""
    config: dict[str, Any] = {
        "temperature": 0,
        "maxOutputTokens": max_output_tokens,
        "responseMimeType": "application/json",
        "responseSchema": schema,
    }
    if thinking_budget is not None:
        config["thinkingConfig"] = {"thinkingBudget": thinking_budget}
    return config


def build_requests(tasks: list[dict], codebook: str, *, batch_size: int = BATCH_SIZE,
                   thinking_budget: Optional[int] = None, max_output_tokens: int = MAX_OUTPUT_TOKENS) -> list[dict]:
    """One request line per `batch_size` tasks, in task order: the input of a batch prediction job."""
    schema = vertex_schema(Labels)
    config = generation_config(thinking_budget, max(max_output_tokens, gemini._TOKENS_PER_LABEL * batch_size), schema)
    return [
        {"request": {"contents": [{"role": "user", "parts": [{"text": gemini.build_batch_prompt(codebook, batch)}]}],
                     "generationConfig": config}}
        for batch in (tasks[i : i + batch_size] for i in range(0, len(tasks), max(1, batch_size)))
    ]


def submit(tasks: list[dict], codebook: str, *, model: str, client, store, batch_size: int = BATCH_SIZE,
           thinking_budget: Optional[int] = None, max_output_tokens: int = MAX_OUTPUT_TOKENS) -> dict:
    """Write the requests to `store` and create the batch job. Returns the job record for `collect`.

    `store` is where the requests go (`fetch.store(dest)`); the output is written under
    `<dest>/output/`. A location that already holds a `requests.jsonl` is refused, so a job is
    never submitted twice from the same files.
    """
    lines = build_requests(tasks, codebook, batch_size=batch_size, thinking_budget=thinking_budget,
                           max_output_tokens=max_output_tokens)
    data = "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines).encode("utf-8")
    if not store.create(REQUESTS, data):
        raise SystemExit(f"{store}/{REQUESTS} exists already: a batch job was submitted from there; use a new --dest")
    src, dest = f"{store}/{REQUESTS}", f"{store}/{OUTPUT}"
    job = client.batches.create(model=model, src=src, config={"dest": dest})
    return {
        "coder": CODER, "mode": "batch", "job": job.name, "state": _state(job), "model": model,
        "src": src, "dest": dest, "tasks": len(tasks), "requests": len(lines), "batch_size": batch_size,
        "thinking_budget": thinking_budget, "submitted": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


def _state(job) -> str:
    state = getattr(job, "state", None)
    return getattr(state, "value", None) or getattr(state, "name", None) or str(state)


def _text(response: dict) -> Optional[str]:
    try:
        parts = response["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        return None
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict)) or None


def _usage(response: dict) -> dict:
    u = (response or {}).get("usageMetadata") or {}
    return {"input_tokens": u.get("promptTokenCount") or 0, "output_tokens": u.get("candidatesTokenCount") or 0,
            "thinking_tokens": u.get("thoughtsTokenCount") or 0}


def _request_ids(request: dict) -> list[str]:
    text = "\n".join(p.get("text", "") for c in (request or {}).get("contents") or [] for p in c.get("parts") or [])
    return _PASSAGE_ID.findall(text)


def read_output(lines: list[str], tasks: list[dict], *, model: str) -> list[dict]:
    """The results of a finished job, one per task in task order, in the synchronous coder's form.

    Every label is matched by `passage_id` and checked with `gemini._check`. Rejected labels,
    labels missing from an answer, the tasks of a failed request and tasks absent from the
    output are deferred (`deferred` True, `answer` the rejected text or None); nothing is asked
    again here. The tokens of a request are booked on its first task.
    """
    by_task = {t["passage_id"]: t for t in tasks}
    results: dict[str, dict] = {}

    def blank(pid: str) -> dict:
        return {"passage_id": pid, "label": None, "error": None,
                "usage": {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0},
                "model": model, "latency_s": 0.0, "attempts": 1, "repairs": 0}

    for raw in lines:
        if not raw.strip():
            continue
        line = json.loads(raw)
        ids = [pid for pid in _request_ids(line.get("request") or {}) if pid in by_task]
        response, status = line.get("response"), line.get("status")
        text = _text(response) if isinstance(response, dict) else None
        failure = None
        if not isinstance(response, dict) or text is None:
            failure = f"batch request failed: {status or 'no response'}"
        by_id: dict[str, dict] = {}
        if text is not None:
            try:
                parsed = json.loads(text)
                for label in parsed.get("labels") or [] if isinstance(parsed, dict) else []:
                    if isinstance(label, dict) and isinstance(label.get("passage_id"), str):
                        by_id.setdefault(label["passage_id"], label)
            except json.JSONDecodeError as e:
                failure = f"batch answer is not JSON: {e}"
        for n, pid in enumerate(ids):
            result = blank(pid)
            if failure:
                result.update(error=failure, deferred=True, answer=None)
            elif pid not in by_id:
                result.update(error="no label in the batch answer", deferred=True, answer=None)
            else:
                answer = json.dumps(by_id[pid], ensure_ascii=False)
                label, error = gemini._check(answer, by_task[pid])
                result["label"] = label
                if error is not None:
                    result.update(error=error, deferred=True, answer=answer)
            if n == 0 and isinstance(response, dict):
                result["usage"] = _usage(response)
            results.setdefault(pid, result)
    out = []
    for t in tasks:
        r = results.get(t["passage_id"])
        if r is None:
            r = {**blank(t["passage_id"]), "error": "not in the batch output", "deferred": True, "answer": None, "attempts": 0}
        out.append(r)
    return out


def output_lines(store, prefix: str = OUTPUT) -> list[str]:
    """Every line of every `.jsonl` file the job wrote under `prefix` (Vertex AI writes them into a
    subfolder named after the job, so the search is recursive)."""
    names = sorted(n for n in store.files(prefix) if n.endswith(".jsonl"))
    lines: list[str] = []
    for name in names:
        data = store.read(name)
        if data:
            lines += data.decode("utf-8").splitlines()
    return lines


def collect(record: dict, tasks: list[dict], *, client, store) -> tuple[str, Optional[list[dict]]]:
    """The job's state and, once it is done, the results (see `read_output`); else (state, None)."""
    job = client.batches.get(name=record["job"])
    state = _state(job)
    if state not in DONE_STATES:
        return state, None
    lines = output_lines(store)
    if not lines:
        raise SystemExit(f"job {record['job']} is {state} but {store}/{OUTPUT} holds no .jsonl output")
    return state, read_output(lines, tasks, model=record["model"])


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m airo.coders.gemini_batch",
                                description="Label tasks.jsonl with Gemini through Vertex AI batch prediction.")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("submit", help="write the requests to --dest and create the batch job")
    s.add_argument("--tasks", type=Path, required=True, help="tasks.jsonl from `airo tasks`")
    s.add_argument("--codebook", type=Path, required=True, help="codebook.md from `airo tasks`")
    s.add_argument("--model", required=True, help="Gemini model name, e.g. gemini-2.5-flash")
    s.add_argument("--project", required=True, help="Google Cloud project id")
    s.add_argument("--location", default="us-central1", help="Vertex AI region (default us-central1)")
    s.add_argument("--dest", required=True, help="gs://bucket/prefix for requests.jsonl and the job's output/ (new per job)")
    s.add_argument("--job-file", type=Path, required=True, help="where to write the job record that `collect` reads")
    s.add_argument("--batch-size", type=int, default=BATCH_SIZE, help=f"tasks per request (default {BATCH_SIZE})")
    s.add_argument("--thinking-budget", type=int, default=None, help="thinking token budget; 0 = off")
    s.add_argument("--max-output-tokens", type=int, default=MAX_OUTPUT_TOKENS, help=f"default {MAX_OUTPUT_TOKENS}")
    s.add_argument("--limit", type=int, default=None, help="submit only the first N tasks")
    s.add_argument("--repairs-from", type=Path, default=None,
                   help="submit only the passages of this <out>.deferred.jsonl, in a new grouping")
    c = sub.add_parser("collect", help="read the job's output, check the labels, write --out")
    c.add_argument("--job-file", type=Path, required=True, help="the record `submit` wrote")
    c.add_argument("--tasks", type=Path, required=True, help="the tasks.jsonl the job was submitted from")
    c.add_argument("--out", type=Path, required=True, help="labels JSONL to write; <out>.run.json and <out>.deferred.jsonl beside it")
    c.add_argument("--project", required=True, help="Google Cloud project id")
    c.add_argument("--location", default="us-central1", help="Vertex AI region (default us-central1)")
    c.add_argument("--price-input", type=float, default=None, help="USD per million input tokens at the batch price")
    c.add_argument("--price-output", type=float, default=None, help="USD per million output tokens at the batch price")
    args = p.parse_args(argv)
    if args.command == "collect" and (args.price_input is None) != (args.price_output is None):
        p.error("--price-input and --price-output must be given together")
    return args


def _read_tasks(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    tasks = _read_tasks(args.tasks)
    client = gemini.make_client(args.project, args.location)
    if args.command == "submit":
        if args.repairs_from:
            wanted = {d["passage_id"] for d in _read_tasks(args.repairs_from)}
            tasks = [t for t in tasks if t["passage_id"] in wanted]
        if args.limit is not None:
            tasks = tasks[: args.limit]
        record = submit(tasks, args.codebook.read_text(encoding="utf-8"), model=args.model, client=client,
                        store=fetch.store(args.dest), batch_size=args.batch_size,
                        thinking_budget=args.thinking_budget, max_output_tokens=args.max_output_tokens)
        args.job_file.parent.mkdir(parents=True, exist_ok=True)
        args.job_file.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"submitted {record['tasks']} tasks in {record['requests']} requests: job {record['job']} ({record['state']})\n"
              f"-> {args.job_file}\nnext, once the job is done: python -m airo.coders.gemini_batch collect "
              f"--job-file {args.job_file} --tasks {args.tasks} --out <labels.jsonl> --project {args.project}")
        return 0
    record = json.loads(args.job_file.read_text(encoding="utf-8"))
    start = time.perf_counter()
    state, results = collect(record, tasks, client=client, store=fetch.store(record["dest"].removesuffix("/" + OUTPUT)))
    if results is None:
        print(f"job {record['job']} is {state}; nothing collected" + (" (the job failed)" if state in FAILED_STATES else ""))
        return 1 if state in FAILED_STATES else 2
    prices = None if args.price_input is None else {"input": args.price_input, "output": args.price_output}
    summary = gemini.write_labels(results, args.out, prices=prices, wall_time_s=time.perf_counter() - start)
    summary.update(mode="batch", job=record["job"], job_state=state, submitted=record.get("submitted"))
    with open(str(args.out) + ".run.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    cost = summary["estimated_cost_usd"]
    print(f"{summary['succeeded']}/{summary['tasks']} labelled, {summary['deferred']} deferred to {args.out}.deferred.jsonl; "
          f"{summary['tokens']['input_tokens']:,} in / {summary['tokens']['output_tokens']:,} out tokens; "
          f"est. cost {'n/a' if cost is None else f'${cost:.4f}'}\n-> {args.out}  and  {args.out}.run.json\n"
          f"next: python -m airo --data <dir> accept {args.out} --coder {CODER}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
