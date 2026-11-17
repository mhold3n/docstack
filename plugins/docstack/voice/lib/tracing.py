"""Langfuse tracing for voice CLI model calls.

Agent note: profile synthesis and review call the Claude CLI. Picklist calls
the Cursor agent CLI. Neither client is an OpenAI/LangChain SDK, so there is
no framework integration to wrap. This module records those subprocesses with
Langfuse Python SDK 5.2.0 (``start_as_current_observation``).

Importing this module does not import Langfuse and does not read secrets.
``client()`` loads ``.env`` in the voice root, then constructs the singleton.
Set ``LANGFUSE_PUBLIC_KEY``, ``LANGFUSE_SECRET_KEY``, and ``LANGFUSE_BASE_URL``
in the environment or in that file. Do not log those values.

Short-lived ``voicectl`` processes must ``flush()`` before exit. ``operation``
flushes when the root span ends so the MCP server also delivers traces.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# Langfuse usage buckets are exclusive. Anthropic reports input_tokens apart
# from cache reads and cache writes, which matches that contract.
_INPUT_KEYS = ("input_tokens", "inputTokens", "prompt_tokens", "promptTokens")
_OUTPUT_KEYS = (
    "output_tokens",
    "outputTokens",
    "completion_tokens",
    "completionTokens",
)
_CACHE_READ_KEYS = (
    "cache_read_input_tokens",
    "cacheReadInputTokens",
    "cache_read_tokens",
    "cacheReadTokens",
)
_CACHE_WRITE_KEYS = (
    "cache_creation_input_tokens",
    "cacheCreationInputTokens",
    "cache_write_tokens",
    "cacheWriteTokens",
)

_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\b")
_PHONE = re.compile(r"\b\d{3}[-. ]?\d{3}[-. ]?\d{4}\b")
_CARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_SECRET = re.compile(
    r"(?:sk-lf-|pk-lf-|sk-ant-|sk-proj-)[A-Za-z0-9_-]{8,}"
    r"|Bearer\s+[A-Za-z0-9._\-]{8,}"
)

_client: Any = None
_warned = False


class _NullObs:
    """Stand-in when Langfuse credentials are absent. Updates are discarded."""

    def update(self, **_kwargs: Any) -> _NullObs:
        return self


def _voice_root() -> Path:
    return Path(os.environ.get("CURSOR_VOICE_ROOT", Path.home() / ".cursor" / "voice"))


def _load_env_file(path: Path) -> None:
    """Set missing variables from a dotenv file. Existing env wins.

    Agent note: values stay in the process environment. This function does not
    return them and does not log them.
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value


def _prepare_env() -> None:
    """Load voice-root .env, then align host and default the trace environment."""
    _load_env_file(_voice_root() / ".env")
    base = os.environ.get("LANGFUSE_BASE_URL")
    if base and not os.environ.get("LANGFUSE_HOST"):
        # CLI reads LANGFUSE_HOST. The Python SDK reads LANGFUSE_BASE_URL.
        os.environ["LANGFUSE_HOST"] = base
    # Local voicectl and the voice MCP are not a deployed production service.
    os.environ.setdefault("LANGFUSE_TRACING_ENVIRONMENT", "development")


def configured() -> bool:
    """True when both project API keys are present. Does not print them."""
    _prepare_env()
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY")) and bool(
        os.environ.get("LANGFUSE_SECRET_KEY")
    )


def _warn_unconfigured() -> None:
    global _warned
    if _warned:
        return
    _warned = True
    print(
        "Langfuse tracing skipped: set LANGFUSE_PUBLIC_KEY, "
        "LANGFUSE_SECRET_KEY, and LANGFUSE_BASE_URL "
        "(environment or .cursor/voice/.env).",
        file=sys.stderr,
    )


def mask_otel_spans(*, params: Any) -> Any:
    """Redact emails, phone numbers, card numbers, and API-key shapes at export.

    Agent note: writing samples stay in the trace. Only matching substrings
    inside exported string attributes change. A failure here must not raise;
    the SDK drops the batch if this hook raises.
    """
    try:
        from langfuse.types import MaskOtelSpansResult, OtelSpanPatch
    except Exception:
        return None
    patches: dict[Any, Any] = {}
    try:
        spans = params.spans
    except Exception:
        return None
    for identifier, span in spans.items():
        replacements: dict[str, str] = {}
        attributes = getattr(span, "attributes", None) or {}
        for key, value in attributes.items():
            if not isinstance(value, str):
                continue
            masked = _SECRET.sub("[REDACTED SECRET]", value)
            masked = _EMAIL.sub("[REDACTED EMAIL]", masked)
            masked = _PHONE.sub("[REDACTED PHONE]", masked)
            masked = _CARD.sub("[REDACTED CARD]", masked)
            if masked != value:
                replacements[key] = masked
        if replacements:
            patches[identifier] = OtelSpanPatch(set_attributes=replacements)
    if not patches:
        return None
    return MaskOtelSpansResult(span_patches=patches)


def client() -> Any:
    """Return the process-wide Langfuse client, or None when keys are absent.

    Agent note: construct this after ``_prepare_env``. The first ``Langfuse()``
    call with a public key wins the singleton, including the masking hook.
    """
    global _client
    if _client is not None:
        return _client
    if not configured():
        return None
    from langfuse import Langfuse

    _client = Langfuse(mask_otel_spans=mask_otel_spans)
    return _client


def flush() -> None:
    """Deliver queued spans. Safe when tracing never started."""
    if _client is None:
        return
    _client.flush()


def _status(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:500]


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    return int(value)


