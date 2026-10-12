"""Automated coder: Gemini on Google Cloud Vertex AI, through the `google-genai` SDK.

    python -m airo.coders.gemini --tasks data/tasks.jsonl --codebook data/codebook.md \\
        --out data/labels_in/gemini.jsonl --model gemini-2.5-flash \\
        --project <gcp-project> --location us-central1

One request per `--batch-size` tasks (default 40): the request carries the codebook once
and the rendered tasks (`build_batch_prompt`) and asks for one JSON object with one label
per task; it runs in JSON mode (`response_mime_type="application/json"`,
`response_schema=Labels`) at temperature 0. Every label of the answer is checked on its
own. A task whose label is missing or rejected is asked again on its own, with the
codebook and the reason (see `code_one`), so one bad label costs one extra request and
not the batch. With `--batch-size 1` every task is a request of its own
(`build_prompt`, `response_schema=Label`).
The SDK converts the pydantic `Label` class itself: `Optional[Literal[...]]` fields
become nullable enums and `list[Literal[...]]` arrays of enums, so no flattening is
needed. The schema cannot express the cross-field rules of `Label` (risk_types only
with the `risk` role, ...), nor that `evidence` must be a verbatim quote; every
response is therefore checked with `classify.validate`, and a label that fails is
reported as that task's error rather than written out.

Output: `--out` receives the successful labels as JSONL (one `Label` per line, ready
for `python -m airo accept <out> --coder gemini`), and `<out>.run.json` the totals of
the run (tasks, succeeded, failed, tokens by kind, wall time, model, estimated cost).

What an earlier version of this pipeline learned about Gemini: on models that
"think" (Gemini 2.5 and later) the thinking tokens count against
`max_output_tokens`. With a tight limit the answer is cut off after the thinking and
`response.text` comes back empty with finish reason MAX_TOKENS. So
`max_output_tokens` is set generously (`MAX_OUTPUT_TOKENS`, 4096) and the thinking
budget is exposed (`--thinking-budget`); thinking tokens are reported separately in
the usage figures and, on Vertex AI, billed at the output-token price.

The live call has not been exercised yet: this module was written against the SDK's
documented interface (`google.genai.Client(vertexai=True, project=, location=)`,
`client.models.generate_content(model=, contents=, config=)`, `response.text`,
`response.usage_metadata`) and tested with a fake client only.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel

from .. import classify
from ..taxonomy import Label

CODER = "gemini"
MAX_OUTPUT_TOKENS = 4096
BATCH_SIZE = 40
# Output budget per label of a batch answer; a label is about 250 tokens.
_TOKENS_PER_LABEL = 600


class Labels(BaseModel):
    """The answer to a batch request: one label per task."""

    labels: list[Label]
# HTTP status codes worth retrying: rate limit, timeout, and server-side failures.
RETRY_CODES = {408, 429, 500, 502, 503, 504}
_MAX_BACKOFF = 60.0

_TASK_FIELDS = (
    ("Company", "company"),
    ("Form", "form"),
    ("Fiscal year", "fiscal_year"),
    ("Section", "section"),
    ("Heading", "heading"),
)


# --------------------------------------------------------------------------
# Prompt
# --------------------------------------------------------------------------


def render_task(task: dict) -> str:
    """One task as the coders see it: context fields, matched terms, passage text."""
    lines = [f"passage_id: {task['passage_id']}"]
    for title, key in _TASK_FIELDS:
        value = task.get(key)
        lines.append(f"{title}: {value if value not in (None, '') else '(unknown)'}")
    matched = task.get("matched_terms") or {}
    terms = ", ".join(f"{lex}: {', '.join(ts)}" for lex, ts in matched.items() if ts) or "(none)"
    lines.append(f"Matched terms: {terms}")
    lines += ["", "Passage:", "<<<", task["text"], ">>>"]
    return "\n".join(lines)


def build_prompt(codebook: str, task: dict) -> str:
    """The codebook, one rendered task, and the request for exactly one JSON object."""
    return "\n".join(
        [
            codebook.rstrip(),
            "",
            "---",
            "",
            "# Task",
            "",
            render_task(task),
            "",
            "Label this one passage. Return exactly one JSON object for it, with every field of the "
            "codebook and `passage_id` copied from the task, and nothing else.",
        ]
    )


def build_batch_prompt(codebook: str, tasks: list[dict]) -> str:
    """The codebook once, the rendered tasks, and the request for one label per task."""
    lines = [
        codebook.rstrip(),
        "",
        "---",
        "",
        "# Tasks",
        "",
        f"There are {len(tasks)} passages below, each under its own \"## Task\" heading. Label every passage "
        "on its own, from what that passage says: carry nothing over from one passage to another.",
    ]
    for n, task in enumerate(tasks, 1):
        lines += ["", f"## Task {n}", "", render_task(task)]
    lines += [
        "",
        "---",
        "",
        f"Return exactly one JSON object {{\"labels\": [...]}} with {len(tasks)} label objects, one per task and in "
        "the order of the tasks, each with every field of the codebook and `passage_id` copied from its task, "
        "and nothing else.",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Calling the model
# --------------------------------------------------------------------------


def make_client(project: str, location: str):
    """A Vertex AI client. Imported lazily: the package works without the SDK installed."""
    try:
        from google import genai
    except ImportError as e:  # pragma: no cover - depends on the environment
        raise ImportError(
            "the Gemini coder needs the google-genai package: pip install google-genai"
        ) from e
    return genai.Client(vertexai=True, project=project, location=location)


def request_config(thinking_budget: Optional[int] = None, max_output_tokens: int = MAX_OUTPUT_TOKENS,
                   schema: Any = Label) -> dict:
    """The `config` of every request (a GenerateContentConfigDict; the SDK validates it)."""
    config: dict[str, Any] = {
        "temperature": 0,
        "max_output_tokens": max_output_tokens,
        "response_mime_type": "application/json",
        "response_schema": schema,
    }
    if thinking_budget is not None:
        config["thinking_config"] = {"thinking_budget": thinking_budget}
    return config


def retryable(exc: Exception) -> bool:
    """Rate limits, timeouts, server errors and connection failures are retried; the rest is not."""
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code in RETRY_CODES or code >= 500
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    name = type(exc).__name__
    return any(k in name for k in ("Timeout", "Connect", "RemoteProtocol", "ReadError", "WriteError"))


def _usage(response) -> dict:
    u = getattr(response, "usage_metadata", None)
    return {
        "input_tokens": getattr(u, "prompt_token_count", None) or 0,
        "output_tokens": getattr(u, "candidates_token_count", None) or 0,
        "thinking_tokens": getattr(u, "thoughts_token_count", None) or 0,
    }


def _finish_reason(response) -> str:
    try:
        reason = response.candidates[0].finish_reason
    except (AttributeError, IndexError, TypeError):
        return "unknown"
    return getattr(reason, "name", None) or str(reason)


def _check(text: str, task: dict) -> tuple[Optional[dict], Optional[str]]:
    """Parse the model's text and run the pipeline's own acceptance check on it.

    Returns (label, error). On success the label is the normalised Label dict with
    passage_id forced to the task's. On a schema or evidence failure the label is the
    model's parsed JSON (for inspection) and error says why `accept` would reject it.
    """
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e}"
    if not isinstance(parsed, dict):
        return None, f"invalid JSON: expected an object, got {type(parsed).__name__}"
    parsed["passage_id"] = task["passage_id"]
    accepted, problems = classify.validate([json.dumps(parsed)], [task], CODER)
    if not accepted:
        reason = problems[0].split(": ", 1)[-1] if problems else "rejected"
        return parsed, f"rejected by validate: {reason}"
    label = {k: v for k, v in accepted[0].items() if k not in ("coder", "taxonomy_version")}
    return label, None


def repair_prompt(prompt: str, answer: str, error: str) -> str:
    """The task again, with the answer the acceptance check rejected and the reason."""
    return "\n".join(
        [
            prompt,
            "",
            "---",
            "",
            "Your previous answer to this task was rejected by the automatic check.",
            f"Reason: {error}",
            "",
            "Previous answer:",
            answer,
            "",
            "Return the corrected JSON object for the same passage, and nothing else. Every quote in "
            "`evidence` must be copied character for character from the passage text between <<< and >>>: "
            "one continuous stretch of it, without ellipses, without joining separate sentences, without "
            "changing punctuation, quotation marks or capitalisation. Give 1 to 3 quotes whenever "
            "`ai_reference` is not `none`.",
        ]
    )


def code_one(task: dict, codebook: str, *, model: str, client, config: dict,
             max_retries: int = 5, backoff: float = 1.0, max_repairs: int = 2,
             rejected: Optional[tuple[str, str]] = None) -> dict:
    """Label one task. Never raises: failures are captured in the result's `error`.

    `max_retries` is the number of retries after the first attempt of a request, with
    exponential backoff (`backoff` * 2**attempt seconds plus jitter, capped at 60 s) on
    retryable errors. `latency_s` covers all attempts.

    Fallback for an answer the acceptance check rejects (invalid JSON, a schema rule,
    evidence that is missing or not a verbatim quote): the task is asked again, up to
    `max_repairs` times, with the rejected answer and the reason (`repair_prompt`). An
    answer that is still rejected after that stays an error; nothing is corrected by
    the coder itself. `repairs` counts these extra requests, `usage` covers all requests.

    `rejected` is (answer, reason) of a label this task already got in a batch request and
    that the check rejected: the first request here is then already the repair request.
    """
    prompt = build_prompt(codebook, task)
    result = {
        "passage_id": task["passage_id"],
        "label": None,
        "error": None,
        "usage": {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0},
        "model": model,
        "latency_s": 0.0,
        "attempts": 0,
        "repairs": 0,
    }
    start = time.perf_counter()
    contents = prompt
    if rejected is not None:
        if max_repairs < 1:
            result["error"] = rejected[1]
            return result
        result["repairs"] = 1
        contents = repair_prompt(prompt, *rejected)
    while True:
        response = None
        for attempt in range(max_retries + 1):
            result["attempts"] += 1
            try:
                response = client.models.generate_content(model=model, contents=contents, config=config)
                break
            except Exception as e:  # noqa: BLE001 - every failure is captured per task
                result["error"] = f"{type(e).__name__}: {e}"
                if attempt < max_retries and retryable(e):
                    if backoff:
                        time.sleep(min(backoff * 2**attempt, _MAX_BACKOFF) * (1 + random.random()))
                    continue
                break
        if response is None:
            break
        for kind, n in _usage(response).items():
            result["usage"][kind] += n
        text = getattr(response, "text", None)
        if not text:
            result["error"] = f"empty response (finish_reason={_finish_reason(response)})"
            break
        result["label"], result["error"] = _check(text, task)
        if result["error"] is None or result["repairs"] >= max_repairs:
            break
        result["repairs"] += 1
        contents = repair_prompt(prompt, text, result["error"])
    result["latency_s"] = round(time.perf_counter() - start, 3)
    return result


def code_batch(tasks: list[dict], codebook: str, *, model: str, client, config: dict, single_config: dict,
               max_retries: int = 5, backoff: float = 1.0, max_repairs: int = 2) -> list[dict]:
    """Label several tasks with one request. Returns one result per task, in task order.

    The answer's labels are matched to the tasks by `passage_id` and checked one by one.
    A task whose label the check rejects is asked again on its own with that answer and
    the reason; a task without a label in the answer, and every task of a request that
    failed as a whole (error, empty or unreadable answer), is asked on its own from the
    start. The tokens of the batch request are booked on the first task's result.
    """
    start = time.perf_counter()
    usage = {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0}
    attempts, answer = 0, None
    for attempt in range(max_retries + 1):
        attempts += 1
        try:
            answer = client.models.generate_content(model=model, contents=build_batch_prompt(codebook, tasks), config=config)
            break
        except Exception as e:  # noqa: BLE001 - the tasks are then asked one by one
            if attempt < max_retries and retryable(e):
                if backoff:
                    time.sleep(min(backoff * 2**attempt, _MAX_BACKOFF) * (1 + random.random()))
                continue
            break
    by_id: dict[str, dict] = {}
    if answer is not None:
        usage = _usage(answer)
        try:
            parsed = json.loads(getattr(answer, "text", None) or "")
            for label in parsed.get("labels") or [] if isinstance(parsed, dict) else []:
                if isinstance(label, dict) and isinstance(label.get("passage_id"), str):
                    by_id.setdefault(label["passage_id"], label)  # a repeated id: the first label counts
        except json.JSONDecodeError:
            pass
    latency = round(time.perf_counter() - start, 3)

    results = []
    for task in tasks:
        own = {"model": model, "config": single_config, "client": client,
               "max_retries": max_retries, "backoff": backoff, "max_repairs": max_repairs}
        raw = by_id.get(task["passage_id"])
        if raw is None:
            result = code_one(task, codebook, **own)
        else:
            text = json.dumps(raw, ensure_ascii=False)
            label, error = _check(text, task)
            if error is None:
                result = {
                    "passage_id": task["passage_id"], "label": label, "error": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0},
                    "model": model, "latency_s": 0.0, "attempts": 0, "repairs": 0,
                }
            else:
                result = code_one(task, codebook, rejected=(text, error), **own)
                if result["label"] is None:
                    result["label"] = label  # the rejected label, kept for inspection
        results.append(result)
    if results:
        for kind, n in usage.items():
            results[0]["usage"][kind] += n
        results[0]["latency_s"] = round(results[0]["latency_s"] + latency, 3)
        results[0]["attempts"] += attempts
    return results


def code(tasks: list[dict], codebook: str, *, model: str, client, workers: int = 4,
         max_retries: int = 5, thinking_budget: Optional[int] = None,
         max_output_tokens: int = MAX_OUTPUT_TOKENS, backoff: float = 1.0, max_repairs: int = 2,
         batch_size: int = 1,
         on_result: Optional[Callable[[dict], None]] = None) -> list[dict]:
    """Label every task, `batch_size` tasks per request, `workers` requests at a time.

    Returns one result per task, in task order:
    {"passage_id", "label": dict or None, "error": str or None,
     "usage": {"input_tokens", "output_tokens", "thinking_tokens"}, "model", "latency_s", "repairs"}.
    `on_result`, if given, is called with each result as it completes.
    """
    config = request_config(thinking_budget, max_output_tokens)

    def run(task: dict) -> dict:
        result = code_one(task, codebook, model=model, client=client, config=config,
                          max_retries=max_retries, backoff=backoff, max_repairs=max_repairs)
        if on_result:
            on_result(result)
        return result

    if batch_size <= 1:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            return list(pool.map(run, tasks))

    batch_config = request_config(thinking_budget, max(max_output_tokens, _TOKENS_PER_LABEL * batch_size), schema=Labels)

    def run_batch(batch: list[dict]) -> list[dict]:
        results = code_batch(batch, codebook, model=model, client=client, config=batch_config, single_config=config,
                             max_retries=max_retries, backoff=backoff, max_repairs=max_repairs)
        if on_result:
            for result in results:
                on_result(result)
        return results

    batches = [tasks[i : i + batch_size] for i in range(0, len(tasks), batch_size)]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return [result for results in pool.map(run_batch, batches) for result in results]


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


def estimate_cost(tokens: dict, prices: Optional[dict]) -> Optional[float]:
    """USD for the run from a price table {"input": $/M tokens, "output": $/M tokens}.

    Thinking tokens are billed as output tokens. None if either price is missing.
    """
    if not prices or prices.get("input") is None or prices.get("output") is None:
        return None
    cost = (
        tokens["input_tokens"] * prices["input"]
        + (tokens["output_tokens"] + tokens["thinking_tokens"]) * prices["output"]
    ) / 1_000_000
    return round(cost, 6)


def run_summary(results: list[dict], *, prices: Optional[dict] = None,
                wall_time_s: Optional[float] = None) -> dict:
    tokens = {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0}
    for r in results:
        for k in tokens:
            tokens[k] += r["usage"].get(k, 0) or 0
    failed = [r for r in results if r["error"] is not None]
    models = sorted({r["model"] for r in results})
    return {
        "coder": CODER,
        "model": models[0] if len(models) == 1 else models,
        "tasks": len(results),
        "succeeded": len(results) - len(failed),
        "failed": len(failed),
        # Fallback: tasks whose first answer the acceptance check rejected, and how many of them it then accepted.
        "asked_again": sum(1 for r in results if r.get("repairs")),
        "accepted_after_asking_again": sum(1 for r in results if r.get("repairs") and r["error"] is None),
        "tokens": {**tokens, "total_tokens": sum(tokens.values())},
        "wall_time_s": round(wall_time_s, 3) if wall_time_s is not None else None,
        "latency_s_sum": round(sum(r["latency_s"] for r in results), 3),
        "prices_per_million_tokens": prices,
        "estimated_cost_usd": estimate_cost(tokens, prices),
        "failures": [{"passage_id": r["passage_id"], "error": r["error"]} for r in failed],
    }


def write_labels(results: list[dict], path, *, prices: Optional[dict] = None,
                 wall_time_s: Optional[float] = None) -> dict:
    """Write the successful labels as JSONL to `path` and the run summary to `<path>.run.json`.

    Only results without an error are written, so the file is what
    `python -m airo accept <path> --coder gemini` expects. Returns the summary.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in results:
            if r["error"] is None and r["label"] is not None:
                fh.write(json.dumps(r["label"], ensure_ascii=False) + "\n")
    summary = run_summary(results, prices=prices, wall_time_s=wall_time_s)
    with open(str(path) + ".run.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return summary


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m airo.coders.gemini",
        description="Label tasks.jsonl with Gemini on Vertex AI; writes JSONL for `airo accept`.",
    )
    p.add_argument("--tasks", type=Path, required=True, help="tasks.jsonl from `airo tasks`")
    p.add_argument("--codebook", type=Path, required=True, help="codebook.md from `airo tasks`")
    p.add_argument("--out", type=Path, required=True, help="labels JSONL to write; <out>.run.json beside it")
    p.add_argument("--model", required=True, help="Gemini model name, e.g. gemini-2.5-flash")
    p.add_argument("--project", required=True, help="Google Cloud project id")
    p.add_argument("--location", default="us-central1", help="Vertex AI region (default us-central1)")
    p.add_argument("--workers", type=int, default=4, help="concurrent requests (default 4)")
    p.add_argument("--max-retries", type=int, default=5, help="retries per task on transient errors (default 5)")
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE,
                   help=f"tasks per request; the codebook is sent once per request (default {BATCH_SIZE}; 1 = one request per task)")
    p.add_argument("--max-repairs", type=int, default=2,
                   help="times a task is asked again when the acceptance check rejects its answer (default 2)")
    p.add_argument("--thinking-budget", type=int, default=None,
                   help="thinking token budget; omitted = model default, 0 = off where the model allows")
    p.add_argument("--max-output-tokens", type=int, default=MAX_OUTPUT_TOKENS,
                   help=f"includes thinking tokens on thinking models (default {MAX_OUTPUT_TOKENS})")
    p.add_argument("--price-input", type=float, default=None, help="USD per million input tokens")
    p.add_argument("--price-output", type=float, default=None,
                   help="USD per million output tokens (thinking tokens are billed as output)")
    p.add_argument("--limit", type=int, default=None, help="label only the first N tasks")
    args = p.parse_args(argv)
    if (args.price_input is None) != (args.price_output is None):
        p.error("--price-input and --price-output must be given together")
    return args


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    with open(args.tasks, encoding="utf-8") as fh:
        tasks = [json.loads(line) for line in fh if line.strip()]
    if args.limit is not None:
        tasks = tasks[: args.limit]
    codebook = args.codebook.read_text(encoding="utf-8")
    client = make_client(args.project, args.location)
    prices = None if args.price_input is None else {"input": args.price_input, "output": args.price_output}

    done = 0

    def progress(r: dict) -> None:
        nonlocal done
        done += 1
        status = "ok" if r["error"] is None else f"FAILED: {r['error']}"
        if r.get("repairs"):
            status += f"  (asked again {r['repairs']}x)"
        print(f"[{done}/{len(tasks)}] {r['passage_id']}  {r['latency_s']}s  {status}", file=sys.stderr)

    start = time.perf_counter()
    results = code(
        tasks, codebook, model=args.model, client=client, workers=args.workers,
        max_retries=args.max_retries, max_repairs=args.max_repairs, batch_size=args.batch_size,
        thinking_budget=args.thinking_budget,
        max_output_tokens=args.max_output_tokens, on_result=progress,
    )
    summary = write_labels(results, args.out, prices=prices, wall_time_s=time.perf_counter() - start)
    cost = summary["estimated_cost_usd"]
    print(
        f"{summary['succeeded']}/{summary['tasks']} labelled, {summary['failed']} failed; "
        f"{summary['tokens']['input_tokens']:,} in / {summary['tokens']['output_tokens']:,} out / "
        f"{summary['tokens']['thinking_tokens']:,} thinking tokens; "
        f"{summary['wall_time_s']}s; est. cost {'n/a' if cost is None else f'${cost:.4f}'}\n"
        f"-> {args.out}  and  {args.out}.run.json\n"
        f"next: python -m airo --data <dir> accept {args.out} --coder {CODER}"
    )
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
