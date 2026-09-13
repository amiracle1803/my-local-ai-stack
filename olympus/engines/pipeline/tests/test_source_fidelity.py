import json

from pipeline.source_fidelity import analyze
from pipeline.story_contract import write_source_manifest, write_beats, verify_source_manifest, repin_source_manifest


SOURCE = """The Bloodline System. Gustav enters the arena. Gustav stands on the cliff. A meteor strikes. The system interface appears and he says I accept. An unknown man searches for him. Gustav gains bloodline acquisition."""


def _project(tmp_path, screenplay):
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "script.txt").write_text(SOURCE, encoding="utf-8")
    (tmp_path / "screenplay").mkdir()
    (tmp_path / "screenplay" / "screenplay.json").write_text(json.dumps(screenplay), encoding="utf-8")
    return tmp_path


def test_bloodline_fidelity_gate_accepts_required_order(tmp_path):
    output = "arena Gustav cliff meteor system interface I accept unknown man bloodline acquisition MBO Plankton City"
    report = analyze(_project(tmp_path, {"scenes": [{"summary": output}]}))
    assert report.passed
    assert report.score >= 0.75


def test_bloodline_fidelity_gate_rejects_unrelated_story(tmp_path):
    output = "Kael and Mira fight with a soulchain in Luminara against Veylan Drek"
    project = _project(tmp_path, {"scenes": [{"summary": output}]})
    (project / "fidelity_rules.json").write_text(json.dumps({"required": ["Gustav"], "prohibited": ["Kael", "Mira"], "hard_fail": True}), encoding="utf-8")
    report = analyze(project)
    assert not report.passed
    assert "Gustav" in report.required_missing
    assert report.score < 0.65


def test_project_rules_reject_invented_props(tmp_path):
    project = _project(tmp_path, {"scenes": [{"summary": "Gustav enters the arena with a blade"}]})
    (project / "fidelity_rules.json").write_text(json.dumps({"prohibited": ["blade"], "hard_fail": True}), encoding="utf-8")
    report = analyze(project)
    assert not report.passed
    assert "blade" in report.prohibited_found


def test_source_manifest_is_immutable(tmp_path):
    project = _project(tmp_path, {"scenes": []})
    first = write_source_manifest(project)
    assert first.sha256
    (project / "input" / "script.txt").write_text("changed", encoding="utf-8")
    with __import__("pytest").raises(RuntimeError):
        write_source_manifest(project)


def test_verify_source_manifest_rejects_intake_mutation(tmp_path):
    project = _project(tmp_path, {"scenes": []})
    write_source_manifest(project)
    (project / "input" / "script.txt").write_text("mutated", encoding="utf-8")
    with __import__("pytest").raises(RuntimeError):
        verify_source_manifest(project)


def test_repin_source_manifest_accepts_generated_script(tmp_path):
    project = _project(tmp_path, {"scenes": []})
    write_source_manifest(project)
    (project / "input" / "script.txt").write_text(
        "--- [SCENE 1: Reborn] ---\nGustav wakes in the arena.", encoding="utf-8"
    )
    manifest = repin_source_manifest(project)
    assert manifest.scene_count == 1
    verify_source_manifest(project)


def test_story_beats_are_written_and_linked(tmp_path):
    project = _project(tmp_path, {"scenes": [{"id": "sc-001", "shots": [{"id": "sh-001-01", "beat": "Gustav sees the meteor"}]}]})
    screenplay = json.loads((project / "screenplay" / "screenplay.json").read_text())
    beats = write_beats(project, screenplay)
    assert beats[0].id == "beat-0001"
    assert screenplay["scenes"][0]["shots"][0]["beat_ids"] == ["beat-0001"]
    assert (project / "screenplay" / "story_beats.json").exists()
