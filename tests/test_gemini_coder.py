"""Tests for the Gemini coder (airo.coders.gemini).

No network and no credentials: a fake client mimics the one SDK call path the
coder uses, `client.models.generate_content(model=, contents=, config=)`, and
returns objects with `.text`, `.usage_metadata` and `.candidates`. The tests do
not need the google-genai package; the few that look at the real SDK are skipped
without it.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest

from airo import classify
from airo.coders import gemini
from airo.taxonomy import Label

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

TASKS = [
    {
        "passage_id": "abc123:10-12",
        "company": "Acme Corp",
        "form": "10-K",
        "fiscal_year": 2025,
        "section": "Item 1A Risk Factors",
        "heading": "Technology risks",
        "matched_terms": {"ai": ["ai", "machine_learning"], "ai_adjacent": []},
        "text": "Technology risks\n\nWe use machine learning in our underwriting. Our AI models may produce "
        "inaccurate results, which could harm our reputation.",
    },
    {
        "passage_id": "abc123:40-41",
        "company": "Acme Corp",
        "form": "10-K",
        "fiscal_year": 2025,
        "section": None,
        "heading": None,
        "matched_terms": {"ai": [], "ai_adjacent": ["data_center"]},
        "text": "Our data center in Ohio hosts our disaster recovery systems.",
    },
    {
        "passage_id": "abc123:77-77",
        "company": "Acme Corp",
        "form": "10-K",
        "fiscal_year": 2025,
        "section": "Item 7 MD&A",
        "heading": "Outlook",
        "matched_terms": {"ai": ["generative_ai"], "ai_adjacent": []},
        "text": "We launched a generative AI assistant for customers in 2025, built on Azure OpenAI.",
    },
]

LABELS = {
    "abc123:10-12": {
        "passage_id": "abc123:10-12",
        "ai_reference": "explicit",
        "frame": "risk_factor",
        "roles": ["adoption", "risk"],
        "risk_types": ["operational_reliability", "reputational_ethical"],
        "adoption_stage": "deployed",
        "business_functions": ["operations"],
        "ai_kind": "non_generative",
        "disclosure_traits": ["hedging"],
        "substantiveness": "specific",
        "entities": [],
        "evidence": ["Our AI models may produce inaccurate results, which could harm our reputation."],
        "confidence": "high",
        "note": "",
    },
    "abc123:40-41": {
        "passage_id": "abc123:40-41",
        "ai_reference": "none",
        "frame": None,
        "roles": [],
        "risk_types": [],
        "adoption_stage": None,
        "ai_kind": None,
        "specificity": None,
        "entities": [],
        "evidence": [],
        "confidence": "high",
        "note": "",
    },
    "abc123:77-77": {
        "passage_id": "abc123:77-77",
        "ai_reference": "explicit",
        "frame": "business",
        "roles": ["offering"],
        "risk_types": [],
        "adoption_stage": None,
        "ai_kind": "generative",
        "disclosure_traits": ["hedging"],
        "substantiveness": "specific",
        "entities": ["Azure OpenAI"],
        "evidence": ["We launched a generative AI assistant for customers in 2025, built on Azure OpenAI."],
        "confidence": "high",
        "note": "",
    },
}

CODEBOOK = "# Codebook: test taxonomy\n\nLabel what the passage says.\n"


class FakeResponse:
    def __init__(self, text, *, prompt=100, output=50, thoughts=0, finish_reason="STOP"):
        self.text = text
        self.usage_metadata = SimpleNamespace(
            prompt_token_count=prompt, candidates_token_count=output, thoughts_token_count=thoughts
        )
        self.candidates = [SimpleNamespace(finish_reason=SimpleNamespace(name=finish_reason))]


class FakeModels:
    """Mimics `client.models`; `handler(passage_id, call_number)` produces the response."""

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        m = re.search(r"^passage_id: (\S+)$", contents, re.M)
        assert m, "the prompt must carry the passage_id"
        return self.handler(m.group(1), len(self.calls))


class FakeClient:
    def __init__(self, handler):
        self.models = FakeModels(handler)


def respond_with_labels(pid, _n):
    return FakeResponse(json.dumps(LABELS[pid]))


class RateLimited(Exception):
    """Shaped like google.genai.errors.ClientError for a 429: an integer `code`."""

    code = 429


# --------------------------------------------------------------------------
# Prompt
# --------------------------------------------------------------------------


def test_build_prompt_contains_codebook_and_every_task_field():
    prompt = gemini.build_prompt(CODEBOOK, TASKS[0])
    assert prompt.startswith(CODEBOOK.rstrip())
    for needle in [
        "passage_id: abc123:10-12",
        "Company: Acme Corp",
        "Form: 10-K",
        "Fiscal year: 2025",
        "Section: Item 1A Risk Factors",
        "Heading: Technology risks",
        "ai: ai, machine_learning",
        TASKS[0]["text"],
        "exactly one JSON object",
    ]:
        assert needle in prompt, needle


def test_build_prompt_handles_missing_context():
    prompt = gemini.build_prompt(CODEBOOK, TASKS[1])
    assert "Section: (unknown)" in prompt
    assert "Heading: (unknown)" in prompt
    assert "ai_adjacent: data_center" in prompt and "ai: " not in prompt.split("Matched terms:")[1].split("\n")[0]


# --------------------------------------------------------------------------
# code(): happy path, request configuration
# --------------------------------------------------------------------------


def test_happy_path_labels_pass_validate():
    client = FakeClient(respond_with_labels)
    results = gemini.code(TASKS, CODEBOOK, model="gemini-test", client=client, workers=2, backoff=0)

    assert [r["passage_id"] for r in results] == [t["passage_id"] for t in TASKS]
    assert all(r["error"] is None for r in results)
    assert all(r["model"] == "gemini-test" for r in results)
    assert all(r["usage"] == {"input_tokens": 100, "output_tokens": 50, "thinking_tokens": 0} for r in results)
    assert all(r["latency_s"] >= 0 for r in results)

    lines = [json.dumps(r["label"]) for r in results]
    accepted, problems = classify.validate(lines, TASKS, "gemini")
    assert problems == []
    assert len(accepted) == 3
    assert accepted[0]["roles"] == ["adoption", "risk"]
    assert len(client.models.calls) == 3


def test_request_is_json_mode_with_label_schema_at_temperature_zero():
    client = FakeClient(respond_with_labels)
    gemini.code(TASKS[:1], CODEBOOK, model="gemini-test", client=client, backoff=0)
    call = client.models.calls[0]
    assert call["model"] == "gemini-test"
    cfg = call["config"]
    assert cfg["temperature"] == 0
    assert cfg["response_mime_type"] == "application/json"
    assert cfg["response_schema"] is Label
    assert cfg["max_output_tokens"] >= 4096
    assert "thinking_config" not in cfg


def test_thinking_budget_is_passed_through():
    client = FakeClient(respond_with_labels)
    gemini.code(TASKS[:1], CODEBOOK, model="gemini-test", client=client, thinking_budget=1024, backoff=0)
    assert client.models.calls[0]["config"]["thinking_config"] == {"thinking_budget": 1024}


def test_passage_id_is_forced_to_the_task():
    def wrong_id(pid, _n):
        return FakeResponse(json.dumps({**LABELS[pid], "passage_id": "something-else"}))

    results = gemini.code(TASKS, CODEBOOK, model="m", client=FakeClient(wrong_id), backoff=0)
    assert all(r["error"] is None for r in results)
    assert [r["label"]["passage_id"] for r in results] == [t["passage_id"] for t in TASKS]


def test_missing_optional_fields_are_filled_with_defaults():
    def sparse(pid, _n):
        label = {k: v for k, v in LABELS[pid].items() if k not in ("note", "entities")}
        return FakeResponse(json.dumps(label))

    results = gemini.code(TASKS[:1], CODEBOOK, model="m", client=FakeClient(sparse), backoff=0)
    assert results[0]["error"] is None
    assert results[0]["label"]["note"] == "" and results[0]["label"]["entities"] == []
    assert "coder" not in results[0]["label"] and "taxonomy_version" not in results[0]["label"]


# --------------------------------------------------------------------------
# code(): failures are per task
# --------------------------------------------------------------------------


def test_invalid_json_is_an_error_for_that_task_only():
    def handler(pid, _n):
        if pid == TASKS[1]["passage_id"]:
            return FakeResponse('{"passage_id": "abc123:40-41", "ai_reference": ')
        return respond_with_labels(pid, _n)

    results = gemini.code(TASKS, CODEBOOK, model="m", client=FakeClient(handler), backoff=0, max_repairs=0)
    assert results[0]["error"] is None and results[2]["error"] is None
    assert results[1]["label"] is None
    assert results[1]["error"].startswith("invalid JSON")
    assert results[1]["usage"]["input_tokens"] == 100  # the failed call's tokens are still counted


def test_schema_violation_is_an_error_not_a_label():
    # risk_types without the `risk` role breaks Label's cross-field rule, which the
    # response schema cannot express; `accept` would reject it, so the coder must too.
    def handler(pid, _n):
        return FakeResponse(json.dumps({**LABELS[pid], "roles": ["adoption"]}))  # risk_types stay filled

    results = gemini.code(TASKS[:1], CODEBOOK, model="m", client=FakeClient(handler), backoff=0)
    assert results[0]["error"].startswith("rejected by validate")
    assert "risk_types" in results[0]["error"]
    assert results[0]["label"]["roles"] == ["adoption"]  # kept for inspection


def test_paraphrased_evidence_is_an_error():
    def handler(pid, _n):
        return FakeResponse(json.dumps({**LABELS[pid], "evidence": ["AI models may be inaccurate..."]}))

    results = gemini.code(TASKS[:1], CODEBOOK, model="m", client=FakeClient(handler), backoff=0)
    assert "verbatim" in results[0]["error"]


def test_empty_response_reports_finish_reason():
    def handler(pid, _n):
        return FakeResponse(None, output=0, thoughts=4000, finish_reason="MAX_TOKENS")

    results = gemini.code(TASKS[:1], CODEBOOK, model="m", client=FakeClient(handler), backoff=0)
    assert results[0]["label"] is None
    assert results[0]["error"] == "empty response (finish_reason=MAX_TOKENS)"
    assert results[0]["usage"]["thinking_tokens"] == 4000


def test_rate_limit_is_retried_then_succeeds():
    def handler(pid, n):
        if n <= 2:
            raise RateLimited("429 RESOURCE_EXHAUSTED")
        return respond_with_labels(pid, n)

    client = FakeClient(handler)
    results = gemini.code(TASKS[:1], CODEBOOK, model="m", client=client, max_retries=5, backoff=0)
    assert results[0]["error"] is None
    assert results[0]["label"]["passage_id"] == TASKS[0]["passage_id"]
    assert results[0]["attempts"] == 3
    assert len(client.models.calls) == 3


def test_retries_are_exhausted_without_raising():
    def handler(pid, n):
        raise RateLimited("429 RESOURCE_EXHAUSTED")

    client = FakeClient(handler)
    results = gemini.code(TASKS[:1], CODEBOOK, model="m", client=client, max_retries=2, backoff=0)
    assert results[0]["label"] is None
    assert results[0]["error"] == "RateLimited: 429 RESOURCE_EXHAUSTED"
    assert len(client.models.calls) == 3  # first attempt + 2 retries


def test_non_retryable_error_is_not_retried():
    class BadRequest(Exception):
        code = 400

    def handler(pid, n):
        raise BadRequest("invalid argument")

    client = FakeClient(handler)
    results = gemini.code(TASKS[:1], CODEBOOK, model="m", client=client, max_retries=5, backoff=0)
    assert results[0]["error"] == "BadRequest: invalid argument"
    assert len(client.models.calls) == 1


def test_retryable_classification():
    assert gemini.retryable(RateLimited())
    assert gemini.retryable(type("ServerError", (Exception,), {"code": 503})())
    assert gemini.retryable(ConnectionError("reset"))
    assert gemini.retryable(type("ReadTimeout", (Exception,), {})())
    assert not gemini.retryable(type("ClientError", (Exception,), {"code": 400})())
    assert not gemini.retryable(ValueError("x"))


def test_backoff_sleeps_between_retries(monkeypatch):
    sleeps = []
    monkeypatch.setattr(gemini.time, "sleep", sleeps.append)
    monkeypatch.setattr(gemini.random, "random", lambda: 0.0)

    def handler(pid, n):
        if n <= 3:
            raise RateLimited()
        return respond_with_labels(pid, n)

    gemini.code(TASKS[:1], CODEBOOK, model="m", client=FakeClient(handler), backoff=1.0)
    assert sleeps == [1.0, 2.0, 4.0]


# --------------------------------------------------------------------------
# write_labels and the run summary
# --------------------------------------------------------------------------


def test_write_labels_writes_only_successes_and_a_run_summary(tmp_path):
    def handler(pid, _n):
        if pid == TASKS[1]["passage_id"]:
            return FakeResponse("not json", prompt=10, output=1, thoughts=5)
        return FakeResponse(json.dumps(LABELS[pid]), prompt=100, output=50, thoughts=200)

    results = gemini.code(TASKS, CODEBOOK, model="gemini-test", client=FakeClient(handler), backoff=0, max_repairs=0)
    out = tmp_path / "labels_in" / "gemini.jsonl"
    summary = gemini.write_labels(results, out, prices={"input": 0.30, "output": 2.50}, wall_time_s=12.3456)

    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    accepted, problems = classify.validate(lines, TASKS, "gemini")
    assert [a["passage_id"] for a in accepted] == [TASKS[0]["passage_id"], TASKS[2]["passage_id"]]
    assert problems == [f"missing label for {TASKS[1]['passage_id']}"]

    sidecar = json.loads((tmp_path / "labels_in" / "gemini.jsonl.run.json").read_text(encoding="utf-8"))
    assert sidecar == summary
    assert sidecar["coder"] == "gemini"
    assert sidecar["model"] == "gemini-test"
    assert sidecar["tasks"] == 3 and sidecar["succeeded"] == 2 and sidecar["failed"] == 1
    assert sidecar["tokens"] == {
        "input_tokens": 210, "output_tokens": 101, "thinking_tokens": 405, "total_tokens": 716,
    }
    assert sidecar["wall_time_s"] == 12.346
    assert sidecar["prices_per_million_tokens"] == {"input": 0.30, "output": 2.50}
    # input at the input price, output plus thinking at the output price
    assert sidecar["estimated_cost_usd"] == pytest.approx((210 * 0.30 + (101 + 405) * 2.50) / 1e6)
    assert sidecar["failures"] == [{"passage_id": TASKS[1]["passage_id"], "error": results[1]["error"]}]


def test_no_prices_means_no_estimate(tmp_path):
    results = gemini.code(TASKS, CODEBOOK, model="m", client=FakeClient(respond_with_labels), backoff=0)
    summary = gemini.write_labels(results, tmp_path / "g.jsonl")
    assert summary["estimated_cost_usd"] is None
    assert summary["prices_per_million_tokens"] is None
    assert summary["wall_time_s"] is None
    assert summary["failed"] == 0 and summary["failures"] == []


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def test_parse_args_defaults():
    args = gemini.parse_args(
        ["--tasks", "data/tasks.jsonl", "--codebook", "data/codebook.md", "--out", "data/labels_in/gemini.jsonl",
         "--model", "gemini-2.5-flash", "--project", "my-proj"]
    )
    assert str(args.tasks) == "data/tasks.jsonl" and str(args.codebook) == "data/codebook.md"
    assert str(args.out) == "data/labels_in/gemini.jsonl"
    assert args.model == "gemini-2.5-flash" and args.project == "my-proj"
    assert args.location == "us-central1"
    assert args.workers == 4 and args.max_retries == 5
    assert args.thinking_budget is None and args.max_output_tokens == gemini.MAX_OUTPUT_TOKENS
    assert args.price_input is None and args.price_output is None and args.limit is None


def test_parse_args_options():
    args = gemini.parse_args(
        ["--tasks", "t.jsonl", "--codebook", "c.md", "--out", "o.jsonl", "--model", "m", "--project", "p",
         "--location", "europe-west4", "--workers", "8", "--thinking-budget", "512",
         "--price-input", "0.3", "--price-output", "2.5", "--limit", "10"]
    )
    assert args.location == "europe-west4" and args.workers == 8
    assert args.thinking_budget == 512 and args.limit == 10
    assert args.price_input == 0.3 and args.price_output == 2.5


def test_parse_args_requires_both_prices_and_required_options():
    base = ["--tasks", "t", "--codebook", "c", "--out", "o", "--model", "m", "--project", "p"]
    with pytest.raises(SystemExit):
        gemini.parse_args(base + ["--price-input", "0.3"])
    with pytest.raises(SystemExit):
        gemini.parse_args(["--tasks", "t", "--codebook", "c", "--out", "o", "--model", "m"])  # no --project


def test_main_runs_end_to_end_with_a_fake_client(tmp_path, monkeypatch, capsys):
    tasks_file = tmp_path / "tasks.jsonl"
    tasks_file.write_text("".join(json.dumps(t) + "\n" for t in TASKS), encoding="utf-8")
    codebook_file = tmp_path / "codebook.md"
    codebook_file.write_text(CODEBOOK, encoding="utf-8")
    out = tmp_path / "labels_in" / "gemini.jsonl"
    made = {}

    def fake_make_client(project, location):
        made.update(project=project, location=location)
        return FakeClient(respond_with_labels)

    monkeypatch.setattr(gemini, "make_client", fake_make_client)
    rc = gemini.main(
        ["--tasks", str(tasks_file), "--codebook", str(codebook_file), "--out", str(out), "--model", "m",
         "--project", "proj", "--limit", "2", "--price-input", "1", "--price-output", "2", "--batch-size", "1"]
    )
    assert rc == 0
    assert made == {"project": "proj", "location": "us-central1"}
    assert len(out.read_text(encoding="utf-8").splitlines()) == 2  # --limit 2
    summary = json.loads((tmp_path / "labels_in" / "gemini.jsonl.run.json").read_text(encoding="utf-8"))
    assert summary["tasks"] == 2 and summary["estimated_cost_usd"] == pytest.approx((200 * 1 + 100 * 2) / 1e6)
    assert "2/2 labelled" in capsys.readouterr().out


# --------------------------------------------------------------------------
# Against the real SDK, when installed (still no network)
# --------------------------------------------------------------------------


def test_sdk_accepts_the_label_class_as_response_schema():
    """The SDK must turn Label (Optional[Literal], list[Literal]) into a request schema
    without flattening. Uses the SDK's own converter, which is what generate_content calls."""
    pytest.importorskip("google.genai")
    from google.genai import types

    try:
        from google.genai._transformers import t_schema
    except ImportError:  # pragma: no cover - SDK layout changed
        pytest.skip("google.genai._transformers.t_schema not available in this SDK version")

    cfg = types.GenerateContentConfig.model_validate(gemini.request_config(thinking_budget=256))
    assert cfg.response_schema is Label
    assert cfg.thinking_config.thinking_budget == 256
    assert cfg.response_mime_type == "application/json"

    schema = t_schema(None, Label).model_dump(exclude_none=True)
    assert schema["type"] == "OBJECT"
    assert schema["properties"]["ai_reference"]["enum"] == ["explicit", "implicit", "none"]
    assert schema["properties"]["adoption_stage"]["nullable"] is True
    assert schema["properties"]["roles"]["items"]["enum"][0] == "market_driver"
    assert set(schema["properties"]) == set(Label.model_fields)


