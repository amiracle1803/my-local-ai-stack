"""ModelPort ladder logic — fully mocked HTTP, passes with Ollama OFF."""

import json

import httpx
import pytest

from harness.core.registry import load_registry
from harness.ports.model_port import ModelPort, LadderExhausted

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ok"],
    "properties": {"ok": {"type": "boolean"}},
}
GOOD = ("text", '{"ok": true}')
BAD = ("text", "not-json")


class MockOllama:
    """Serves per-model queued responses; records call order."""

    def __init__(self, responses: dict, always_connerror: bool = False):
        self.responses = {k: list(v) for k, v in responses.items()}
        self.always_connerror = always_connerror
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        tag = body["model"]
        self.calls.append(tag)
        if self.always_connerror:
            raise httpx.ConnectError("connection refused")
        queue = self.responses.get(tag, [])
        item = queue.pop(0) if queue else ("text", "{}")
        if item == "connerror":
            raise httpx.ConnectError("connection refused")
        _, text = item
        return httpx.Response(200, json={
            "message": {"content": text}, "prompt_eval_count": 5, "eval_count": 7,
        })


def make_port(mock: MockOllama, tmp_path):
    reg = load_registry()
    client = httpx.Client(transport=httpx.MockTransport(mock.handler))
    return reg, ModelPort(reg, runs_dir=tmp_path, client=client)


def _msgs():
    return [{"role": "user", "content": "return json"}]


def _log_lines(tmp_path, task_id):
    log = tmp_path / task_id / "logs" / "calls.jsonl"
    return [json.loads(l) for l in log.read_text().splitlines() if l.strip()]


# --- resolution ----------------------------------------------------------

def test_resolve_tier_and_agent(tmp_path):
    _, port = make_port(MockOllama({}), tmp_path)
    assert port.resolve("T0")[0] == "T0"
    assert port.resolve("T0")[1].id == "qwen2.5-3b@ollama"
    assert port.resolve("planner")[0] == "T2"        # planner min_tier T2 from agents.yaml
    assert port.resolve("executor")[0] == "T1"


# --- ladder rungs --------------------------------------------------------

def test_rung0_primary_success(tmp_path):
    mock = MockOllama({"qwen2.5:3b": [GOOD]})
    _, port = make_port(mock, tmp_path)
    r = port.generate("T0", _msgs(), schema=SCHEMA, task_id="T-a")
    assert r.ok and r.rung == 0 and r.data == {"ok": True}
    assert mock.calls == ["qwen2.5:3b"]
    assert len(_log_lines(tmp_path, "T-a")) == 1


def test_rung1_repair_same_model(tmp_path):
    mock = MockOllama({"qwen2.5:3b": [BAD, GOOD]})
    _, port = make_port(mock, tmp_path)
    r = port.generate("T0", _msgs(), schema=SCHEMA, task_id="T-b")
    assert r.rung == 1
    assert mock.calls == ["qwen2.5:3b", "qwen2.5:3b"]   # repair on same model
    lines = _log_lines(tmp_path, "T-b")
    assert [l["rung"] for l in lines] == [0, 1]
    assert lines[0]["outcome"] == "schema-invalid"


def test_rung2_sibling(tmp_path):
    mock = MockOllama({"qwen2.5:7b": [BAD, BAD], "ornith:9b": [GOOD]})
    _, port = make_port(mock, tmp_path)
    r = port.generate("T1", _msgs(), schema=SCHEMA, task_id="T-c")
    assert r.rung == 2 and r.model_id == "ornith-9b@ollama"
    assert mock.calls == ["qwen2.5:7b", "qwen2.5:7b", "ornith:9b"]


def test_rung3_tier_escalation(tmp_path):
    mock = MockOllama({
        "qwen2.5:7b": [BAD, BAD],   # rung0 + repair
        "ornith:9b": [BAD],         # rung2 sibling (no repair for siblings)
        "qwen3:8b": [GOOD],         # rung3 tier+1
    })
    _, port = make_port(mock, tmp_path)
    r = port.generate("T1", _msgs(), schema=SCHEMA, task_id="T-d")
    assert r.rung == 3 and r.model_id == "qwen3-8b@ollama"


def test_ladder_exhausted_raises_and_logs(tmp_path):
    mock = MockOllama({})  # every model returns "{}" -> schema-invalid (missing 'ok')
    _, port = make_port(mock, tmp_path)
    with pytest.raises(LadderExhausted):
        port.generate("T1", _msgs(), schema=SCHEMA, task_id="T-e")
    lines = _log_lines(tmp_path, "T-e")
    assert all(l["outcome"] == "schema-invalid" for l in lines)
    assert {l["rung"] for l in lines} == {0, 1, 2, 3}


def test_ollama_off_is_typed_not_crash(tmp_path):
    mock = MockOllama({}, always_connerror=True)
    _, port = make_port(mock, tmp_path)
    with pytest.raises(LadderExhausted):
        port.generate("T0", _msgs(), schema=SCHEMA, task_id="T-f")
    lines = _log_lines(tmp_path, "T-f")
    assert lines and all(l["outcome"] == "connection-refused" for l in lines)
    # connection failures are NOT schema-repaired -> no repair rung
    assert all(l["rung"] != 1 for l in lines)


def test_prompt_hash_and_usage_logged(tmp_path):
    mock = MockOllama({"qwen2.5:3b": [GOOD]})
    _, port = make_port(mock, tmp_path)
    port.generate("T0", _msgs(), schema=SCHEMA, task_id="T-g")
    line = _log_lines(tmp_path, "T-g")[0]
    assert len(line["prompt_hash"]) == 64
    assert line["tokens_in"] == 5 and line["tokens_out"] == 7
    assert line["latency_ms"] is not None


def test_no_schema_returns_text(tmp_path):
    mock = MockOllama({"qwen2.5:3b": [("text", "plain answer")]})
    _, port = make_port(mock, tmp_path)
    r = port.generate("T0", _msgs(), task_id="T-h")
    assert r.ok and r.data is None and r.text == "plain answer"
