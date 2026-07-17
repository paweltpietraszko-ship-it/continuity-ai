"""OpenAI Responses API adapter."""
from __future__ import annotations
import os
from typing import Any
from continuity_ai.errors import ProviderError
class OpenAIReasoningProvider:
    provider_id = "openai-responses"
    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            from openai import OpenAI
            client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        self.client=client
    def analyze(self, evidence, spans, question: str) -> dict[str, Any]:
        model=os.environ.get("CONTINUITY_OPENAI_MODEL")
        if not model: raise ProviderError()
        try:
            resp=self.client.responses.create(model=model, input=[{"role":"user","content":question}], text={"format":{"type":"json_schema","name":"analysis","schema":{"type":"object"},"strict":True}}, store=False, tools=[])
            return resp.output_parsed if hasattr(resp,"output_parsed") else resp.output[0].content[0].parsed
        except Exception as exc: raise ProviderError() from exc
