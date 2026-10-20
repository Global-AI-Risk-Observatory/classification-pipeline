"""Tests for the batch coder (airo.coders.gemini_batch).

No network and no credentials: a fake client mimics `client.batches.create` and
`client.batches.get`, and the store is a directory (`fetch.DirStore`) in place of the bucket.
Tasks and labels are those of the synchronous coder's tests.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from airo import fetch
from airo.coders import gemini, gemini_batch
from test_gemini_coder import LABELS, TASKS

CODEBOOK = "# Codebook\n\nLabel passages."


class FakeBatches:
    def __init__(self, state: str = "JOB_STATE_PENDING"):
        self.state, self.created = state, []

    def create(self, *, model, src, config):
        self.created.append({"model": model, "src": src, "config": config})
        return SimpleNamespace(name="projects/p/locations/l/batchPredictionJobs/123", state=SimpleNamespace(value=self.state))

    def get(self, *, name):
        return SimpleNamespace(name=name, state=SimpleNamespace(value=self.state))


def fake_client(state: str = "JOB_STATE_PENDING"):
    return SimpleNamespace(batches=FakeBatches(state))


def response(labels: list[dict], usage=(1000, 200, 0)) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps({"labels": labels})}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": usage[0], "candidatesTokenCount": usage[1], "thoughtsTokenCount": usage[2]}}


# --------------------------------------------------------------------------
# Schema and requests
# --------------------------------------------------------------------------


def test_vertex_schema_inlines_refs_marks_optionals_nullable_and_uses_upper_case_types():
    schema = gemini_batch.vertex_schema(gemini.Labels)
    text = json.dumps(schema)
    assert "$ref" not in text and "$defs" not in text and '"title"' not in text and '"default"' not in text
    label = schema["properties"]["labels"]["items"]
    assert schema["type"] == "OBJECT" and schema["required"] == ["labels"]
    assert label["properties"]["frame"]["nullable"] is True and "enum" in label["properties"]["frame"]
    assert label["properties"]["frame"]["type"] == "STRING"
    assert label["properties"]["roles"] == {"type": "ARRAY", "items": {"type": "STRING", "enum": label["properties"]["roles"]["items"]["enum"]}}
    assert "risk" in label["properties"]["roles"]["items"]["enum"]
    assert label["properties"]["passage_id"] == {"type": "STRING"}
    assert label["properties"]["ai_reference"]["enum"] == ["explicit", "none"]
    assert "passage_id" in label["required"] and "confidence" in label["required"]


def test_vertex_schema_rejects_a_union_it_cannot_express():
    with pytest.raises(ValueError):
        gemini_batch.vertex_schema({"anyOf": [{"type": "string"}, {"type": "integer"}]})


def test_requests_carry_the_codebook_once_per_batch_and_the_synchronous_settings():
    lines = gemini_batch.build_requests(TASKS, CODEBOOK, batch_size=2, thinking_budget=0)

    assert len(lines) == 2
    first = lines[0]["request"]
    text = first["contents"][0]["parts"][0]["text"]
    assert text.count("# Codebook") == 1 and text == gemini.build_batch_prompt(CODEBOOK, TASKS[:2])
    assert "abc123:10-12" in text and "abc123:40-41" in text and "abc123:77-77" not in text
    assert first["contents"][0]["role"] == "user"
    config = first["generationConfig"]
    assert config["temperature"] == 0 and config["responseMimeType"] == "application/json"
    assert config["thinkingConfig"] == {"thinkingBudget": 0}
    assert config["maxOutputTokens"] == max(gemini.MAX_OUTPUT_TOKENS, gemini._TOKENS_PER_LABEL * 2)
    assert config["responseSchema"] == gemini_batch.vertex_schema(gemini.Labels)
    assert "abc123:77-77" in lines[1]["request"]["contents"][0]["parts"][0]["text"]


# --------------------------------------------------------------------------
# submit
# --------------------------------------------------------------------------


def test_submit_writes_the_requests_and_creates_the_job(tmp_path):
    client, store = fake_client(), fetch.DirStore(tmp_path)
    record = gemini_batch.submit(TASKS, CODEBOOK, model="gemini-2.5-flash", client=client, store=store, batch_size=40)

    written = [json.loads(l) for l in (tmp_path / "requests.jsonl").read_text().splitlines()]
    assert len(written) == 1 and written == gemini_batch.build_requests(TASKS, CODEBOOK, batch_size=40)
    assert client.batches.created == [{"model": "gemini-2.5-flash", "src": f"{tmp_path}/requests.jsonl",
                                       "config": {"dest": f"{tmp_path}/output"}}]
    assert record["job"].endswith("/123") and record["state"] == "JOB_STATE_PENDING"
    assert record["tasks"] == 3 and record["requests"] == 1 and record["batch_size"] == 40
    assert record["src"] == f"{tmp_path}/requests.jsonl" and record["dest"] == f"{tmp_path}/output"


def test_submit_refuses_a_location_that_already_holds_requests(tmp_path):
    client, store = fake_client(), fetch.DirStore(tmp_path)
    gemini_batch.submit(TASKS, CODEBOOK, model="m", client=client, store=store)
    with pytest.raises(SystemExit, match="exists already"):
        gemini_batch.submit(TASKS, CODEBOOK, model="m", client=client, store=store)
    assert len(client.batches.created) == 1


# --------------------------------------------------------------------------
# collect
# --------------------------------------------------------------------------


def test_collect_reports_the_state_while_the_job_runs(tmp_path):
    record = {"job": "jobs/123", "model": "m", "dest": f"{tmp_path}/output"}
    state, results = gemini_batch.collect(record, TASKS, client=fake_client("JOB_STATE_RUNNING"), store=fetch.DirStore(tmp_path))
    assert state == "JOB_STATE_RUNNING" and results is None


def write_output(tmp_path, lines: list[dict], name="output/prediction-model-2026-10-20/predictions.jsonl"):
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps(l) + "\n" for l in lines), encoding="utf-8")


def test_collect_checks_every_label_and_defers_the_rest(tmp_path):
    requests = gemini_batch.build_requests(TASKS, CODEBOOK, batch_size=2)
    paraphrased = {**LABELS["abc123:40-41"], "ai_reference": "explicit", "frame": "business", "roles": ["adoption"],
                   "adoption_stage": "deployed", "business_functions": ["operations"], "ai_kinds": ["traditional_ml"],
                   "substantiveness": "specific", "evidence": ["Our data centre in Ohio hosts disaster recovery."]}
    write_output(tmp_path, [
        {**requests[0], "response": response([LABELS["abc123:10-12"], paraphrased], usage=(5000, 400, 0))},
        {**requests[1], "status": "Internal error"},
    ])
    record = {"job": "jobs/123", "model": "gemini-2.5-flash", "dest": f"{tmp_path}/output"}

    state, results = gemini_batch.collect(record, TASKS, client=fake_client("JOB_STATE_SUCCEEDED"), store=fetch.DirStore(tmp_path))

    assert state == "JOB_STATE_SUCCEEDED"
    assert [r["passage_id"] for r in results] == [t["passage_id"] for t in TASKS]
    ok, rejected, failed = results
    assert ok["error"] is None and ok["label"]["roles"] == ["adoption", "risk"] and not ok.get("deferred")
    assert ok["usage"] == {"input_tokens": 5000, "output_tokens": 400, "thinking_tokens": 0}
    assert rejected["deferred"] and "not a verbatim quote" in rejected["error"]
    assert json.loads(rejected["answer"])["passage_id"] == "abc123:40-41"
    assert rejected["usage"]["input_tokens"] == 0  # the request's tokens are booked once, on its first task
    assert failed["deferred"] and failed["error"] == "batch request failed: Internal error" and failed["answer"] is None

    summary = gemini.write_labels(results, tmp_path / "labels.jsonl")
    assert summary["succeeded"] == 1 and summary["deferred"] == 2 and summary["failed"] == 0
    assert [json.loads(l)["passage_id"] for l in (tmp_path / "labels.jsonl").read_text().splitlines()] == ["abc123:10-12"]
    deferred = [json.loads(l) for l in (tmp_path / "labels.jsonl.deferred.jsonl").read_text().splitlines()]
    assert [d["passage_id"] for d in deferred] == ["abc123:40-41", "abc123:77-77"]


def test_a_task_missing_from_the_answer_and_a_task_missing_from_the_output_are_deferred(tmp_path):
    requests = gemini_batch.build_requests(TASKS[:2], CODEBOOK, batch_size=2)
    write_output(tmp_path, [{**requests[0], "response": response([LABELS["abc123:10-12"]])}])
    results = gemini_batch.read_output((tmp_path / "output/prediction-model-2026-10-20/predictions.jsonl").read_text().splitlines(),
                                       TASKS, model="m")
    assert results[0]["error"] is None
    assert results[1]["error"] == "no label in the batch answer" and results[1]["deferred"]
    assert results[2]["error"] == "not in the batch output" and results[2]["deferred"]


def test_an_answer_that_is_not_json_defers_its_tasks(tmp_path):
    requests = gemini_batch.build_requests(TASKS[:2], CODEBOOK, batch_size=2)
    bad = {"candidates": [{"content": {"parts": [{"text": "{not json"}]}}], "usageMetadata": {"promptTokenCount": 10}}
    results = gemini_batch.read_output([json.dumps({**requests[0], "response": bad})], TASKS[:2], model="m")
    assert all(r["deferred"] and r["error"].startswith("batch answer is not JSON") for r in results)
    assert results[0]["usage"]["input_tokens"] == 10


def test_output_is_read_from_every_jsonl_file_under_output(tmp_path):
    requests = gemini_batch.build_requests(TASKS, CODEBOOK, batch_size=1)
    write_output(tmp_path, [{**requests[0], "response": response([LABELS["abc123:10-12"]])}], "output/a/predictions.jsonl")
    write_output(tmp_path, [{**requests[1], "response": response([LABELS["abc123:40-41"]])}], "output/b/predictions.jsonl")
    (tmp_path / "output/a/notes.txt").write_text("ignored")
    results = gemini_batch.read_output(gemini_batch.output_lines(fetch.DirStore(tmp_path)), TASKS, model="m")
    assert [r["error"] for r in results] == [None, None, "not in the batch output"]


def test_gcs_store_lists_files_at_any_depth(gcs):
    store = fetch.GcsStore("gs://bucket/run/batch", client=gcs)
    gcs.objects.update({"run/batch/output/job-1/predictions.jsonl": b"", "run/batch/output/job-1/": b"",
                        "run/batch/requests.jsonl": b"", "other/x.jsonl": b""})
    assert store.files("output") == {"output/job-1/predictions.jsonl"}


@pytest.fixture
def gcs(monkeypatch):
    from test_fetch import gcs as fetch_gcs

    return fetch_gcs.__wrapped__(monkeypatch)


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------


def test_the_command_line_submits_and_later_collects(tmp_path, monkeypatch, capsys):
    tasks_path, codebook_path = tmp_path / "tasks.jsonl", tmp_path / "codebook.md"
    tasks_path.write_text("".join(json.dumps(t) + "\n" for t in TASKS))
    codebook_path.write_text(CODEBOOK)
    client = fake_client()
    monkeypatch.setattr(gemini, "make_client", lambda project, location: client)
    dest, job_file = tmp_path / "batch", tmp_path / "gemini.batch.json"

    assert gemini_batch.main(["submit", "--tasks", str(tasks_path), "--codebook", str(codebook_path), "--model", "m",
                              "--project", "p", "--dest", str(dest), "--job-file", str(job_file), "--thinking-budget", "0",
                              "--batch-size", "2"]) == 0
    record = json.loads(job_file.read_text())
    assert record["requests"] == 2 and (dest / "requests.jsonl").exists()
    assert "submitted 3 tasks in 2 requests" in capsys.readouterr().out

    collect = ["collect", "--job-file", str(job_file), "--tasks", str(tasks_path), "--out", str(tmp_path / "labels.jsonl"),
               "--project", "p", "--price-input", "0.15", "--price-output", "1.25"]
    assert gemini_batch.main(collect) == 2  # still pending
    assert "JOB_STATE_PENDING" in capsys.readouterr().out

    requests = gemini_batch.build_requests(TASKS, CODEBOOK, batch_size=2, thinking_budget=0)
    write_output(dest, [{**requests[0], "response": response([LABELS["abc123:10-12"], LABELS["abc123:40-41"]], usage=(2_000_000, 0, 0))},
                        {**requests[1], "response": response([LABELS["abc123:77-77"]])}])
    client.batches.state = "JOB_STATE_SUCCEEDED"
    assert gemini_batch.main(collect) == 0
    run = json.loads((tmp_path / "labels.jsonl.run.json").read_text())
    assert run["mode"] == "batch" and run["job"] == record["job"] and run["job_state"] == "JOB_STATE_SUCCEEDED"
    assert run["succeeded"] == 3 and run["deferred"] == 0
    assert run["estimated_cost_usd"] == pytest.approx(2_001_000 * 0.15 / 1e6 + 200 * 1.25 / 1e6, abs=1e-6)
    assert len((tmp_path / "labels.jsonl").read_text().splitlines()) == 3


def test_submit_can_take_the_deferred_passages_of_an_earlier_run(tmp_path, monkeypatch):
    tasks_path, codebook_path, deferred = tmp_path / "tasks.jsonl", tmp_path / "codebook.md", tmp_path / "x.deferred.jsonl"
    tasks_path.write_text("".join(json.dumps(t) + "\n" for t in TASKS))
    codebook_path.write_text(CODEBOOK)
    deferred.write_text(json.dumps({"passage_id": "abc123:77-77", "answer": None, "error": "no label"}) + "\n")
    client = fake_client()
    monkeypatch.setattr(gemini, "make_client", lambda project, location: client)

    gemini_batch.main(["submit", "--tasks", str(tasks_path), "--codebook", str(codebook_path), "--model", "m", "--project", "p",
                       "--dest", str(tmp_path / "b"), "--job-file", str(tmp_path / "j.json"), "--repairs-from", str(deferred)])
    record = json.loads((tmp_path / "j.json").read_text())
    text = (tmp_path / "b" / "requests.jsonl").read_text()
    assert record["tasks"] == 1 and "abc123:77-77" in text and "abc123:10-12" not in text
