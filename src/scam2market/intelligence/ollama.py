from typing import Any

import httpx

from scam2market.security.guardrails import GuardrailDecision, inspect_untrusted_text


class OllamaClient:
    """Small local-model client for advisory enrichment only."""

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.1:8b",
        timeout_seconds: float = 30.0,
        max_prompt_characters: int = 6000,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model = model
        self._max_prompt_characters = max_prompt_characters
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout_seconds
        )
        self._owns_client = client is None

    async def generate_guarded(self, prompt: str) -> tuple[str | None, GuardrailDecision]:
        decision = inspect_untrusted_text(prompt, max_length=self._max_prompt_characters)
        if not decision.accepted:
            return None, decision
        response = await self._client.post(
            "/api/generate",
            json={
                "model": self._model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0, "top_p": 0.1},
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Ollama response must be a JSON object")
        text = payload.get("response")
        return str(text).strip() if text else None, decision

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def advisory_prompt(instruction: str, evidence: dict[str, Any]) -> str:
    return (
        "You are an advisory summarizer for Scam2Market. "
        "Use only the provided evidence. Do not invent facts, alter scores, or issue final decisions.\n"
        f"Task: {instruction}\n"
        f"Evidence: {evidence}\n"
        "Return a concise explanation with uncertainty where evidence is incomplete."
    )
