#!/usr/bin/env python3
"""Contract tests for Langfuse usage mapping and export masking.

Run with the voice venv, which has langfuse==5.2.0:

    .venv/bin/python tests/test_tracing.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import tracing  # noqa: E402
import voice_core  # noqa: E402
from langfuse import Langfuse  # noqa: E402
from langfuse.types import (  # noqa: E402
    MaskOtelSpansParams,
    OtelSpanData,
    OtelSpanIdentifier,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)


def test_usage_maps_anthropic_buckets() -> None:
    details = tracing.usage_from_payload(
        {
            "usage": {
                "input_tokens": 12,
                "output_tokens": 4,
                "cache_read_input_tokens": 30,
                "cache_creation_input_tokens": 2,
            }
        }
    )
    assert details == {
        "input": 12,
        "output": 4,
        "cache_read_input_tokens": 30,
        "cache_creation_input_tokens": 2,
    }


def test_usage_maps_cursor_camel_case() -> None:
    details = tracing.usage_from_payload(
        {"usage": {"inputTokens": 8, "outputTokens": 3, "cacheReadTokens": 1}}
    )
    assert details == {
        "input": 8,
        "output": 3,
        "cache_read_input_tokens": 1,
    }


def test_usage_missing_is_none() -> None:
    assert tracing.usage_from_payload({"result": "{}"}) is None
    assert tracing.usage_from_payload(None) is None


def test_model_from_model_usage_map() -> None:
    assert (
        tracing.model_from_payload({"modelUsage": {"claude-sonnet-4-5": {"input": 1}}})
        == "claude-sonnet-4-5"
    )
    assert tracing.model_from_payload({"model": "gpt-5"}) == "gpt-5"


def test_mask_redacts_email_and_secret() -> None:
    identifier = OtelSpanIdentifier(trace_id="a" * 32, span_id="b" * 16)
    span = OtelSpanData(
        trace_id=identifier.trace_id,
        span_id=identifier.span_id,
        parent_span_id=None,
        name="review-against-profile",
        instrumentation_scope_name="langfuse-sdk",
        instrumentation_scope_version=None,
        attributes={
            "langfuse.observation.input": (
                "contact max@example.com key sk-lf-abcdefghijklmnopqrstuvwxyz"
            )
        },
        resource_attributes={},
    )
    result = tracing.mask_otel_spans(
        params=MaskOtelSpansParams(spans={identifier: span})
    )
    assert result is not None
    patched = result.span_patches[identifier].set_attributes[
        "langfuse.observation.input"
    ]
    assert "max@example.com" not in patched
    assert "sk-lf-" not in patched
    assert "[REDACTED EMAIL]" in patched
    assert "[REDACTED SECRET]" in patched


def test_picklist_span_tree() -> None:
    """Judge call nests agent under the batch span and generation under the agent.

    Uses an in-memory exporter so the shape can be checked without project keys.
    """
    exporter = InMemorySpanExporter()
    tracing._client = Langfuse(
        public_key="pk-lf-localtest",
        secret_key="sk-lf-localtest",
        base_url="http://127.0.0.1:9",
        environment="development",
        mask_otel_spans=tracing.mask_otel_spans,
        span_exporter=exporter,
    )

    class _Proc:
        returncode = 0
        stderr = ""
        stdout = json.dumps(
            {
                "result": json.dumps({"judgments": []}),
                "model": "gpt-5",
                "usage": {"inputTokens": 4, "outputTokens": 1},
                "thinking": "look at the byline",
            }
        )

    original = voice_core.subprocess.run
    voice_core.subprocess.run = lambda *args, **kwargs: _Proc()
    try:
        with tracing.operation(
            name="judge-picklist",
            feature="picklist-judge",
            input={"batch_id": "b1", "cards": [{"path": "a.pdf"}]},
            version="1",
            metadata={"provider": "cursor-agent"},
        ) as span:
            voice_core.cursor_json(
                "email max@example.com",
                {"cursor": {"bin": "agent", "model": "gpt-5", "timeout_sec": 5}},
                "rubric",
                workspace=Path("/tmp"),
                agent_name="judge-authorship",
            )
            span.update(output={"judgments": []})
        tracing.flush()
        spans = {span.name: span for span in exporter.get_finished_spans()}
        root = spans["judge-picklist"]
        agent = spans["judge-authorship"]
        generation = spans["judge-authorship-completion"]
        assert agent.parent is not None
        assert agent.parent.span_id == root.context.span_id
        assert generation.parent is not None
        assert generation.parent.span_id == agent.context.span_id
        assert generation.attributes["langfuse.observation.type"] == "generation"
        assert agent.attributes["langfuse.observation.type"] == "agent"
        assert generation.attributes["langfuse.observation.model.name"] == "gpt-5"
        usage = generation.attributes["langfuse.observation.usage_details"]
        assert '"input": 4' in usage
        assert '"output": 1' in usage
        blob = " ".join(str(value) for value in generation.attributes.values())
        assert "max@example.com" not in blob
        assert "[REDACTED EMAIL]" in blob
        assert "look at the byline" in blob
        assert root.attributes["langfuse.trace.tags"] == ("picklist-judge",)
        assert root.attributes["langfuse.environment"] == "development"
    finally:
        voice_core.subprocess.run = original
        tracing._client.shutdown()
        tracing._client = None


def main() -> None:
    test_usage_maps_anthropic_buckets()
    test_usage_maps_cursor_camel_case()
    test_usage_missing_is_none()
    test_model_from_model_usage_map()
    test_mask_redacts_email_and_secret()
    test_picklist_span_tree()
    print("tracing_ok")


if __name__ == "__main__":
    main()
