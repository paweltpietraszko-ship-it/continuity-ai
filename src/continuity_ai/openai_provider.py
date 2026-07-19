'''OpenAI Responses API adapter.'''
from __future__ import annotations

import json
import os
from typing import Any, cast

from continuity_ai.domain import EvidenceSpan, ReasoningEvidence
from continuity_ai.errors import ProviderError
from continuity_ai.prompts import (
    PROMPTS,
    REASONING_PROMPT_ID,
    REASONING_RESPONSE_SCHEMA_NAME,
    reasoning_response_schema,
)
from continuity_ai.reasoning_contract import AnalysisCandidate

MODEL_ENVIRONMENT_VARIABLE = 'CONTINUITY_OPENAI_MODEL'
REQUEST_SCHEMA_VERSION = '1.0'


def build_request_document(
    evidence: tuple[ReasoningEvidence, ...],
    spans: tuple[EvidenceSpan, ...],
    question: str,
) -> dict[str, Any]:
    '''Build the provider-neutral, closed-world request document.'''
    return {
        'request_schema_version': REQUEST_SCHEMA_VERSION,
        'question': question,
        'evidence': [
            {
                'id': item.evidence_id,
                'type': item.source_type,
                'author': item.author_or_actor,
                'timestamp': item.timestamp,
                'title': item.title,
                'provenance': item.provenance,
            }
            for item in evidence
        ],
        'spans': [
            {
                'id': span.span_id,
                'evidence_id': span.evidence_id,
                'text': span.text,
                'index': span.index,
            }
            for span in spans
        ],
    }


def serialize_request_document(
    evidence: tuple[ReasoningEvidence, ...],
    spans: tuple[EvidenceSpan, ...],
    question: str,
) -> str:
    '''Serialize the request deterministically while preserving Unicode.'''
    return json.dumps(
        build_request_document(evidence, spans, question),
        ensure_ascii=False,
        separators=(',', ':'),
    )


def _response_has_refusal(response: Any) -> bool:
    if getattr(response, 'refusal', None):
        return True
    for output_item in getattr(response, 'output', ()) or ():
        if getattr(output_item, 'type', None) != 'message':
            continue
        for content_item in getattr(output_item, 'content', ()) or ():
            if (
                getattr(content_item, 'type', None) == 'refusal'
                or getattr(content_item, 'refusal', None)
            ):
                return True
    return False


class OpenAIReasoningProvider:
    provider_id = 'openai-responses'

    def __init__(self, client: Any | None = None) -> None:
        model = os.environ.get(MODEL_ENVIRONMENT_VARIABLE, '').strip()
        if not model:
            raise ProviderError()
        self.model = model

        if client is None:
            try:
                from openai import OpenAI

                client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))
            except Exception:
                raise ProviderError() from None
        self.client = client

    def analyze(
        self,
        evidence: tuple[ReasoningEvidence, ...],
        spans: tuple[EvidenceSpan, ...],
        question: str,
    ) -> AnalysisCandidate:
        request_input = serialize_request_document(evidence, spans, question)
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=PROMPTS[REASONING_PROMPT_ID],
                input=request_input,
                text={
                    'format': {
                        'type': 'json_schema',
                        'name': REASONING_RESPONSE_SCHEMA_NAME,
                        'strict': True,
                        'schema': reasoning_response_schema(),
                    }
                },
                store=False,
                tools=[],
            )
        except Exception:
            raise ProviderError() from None

        try:
            if getattr(response, 'status', None) != 'completed':
                raise ProviderError()
            if _response_has_refusal(response):
                raise ProviderError()
            output_text = response.output_text
            if not isinstance(output_text, str) or not output_text.strip():
                raise ProviderError()
            parsed = json.loads(output_text)
            if not isinstance(parsed, dict):
                raise ProviderError()
            return cast(AnalysisCandidate, parsed)
        except ProviderError:
            raise
        except Exception:
            raise ProviderError() from None
