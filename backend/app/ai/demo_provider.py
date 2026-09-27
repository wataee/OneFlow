import hashlib
import json
from typing import Any, Dict
from app.ai.provider import AIProvider
from app.ai.schemas import (
    AIClassifyInput,
    AIExtractInput,
    AIMatchInput,
    AIProcessInput,
    AIResult,
)


class DemoAIProvider(AIProvider):
    """
    Deterministic AI Provider implementation for local demos and integration testing.
    Outputs are 100% reproducible and computed deterministically via stable payload hashing.
    No network connection or API keys required.
    """

    MODEL_NAME = "demo-deterministic-engine-v1"

    def _hash_payload(self, data: Any) -> int:
        serialized = json.dumps(data, sort_keys=True, default=str)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return int(digest[:8], 16)

    async def process(self, input_data: AIProcessInput) -> AIResult:
        if input_data.payload.get("trigger_failure") is True:
            raise RuntimeError("Simulated processing error in DemoAIProvider (trigger_failure flag)")

        # Allow explicit control for test/demo scenarios
        if input_data.payload.get("force_review") is True or input_data.payload.get("trigger_review") is True:
            confidence = 0.70  # Explicitly below standard threshold to trigger human-in-the-loop review
        elif "confidence" in input_data.payload:
            confidence = float(input_data.payload["confidence"])
        else:
            # Deterministic calculation based on payload hash
            h = self._hash_payload(input_data.payload)
            # Produces values in [0.75, 0.99] deterministically
            confidence = round(0.75 + (h % 25) / 100.0, 2)

        result_data: Dict[str, Any] = {
            "processed_type": input_data.task_type,
            "status": "success",
            "summary": f"Deterministic automated evaluation for {input_data.task_type}",
            "attributes_detected": len(input_data.payload.keys()),
            "normalized_fields": {
                k: f"normalized_{v}" if isinstance(v, str) else v
                for k, v in input_data.payload.items()
            },
        }

        return AIResult(
            data=result_data,
            confidence=confidence,
            raw_response=json.dumps(result_data),
            model_used=self.MODEL_NAME,
        )

    async def classify(self, input_data: AIClassifyInput) -> AIResult:
        if not input_data.candidate_labels:
            selected_label = "unknown"
            confidence = 0.50
        else:
            h = self._hash_payload(input_data.content)
            idx = h % len(input_data.candidate_labels)
            selected_label = input_data.candidate_labels[idx]
            confidence = 0.92

        result_data = {
            "label": selected_label,
            "all_scores": {
                label: (0.92 if label == selected_label else round(0.08 / max(1, len(input_data.candidate_labels) - 1), 3))
                for label in input_data.candidate_labels
            },
        }
        return AIResult(
            data=result_data,
            confidence=confidence,
            raw_response=json.dumps(result_data),
            model_used=self.MODEL_NAME,
        )

    async def extract(self, input_data: AIExtractInput) -> AIResult:
        extracted = {}
        for field in input_data.target_fields:
            extracted[field] = f"extracted_value_for_{field}"

        return AIResult(
            data={"fields": extracted},
            confidence=0.89,
            raw_response=json.dumps(extracted),
            model_used=self.MODEL_NAME,
        )

    async def match(self, input_data: AIMatchInput) -> AIResult:
        best_match = input_data.candidate_items[0] if input_data.candidate_items else None
        return AIResult(
            data={"matched_item": best_match, "match_quality": "exact"},
            confidence=0.96,
            raw_response=json.dumps(best_match),
            model_used=self.MODEL_NAME,
        )
