# Pipeline Tools

These are operator tools, not pipeline runtime modules. Run them from the
repository root unless a command says otherwise.

## Validation

- `validate_workflows.py`: validate canonical API workflow templates.
- `check_workflows.py`: inspect ComfyUI UI-format workflows.

## Smoke Tests

- `model_smoke.py`: image model smoke checks.
- `ltx_smoke.py`, `ltx_director_smoke.py`: LTX checks.
- `wan_smoke.py`, `wan22_2f_fresh.py`: Wan checks.
- `director_endframe_smoke.py`, `i2v_shootout.py`: animation comparisons.

## ComfyUI Utilities

- `api2ui.py`, `api_to_ui_converter.py`: API/UI workflow conversion.
- `make_placeholder_inputs.py`: create local smoke-test inputs.
- `generate_viseme_masks.py`: create viseme masks.

## Calibration and Experimental Data

- `nim_calibrate.py`, `nvidia_probe.py`: optional hosted-provider checks.
- `make_character_dataset.py`, `direct_recap.py`: experimental operator tools.
- `compare_local_nim.py`: bounded local-artifact comparison against the
  configured NVIDIA NIM text and vision models; writes a report under the
  project `comparisons/` directory.
- `audit_models.py`: read-only model inventory/checksum/reference audit.
- `probe_cloud_providers.py`: non-generative credential/reachability probe;
  reads replacement credentials only from environment or `.agent-secrets/`.

The n8n importable orchestration workflow is at
`foundation/n8n/olympus-pipeline-run.json`. It checks providers, then starts a
kernel pipeline run; it does not expose credentials or silently enable cloud
generation.

Generated reports, smoke markers, caches, and project media do not belong in
the source workflow directory. The runtime workflow source is always:
`olympus/engines/pipeline/workflows/`.