def _first_int(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        found = _as_int(mapping.get(key))
        if found is not None:
            return found
    return None


def cli_envelope(raw: str) -> dict[str, Any] | None:
    """Parse a CLI stdout object. Non-JSON and non-objects return None."""
    text = raw.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        return data
    return None


def model_from_payload(payload: dict[str, Any] | None) -> str | None:
    """Model id from a Claude Code or Cursor agent JSON envelope."""
    if not isinstance(payload, dict):
        return None
    model = payload.get("model")
    if isinstance(model, str) and model.strip():
        return model.strip()
    usage = payload.get("modelUsage")
    if isinstance(usage, dict):
        names = [key for key in usage if isinstance(key, str) and key.strip()]
        if len(names) == 1:
            return names[0]
    return None


def usage_from_payload(payload: dict[str, Any] | None) -> dict[str, int] | None:
    """Map a CLI usage object onto exclusive Langfuse usage buckets.

    Agent note: returns None when the envelope has no token counts. Callers
    must not invent zeros. ``input`` is the provider's non-cached input count.
    """
    if not isinstance(payload, dict):
        return None
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    details: dict[str, int] = {}
    input_tokens = _first_int(usage, _INPUT_KEYS)
    output_tokens = _first_int(usage, _OUTPUT_KEYS)
    cache_read = _first_int(usage, _CACHE_READ_KEYS)
    cache_write = _first_int(usage, _CACHE_WRITE_KEYS)
    if input_tokens is None and output_tokens is None:
        return None
    if input_tokens is not None:
        details["input"] = input_tokens
    if output_tokens is not None:
        details["output"] = output_tokens
    if cache_read:
        details["cache_read_input_tokens"] = cache_read
    if cache_write:
        details["cache_creation_input_tokens"] = cache_write
    return details


def chat_messages(system: str, user: str) -> list[dict[str, str]]:
    """OpenAI-style messages so the Langfuse UI renders roles, not a raw blob."""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def assistant_message(content: str) -> list[dict[str, str]]:
    return [{"role": "assistant", "content": content}]


def _short_meta(metadata: Mapping[str, Any] | None) -> dict[str, str] | None:
    """Keep propagate_attributes metadata inside the SDK's 200-character cap."""
    if not metadata:
        return None
    kept: dict[str, str] = {}
    for key, value in metadata.items():
        text = str(value)
        if len(key) <= 200 and len(text) <= 200:
            kept[key] = text
    return kept or None


@contextmanager
def operation(
    *,
    name: str,
    feature: str,
    input: Any,
    version: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Iterator[Any]:
    """Root span for one unit of work. Sets the trace name, feature tag, and input.

    Agent note: ``propagate_attributes`` wraps span creation so the root span
    receives the tag. Cache hits must not call this. Mock provider must not
    call this. ``feature`` is the stable tag (``voice-review``,
    ``voice-profile``, ``picklist-judge``).
    """
    langfuse = client()
    if langfuse is None:
        _warn_unconfigured()
        yield _NullObs()
        return
    from langfuse import propagate_attributes

    meta = {"feature": feature}
    extra = _short_meta(metadata)
    if extra:
        meta.update(extra)
    version_text = version if version else None
    try:
        with propagate_attributes(
            tags=[feature],
            trace_name=name,
            environment=os.environ.get("LANGFUSE_TRACING_ENVIRONMENT"),
            version=version_text,
            metadata=meta,
        ):
            with langfuse.start_as_current_observation(
                as_type="span",
                name=name,
                input=input,
            ) as span:
                try:
                    yield span
                except Exception as exc:
                    span.update(level="ERROR", status_message=_status(exc))
                    raise
    finally:
        langfuse.flush()


@contextmanager
def agent_run(*, name: str, input: Any) -> Iterator[Any]:
    """One subagent execution. Nest the model generation under this observation."""
    langfuse = client()
    if langfuse is None:
        yield _NullObs()
        return
    with langfuse.start_as_current_observation(
        as_type="agent",
        name=name,
        input=input,
    ) as obs:
        try:
            yield obs
        except Exception as exc:
            obs.update(level="ERROR", status_message=_status(exc))
            raise


@contextmanager
def model_call(
    *,
    name: str,
    messages: list[dict[str, str]],
    model: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Iterator[Any]:
    """One model invocation. ``messages`` is the prompt the CLI actually received."""
    langfuse = client()
    if langfuse is None:
        yield _NullObs()
        return
    kwargs: dict[str, Any] = {
        "as_type": "generation",
        "name": name,
        "input": messages,
    }
    if model:
        kwargs["model"] = model
    if metadata:
        kwargs["metadata"] = dict(metadata)
    with langfuse.start_as_current_observation(**kwargs) as obs:
        try:
            yield obs
        except Exception as exc:
            obs.update(
                level="ERROR",
                status_message=_status(exc),
                output={"error": _status(exc)},
            )
            raise


def apply_cli_result(
    obs: Any,
    *,
    envelope: dict[str, Any] | None,
    output_text: str,
    configured_model: str | None,
) -> None:
    """Write assistant output, detected model, and token usage onto a generation.

    Agent note: configured model is the fallback when the CLI envelope omits
    one. Usage is omitted when the envelope has no counts.
    """
    detected = model_from_payload(envelope)
    model = detected or (configured_model or None)
    usage = usage_from_payload(envelope)
    update: dict[str, Any] = {"output": assistant_message(output_text)}
    if model:
        update["model"] = model
    if usage:
        update["usage_details"] = usage
    thinking = None
    if isinstance(envelope, dict):
        for key in ("thinking", "reasoning"):
            value = envelope.get(key)
            if isinstance(value, str) and value.strip():
                thinking = value
                break
    if thinking:
        update["metadata"] = {"thinking": thinking[:8000]}
    obs.update(**update)