def test_real_sdk_errors_are_classified():
    pytest.importorskip("google.genai")
    from google.genai import errors

    assert gemini.retryable(errors.ClientError(429, {"error": {"message": "quota"}}))
    assert gemini.retryable(errors.ServerError(503, {"error": {"message": "unavailable"}}))
    assert not gemini.retryable(errors.ClientError(400, {"error": {"message": "bad request"}}))


# --------------------------------------------------------------------------
# Fallback: an answer the acceptance check rejects is asked for again
# --------------------------------------------------------------------------


def test_a_rejected_answer_is_asked_for_again_with_the_reason_and_then_accepted():
    pid = TASKS[0]["passage_id"]

    def handler(_pid, n):
        if n == 1:
            return FakeResponse(json.dumps({**LABELS[pid], "evidence": ["AI models may be inaccurate..."]}))
        return respond_with_labels(pid, n)

    client = FakeClient(handler)
    results = gemini.code(TASKS[:1], CODEBOOK, model="m", client=client, backoff=0)

    assert results[0]["error"] is None and results[0]["label"]["evidence"] == LABELS[pid]["evidence"]
    assert (results[0]["repairs"], results[0]["attempts"], len(client.models.calls)) == (1, 2, 2)
    assert results[0]["usage"]["input_tokens"] == 200  # both requests are counted
    second = client.models.calls[1]["contents"]
    assert second.startswith(client.models.calls[0]["contents"])  # the same task
    assert "not a verbatim quote" in second and "AI models may be inaccurate..." in second
    assert "character for character" in second


