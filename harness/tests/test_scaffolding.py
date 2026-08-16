import json
import re

from harness.core.models import Classification
from harness.core import runstate


def _cls():
    return Classification(domain="coding", difficulty="hard", risk="low", offline_ok=True)


def test_task_id_format(tmp_path):
    task = runstate.create_task("Build the wiki index now", _cls(), runs_dir=tmp_path)
    assert re.match(r"^T-[0-9]{8}-[a-z0-9-]+-[0-9a-f]{4}$", task.id)


def test_run_dir_scaffolded(tmp_path):
    task = runstate.create_task("scaffold me", _cls(), runs_dir=tmp_path)
    d = runstate.run_dir(task.id, tmp_path)
    for sub in runstate.RUN_SUBDIRS:
        assert (d / sub).is_dir()
    assert (d / "task.json").exists()
    assert (d / "manifest.json").exists()


def test_task_json_roundtrips(tmp_path):
    task = runstate.create_task("roundtrip goal", _cls(), runs_dir=tmp_path)
    loaded = runstate.load_task(task.id, tmp_path)
    assert loaded.id == task.id
    assert loaded.class_.domain == "coding"
    assert loaded.goal == "roundtrip goal"


def test_manifest_record_artifact(tmp_path):
    task = runstate.create_task("manifest goal", _cls(), runs_dir=tmp_path)
    art = runstate.run_dir(task.id, tmp_path) / "artifacts" / "01-out.txt"
    runstate.atomic_write(art, "hello")
    entry = runstate.record_artifact(task.id, art, producer="executor", runs_dir=tmp_path)
    assert entry["path"] == "artifacts/01-out.txt"
    assert len(entry["sha256"]) == 64
    assert entry["producer"] == "executor"
    manifest = runstate.load_manifest(task.id, tmp_path)
    assert manifest["artifacts"][0]["sha256"] == entry["sha256"]


def test_atomic_write_no_partial(tmp_path):
    target = tmp_path / "sub" / "file.json"
    runstate.atomic_write(target, json.dumps({"ok": True}))
    assert json.loads(target.read_text())["ok"] is True
    # no leftover tmp files
    assert not list((tmp_path / "sub").glob("*.tmp-*"))
