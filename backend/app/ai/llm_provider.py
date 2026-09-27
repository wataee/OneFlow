import json
import httpx
from typing import Any, Dict, Optional
from app.ai.provider import AIProvider
from app.ai.schemas import (
    AIClassifyInput,
    AIExtractInput,
    AIMatchInput,
    AIProcessInput,
    AIResult,
)
from app.core.config import settings


class LLMProvider(AIProvider):
    """
    OpenAI-compatible LLM Provider.
    Calls OpenAI / Azure / local vLLM endpoint via httpx.
    """

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.OPENAI_API_KEY or ""
        self.base_url = (base_url or settings.OPENAI_BASE_URL).rstrip("/")
        self.model = model or settings.OPENAI_MODEL

    async def _call_chat_completions(self, system_prompt: str, user_content: str) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.1,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            raw_text = data["choices"][0]["message"]["content"]
            parsed = json.loads(raw_text)
            return {"parsed": parsed, "raw": raw_text}

    async def process(self, input_data: AIProcessInput) -> AIResult:
        system_prompt = (
            "You are a backend processing engine. Analyze the task payload and return JSON with:\n"
            "- 'data': structured key-value findings\n"
            "- 'confidence': float between 0.0 and 1.0 representing model certainty"
        )
        user_prompt = f"Task type: {input_data.task_type}\nPayload: {json.dumps(input_data.payload)}"
        call_res = await self._call_chat_completions(system_prompt, user_prompt)
        parsed = call_res["parsed"]
        confidence = float(parsed.get("confidence", 0.90))
        # Ensure confidence is clamped to [0.0, 1.0]
        confidence = max(0.0, min(1.0, confidence))
        return AIResult(
            data=parsed.get("data", parsed),
            confidence=confidence,
            raw_response=call_res["raw"],
            model_used=self.model,
        )

    async def classify(self, input_data: AIClassifyInput) -> AIResult:
        system_prompt = "Classify text into candidate labels. Return JSON with 'label' and 'confidence' (0.0-1.0)."
        user_prompt = f"Labels: {input_data.candidate_labels}\nText: {input_data.content}"
        call_res = await self._call_chat_completions(system_prompt, user_prompt)
        parsed = call_res["parsed"]
        confidence = float(parsed.get("confidence", 0.85))
        return AIResult(
            data={"label": parsed.get("label", "unknown"), "details": parsed},
            confidence=max(0.0, min(1.0, confidence)),
            raw_response=call_res["raw"],
            model_used=self.model,
        )

    async def extract(self, input_data: AIExtractInput) -> AIResult:
        system_prompt = "Extract requested fields from document text. Return JSON with 'fields' and 'confidence'."
        user_prompt = f"Target fields: {input_data.target_fields}\nText: {input_data.content}"
        call_res = await self._call_chat_completions(system_prompt, user_prompt)
        parsed = call_res["parsed"]
        return AIResult(
            data=parsed.get("fields", parsed),
            confidence=float(parsed.get("confidence", 0.88)),
            raw_response=call_res["raw"],
            model_used=self.model,
        )

    async def match(self, input_data: AIMatchInput) -> AIResult:
        system_prompt = "Match source item against candidate items. Return JSON with 'matched_id' and 'confidence'."
        user_prompt = f"Source: {json.dumps(input_data.source_item)}\nCandidates: {json.dumps(input_data.candidate_items)}"
        call_res = await self._call_chat_completions(system_prompt, user_prompt)
        parsed = call_res["parsed"]
        return AIResult(
            data=parsed,
            confidence=float(parsed.get("confidence", 0.90)),
            raw_response=call_res["raw"],
            model_used=self.model,
        )
