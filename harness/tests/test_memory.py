from harness.core import memory


def test_ensure_memory_tree(tmp_path):
    memory.ensure_memory(tmp_path)
    for sub in memory.STRATA:
        assert (tmp_path / sub).is_dir()
    assert (tmp_path / memory.INDEX_NAME).exists()


def test_write_error_frontmatter_and_body(tmp_path):
    path = memory.write_error(
        task_id="T-20260707-idx-a3f1",
        symptom="Indexer OOM on vaults over 8k notes",
        context="task class coding, model qwen2.5:7b, tier T1",
        root_cause="whole vault loaded into memory before chunking",
        remedies=["raised num_ctx (no effect)", "batched by folder (partial)"],
        recommendation="stream files; chunk before embedding",
        memory_dir=tmp_path,
    )
    text = path.read_text(encoding="utf-8")
    assert path.stem.startswith("err-")
    assert "type: error" in text
    assert "## Symptom" in text
    assert "## Root cause" in text
    assert "## Recommended next approach" in text
    # index updated
    index = (tmp_path / memory.INDEX_NAME).read_text(encoding="utf-8")
    assert path.stem in index


def test_find_errors_ranks_by_overlap(tmp_path):
    memory.write_error("T-1", "Indexer OOM on large vault", "ctx", "cause",
                       ["a"], "rec", memory_dir=tmp_path)
    memory.write_error("T-2", "Ollama connection refused", "ctx", "cause",
                       ["b"], "rec", memory_dir=tmp_path)

    hits = memory.find_errors(["indexer", "oom", "vault"], memory_dir=tmp_path)
    assert hits
    assert "indexer" in hits[0].id
    # unrelated query still finds the connection one
    conn = memory.find_errors("ollama connection", memory_dir=tmp_path)
    assert conn and "connection" in conn[0].id


def test_find_errors_empty_when_no_match(tmp_path):
    memory.ensure_memory(tmp_path)
    assert memory.find_errors(["nonexistentterm"], memory_dir=tmp_path) == []


def test_write_error_unique_paths(tmp_path):
    p1 = memory.write_error("T-1", "same symptom text", "c", "r", [], "rec", memory_dir=tmp_path)
    p2 = memory.write_error("T-1", "same symptom text", "c", "r", [], "rec", memory_dir=tmp_path)
    assert p1 != p2