def test_missing_evidence_is_asked_for_again():
    pid = TASKS[0]["passage_id"]

    def handler(_pid, n):
        return FakeResponse(json.dumps({**LABELS[pid], "evidence": []})) if n == 1 else respond_with_labels(pid, n)

    results = gemini.code(TASKS[:1], CODEBOOK, model="m", client=FakeClient(handler), backoff=0)
    assert results[0]["error"] is None and results[0]["repairs"] == 1


def test_an_answer_still_rejected_after_the_fallback_stays_an_error_and_nothing_is_written(tmp_path):
    def handler(pid, _n):
        return FakeResponse(json.dumps({**LABELS[pid], "evidence": ["AI models may be inaccurate..."]}))

    client = FakeClient(handler)
    results = gemini.code(TASKS[:1], CODEBOOK, model="m", client=client, backoff=0, max_repairs=2)

    assert "verbatim" in results[0]["error"] and results[0]["repairs"] == 2 and len(client.models.calls) == 3
    summary = gemini.write_labels(results, tmp_path / "out.jsonl")
    assert (tmp_path / "out.jsonl").read_text(encoding="utf-8") == ""
    assert (summary["failed"], summary["asked_again"], summary["accepted_after_asking_again"]) == (1, 1, 0)


def test_the_fallback_can_be_switched_off():
    def handler(pid, _n):
        return FakeResponse(json.dumps({**LABELS[pid], "evidence": []}))

    client = FakeClient(handler)
    results = gemini.code(TASKS[:1], CODEBOOK, model="m", client=client, backoff=0, max_repairs=0)
    assert results[0]["error"] is not None and results[0]["repairs"] == 0 and len(client.models.calls) == 1


