from pathlib import Path

from pipeline.config import PipelineConfig
from pipeline.run_contract import artifact_contract_complete, build_run_contract


def test_smoke_contract_is_local_first_and_fingerprinted():
    cfg = PipelineConfig.load()
    contract = build_run_contract(
        cfg,
        Path(__file__).resolve().parents[1] / "prompts",
        "smoke",
    )
    assert contract.profile == "smoke"
    assert contract.animation_enabled is cfg.animation.enabled
    assert "stage2" in contract.stage_artifacts
    assert contract.prompt_files
    assert any(c.capability == "llm" for c in contract.capabilities)


def test_artifact_contract_requires_stage_output(tmp_path):
    assert not artifact_contract_complete(tmp_path, "stage2")
    (tmp_path / "screenplay").mkdir()
    (tmp_path / "screenplay" / "screenplay.json").write_text("{}", encoding="utf-8")
    assert artifact_contract_complete(tmp_path, "stage2")
