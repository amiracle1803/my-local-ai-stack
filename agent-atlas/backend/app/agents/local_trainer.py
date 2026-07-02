"""
Local Model Trainer: collects successful traces and exports training datasets.
Training itself is triggered manually (or via CLI).
"""
import json
import logging
from pathlib import Path
from typing import Any

from app.agents.base import BaseAgent
from app.models.message import AgentMessage
from app.storage.database import get_connection

logger = logging.getLogger("agent_atlas.agents.local_trainer")

TRACES_DIR = Path(__file__).parent.parent.parent.parent / "data" / "traces"


class LocalModelTrainerAgent(BaseAgent):
    agent_id = "local_model_trainer"

    async def handle(self, message: AgentMessage) -> Any:
        op = message.payload.get("op", "prepare")
        if op == "prepare":
            return self._prepare_dataset()
        if op == "status":
            return self._status()
        return {"error": f"Unknown op: {op}"}

    def _prepare_dataset(self) -> dict:
        TRACES_DIR.mkdir(parents=True, exist_ok=True)
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT agent_id, input_json, output_json FROM agent_traces WHERE success = 1"
            ).fetchall()
        finally:
            conn.close()

        conversations = []
        for row in rows:
            try:
                inp = json.loads(row["input_json"] or "null")
                out = json.loads(row["output_json"] or "null")
                if inp and out:
                    conversations.append({"messages": [
                        {"role": "user", "content": str(inp)},
                        {"role": "assistant", "content": str(out)},
                    ]})
            except Exception:
                continue

        out_path = TRACES_DIR / "training_dataset.jsonl"
        with open(out_path, "w", encoding="utf-8") as f:
            for conv in conversations:
                f.write(json.dumps(conv) + "\n")

        return {"status": "prepared", "examples": len(conversations), "path": str(out_path)}

    def _status(self) -> dict:
        out_path = TRACES_DIR / "training_dataset.jsonl"
        if out_path.exists():
            with open(out_path, encoding="utf-8") as f:
                lines = sum(1 for _ in f)
            return {"dataset_exists": True, "examples": lines}
        return {"dataset_exists": False, "examples": 0}