# --------------------------------------------------------------------------
# Several tasks per request: the codebook once, every label checked on its own
# --------------------------------------------------------------------------


class BatchClient:
    """Answers a batch request with {"labels": [...]} and a single request with one label.

    `label(passage_id, call_number, is_batch)` gives the label of a task (None leaves it out of a batch
    answer); `raw(call_number, is_batch)`, if given and not None, is returned as the answer text instead.
    """

    def __init__(self, label=None, raw=None):
        self.label = label or (lambda pid, n, batch: LABELS[pid])
        self.raw = raw or (lambda n, batch: None)
        self.calls = []
        self.models = self

    def generate_content(self, *, model, contents, config):
        ids = re.findall(r"^passage_id: (\S+)$", contents, re.M)
        batch = "## Task 1" in contents
        self.calls.append({"contents": contents, "config": config, "batch": batch, "ids": ids})
        n = len(self.calls)
        text = self.raw(n, batch)
        if text is None:
            if batch:
                text = json.dumps({"labels": [l for l in (self.label(i, n, True) for i in ids) if l is not None]})
            else:
                text = json.dumps(self.label(ids[0], n, False))
        return FakeResponse(text, prompt=1000 if batch else 100, output=60 * len(ids) if batch else 50)


def test_a_batch_sends_the_codebook_once_and_returns_one_checked_label_per_task():
    client = BatchClient()
    results = gemini.code(TASKS, CODEBOOK, model="m", client=client, backoff=0, batch_size=40)

    assert len(client.calls) == 1 and client.calls[0]["ids"] == [t["passage_id"] for t in TASKS]
    prompt = client.calls[0]["contents"]
    assert prompt.count(CODEBOOK.strip()) == 1 and f"There are {len(TASKS)} passages" in prompt
    assert [r["passage_id"] for r in results] == [t["passage_id"] for t in TASKS]
    assert all(r["error"] is None and r["repairs"] == 0 for r in results)
    assert results[0]["label"]["evidence"] == LABELS[TASKS[0]["passage_id"]]["evidence"]
    # the batch request's tokens are booked once
    assert sum(r["usage"]["input_tokens"] for r in results) == 1000
    config = client.calls[0]["config"]
    assert config["response_schema"] is gemini.Labels and config["max_output_tokens"] >= 40 * 600


