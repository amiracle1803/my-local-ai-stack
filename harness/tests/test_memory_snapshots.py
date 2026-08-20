"""Snapshot/rollback memory tests — recall state can be reverted without data loss."""

from harness.core import memory


def test_snapshot_then_rollback_restores_index(tmp_path):
    memory.write_error("T-1", "first", "ctx", "cause", ["a"], "rec", memory_dir=tmp_path)
    snap_id = memory.snapshot_index(tmp_path)
    baseline = (tmp_path / memory.INDEX_NAME).read_text(encoding="utf-8")

    memory.write_error("T-2", "second", "ctx", "cause", ["b"], "rec", memory_dir=tmp_path)
    grown = (tmp_path / memory.INDEX_NAME).read_text(encoding="utf-8")
    assert grown != baseline

    reverted = memory.rollback_index(snap_id, tmp_path)
    assert reverted >= 1
    assert (tmp_path / memory.INDEX_NAME).read_text(encoding="utf-8") == baseline
    # evidence files stay on disk; only the index reverts
    assert len(list((tmp_path / "errors").glob("err-*.md"))) == 2


def test_snapshot_creates_manifest_entry(tmp_path):
    memory.ensure_memory(tmp_path)
    snap_id = memory.snapshot_index(tmp_path)
    manifest = memory._load_snapshot_manifest(tmp_path)
    assert snap_id in {e["id"] for e in manifest}
    assert (tmp_path / "snapshots" / f"{snap_id}.md").exists()


def test_list_snapshots_newest_first(tmp_path):
    memory.ensure_memory(tmp_path)
    memory.snapshot_index(tmp_path)
    memory.snapshot_index(tmp_path)
    snaps = memory.list_snapshots(tmp_path)
    assert len(snaps) == 2
    assert snaps[0]["created"] >= snaps[1]["created"]


def test_rollback_missing_snapshot_raises(tmp_path):
    memory.ensure_memory(tmp_path)
    try:
        memory.rollback_index("snap-nope", tmp_path)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("expected FileNotFoundError for missing snapshot")
