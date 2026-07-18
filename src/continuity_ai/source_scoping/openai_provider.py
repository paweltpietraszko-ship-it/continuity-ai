"""OpenAI Responses API adapter for generic project source scoping."""
from __future__ import annotations

import json
import os
from typing import Any

from continuity_ai.errors import ProviderError
from continuity_ai.source_scoping.prompts import (
    SOURCE_SCOPING_PROMPT,
    SOURCE_SCOPING_SCHEMA_NAME,
    source_scoping_response_schema,
)

MODEL_ENVIRONMENT_VARIABLE = "CONTINUITY_SOURCE_SCOPING_OPENAI_MODEL"
REQUEST_SCHEMA_VERSION = "1.0"


def build_request_document(
    target_project: str, evidence: Any, spans: Any
) -> dict[str, Any]:
    return {
        "request_schema_version": REQUEST_SCHEMA_VERSION,
        "target_project": target_project,
        "evidence": [
            {
                "id": item.evidence_id,
                "type": item.source_type,
                "author": item.author_or_actor,
                "timestamp": item.timestamp,
                "title": item.title,
                "provenance": item.provenance,
            }
            for item in evidence
        ],
        "spans": [
            {
                "id": span.span_id,
                "evidence_id": span.evidence_id,
                "text": span.text,
                "index": span.index,
            }
            for span in spans
        ],
    }


def serialize_request_document(target_project: str, evidence: Any, spans: Any) -> str:
    return json.dumps(
        build_request_document(target_project, evidence, spans),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _response_has_refusal(response: Any) -> bool:
    if getattr(response, "refusal", None):
        return True
    for output_item in getattr(response, "output", ()) or ():
        if getattr(output_item, "type", None) != "message":
            continue
        for content_item in getattr(output_item, "content", ()) or ():
            if (
                getattr(content_item, "type", None) == "refusal"
                or getattr(content_item, "refusal", None)
            ):
                return True
    return False


class OpenAISourceScopingProvider:
    provider_id = "openai-source-scoping-v1"

    def __init__(self, client: Any | None = None, model: str | None = None) -> None:
        configured_model = (
            model
            if model is not None
            else os.environ.get(MODEL_ENVIRONMENT_VARIABLE, "")
        )
        if not isinstance(configured_model, str) or not configured_model.strip():
            raise ProviderError()
        self.model = configured_model.strip()
        if client is None:
            try:
                from openai import OpenAI

                client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
            except Exception:
                raise ProviderError() from None
        self.client = client

    def classify(
        self, target_project: str, evidence: Any, spans: Any
    ) -> dict[str, Any]:
        request_input = serialize_request_document(target_project, evidence, spans)
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=SOURCE_SCOPING_PROMPT,
                input=request_input,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": SOURCE_SCOPING_SCHEMA_NAME,
                        "strict": True,
                        "schema": source_scoping_response_schema(),
                    }
                },
                store=False,
                tools=[],
            )
        except Exception:
            raise ProviderError() from None

        try:
            if (
                getattr(response, "status", None) != "completed"
                or _response_has_refusal(response)
            ):
                raise ProviderError()
            output_text = response.output_text
            if not isinstance(output_text, str) or not output_text.strip():
                raise ProviderError()
            parsed = json.loads(output_text)
            if not isinstance(parsed, dict):
                raise ProviderError()
            return parsed
        except ProviderError:
            raise
        except Exception:
            raise ProviderError() from None