def test_tasks_are_split_into_batches_in_order():
    client = BatchClient()
    results = gemini.code(TASKS, CODEBOOK, model="m", client=client, backoff=0, batch_size=2, workers=1)

    assert [c["ids"] for c in client.calls] == [[TASKS[0]["passage_id"], TASKS[1]["passage_id"]], [TASKS[2]["passage_id"]]]
    assert [r["passage_id"] for r in results] == [t["passage_id"] for t in TASKS]


def test_a_rejected_label_of_a_batch_is_asked_again_on_its_own_and_the_rest_is_kept():
    bad = TASKS[0]["passage_id"]

    def label(pid, n, batch):
        if pid == bad and batch:
            return {**LABELS[pid], "evidence": ["AI models may be inaccurate..."]}
        return LABELS[pid]

    client = BatchClient(label)
    results = gemini.code(TASKS, CODEBOOK, model="m", client=client, backoff=0, batch_size=40)

    assert [c["batch"] for c in client.calls] == [True, False] and client.calls[1]["ids"] == [bad]
    assert "not a verbatim quote" in client.calls[1]["contents"] and "AI models may be inaccurate..." in client.calls[1]["contents"]
    assert all(r["error"] is None for r in results)
    assert [r["repairs"] for r in results] == [1, 0, 0]
    assert results[0]["label"]["evidence"] == LABELS[bad]["evidence"]


def test_a_task_missing_from_the_batch_answer_is_asked_on_its_own():
    missing = TASKS[1]["passage_id"]
    client = BatchClient(lambda pid, n, batch: None if (pid == missing and batch) else LABELS[pid])
    results = gemini.code(TASKS, CODEBOOK, model="m", client=client, backoff=0, batch_size=40)

    assert [c["batch"] for c in client.calls] == [True, False] and client.calls[1]["ids"] == [missing]
    assert "rejected by the automatic check" not in client.calls[1]["contents"]  # a plain request, there was no answer
    assert all(r["error"] is None for r in results) and results[1]["repairs"] == 0


def test_a_batch_answer_that_cannot_be_read_falls_back_to_one_request_per_task():
    client = BatchClient(raw=lambda n, batch: "not json" if batch else None)
    results = gemini.code(TASKS, CODEBOOK, model="m", client=client, backoff=0, batch_size=40)

    assert [c["batch"] for c in client.calls] == [True, False, False, False]
    assert all(r["error"] is None for r in results)


def test_a_label_still_rejected_after_the_batch_fallback_stays_an_error():
    bad = TASKS[0]["passage_id"]
    client = BatchClient(lambda pid, n, batch: {**LABELS[pid], "evidence": ["made up"]} if pid == bad else LABELS[pid])
    results = gemini.code(TASKS, CODEBOOK, model="m", client=client, backoff=0, batch_size=40, max_repairs=2)

    assert "verbatim" in results[0]["error"] and results[0]["repairs"] == 2 and results[0]["label"]["evidence"] == ["made up"]
    assert results[1]["error"] is None and results[2]["error"] is None
    assert len(client.calls) == 3  # the batch, then two repair requests for the one task


def test_the_command_line_uses_batches_of_40_by_default(tmp_path, monkeypatch):
    base = ["--tasks", "t", "--codebook", "c", "--out", "o", "--model", "m", "--project", "p"]
    assert gemini.parse_args(base).batch_size == 40 == gemini.BATCH_SIZE
    assert gemini.parse_args(base + ["--batch-size", "1"]).batch_size == 1

    (tmp_path / "tasks.jsonl").write_text("".join(json.dumps(t) + "\n" for t in TASKS), encoding="utf-8")
    (tmp_path / "codebook.md").write_text(CODEBOOK, encoding="utf-8")
    client = BatchClient()
    monkeypatch.setattr(gemini, "make_client", lambda project, location: client)
    rc = gemini.main(["--tasks", str(tmp_path / "tasks.jsonl"), "--codebook", str(tmp_path / "codebook.md"),
                      "--out", str(tmp_path / "out.jsonl"), "--model", "m", "--project", "p"])
    assert rc == 0 and len(client.calls) == 1 and client.calls[0]["batch"]
    assert len((tmp_path / "out.jsonl").read_text(encoding="utf-8").splitlines()) == len(TASKS)
