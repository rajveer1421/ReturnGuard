"""Gemini access: timeouts, retries with backoff, schema-validated output,
per-call telemetry, and an optional on-disk cache for evaluation runs."""
import base64
import hashlib
import io
import json
import logging
import re
import threading
import time
from dataclasses import asdict, dataclass
from functools import lru_cache

from langchain_core.messages import HumanMessage, SystemMessage
from PIL import Image
from pydantic import BaseModel

from returnguard import config

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """The model could not produce a valid answer after all retries."""

    def __init__(self, agent: str, cause: Exception, record: "CallRecord"):
        super().__init__(f"{agent}: {type(cause).__name__}: {cause}")
        self.record = record


@dataclass
class CallRecord:
    agent: str
    model: str
    ok: bool
    cached: bool
    attempts: int
    latency_s: float
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None

    def to_dict(self):
        return asdict(self)


@lru_cache(maxsize=4)
def _chat(model: str):
    from langchain_google_genai import ChatGoogleGenerativeAI
    temperature = config.LLM_TEMPERATURE
    if temperature is None:
        temperature = 1.0 if model.startswith("gemini-3") else 0.0
    # retries are handled below so that schema-validation failures are retried too
    return ChatGoogleGenerativeAI(model=model, temperature=temperature, timeout=config.LLM_TIMEOUT_S, max_retries=0)


def image_part(img: Image.Image, max_side: int = 1024, background=(236, 236, 236)) -> dict:
    """Encode an image (RGBA cut-outs are flattened onto a neutral grey) as a message part."""
    if img.mode == "RGBA":
        canvas = Image.new("RGB", img.size, background)
        canvas.paste(img, mask=img.getchannel("A"))
        img = canvas
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}}


def text_part(text: str) -> dict:
    return {"type": "text", "text": text}


def _is_rate_limit(err: Exception) -> bool:
    msg = str(err)
    return "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower()


def _is_permanent(err: Exception) -> bool:
    """Errors a retry can never fix: bad key, blocked project, unknown model."""
    msg = str(err)
    return any(s in msg for s in ("PERMISSION_DENIED", "UNAUTHENTICATED", "API_KEY_INVALID", "NOT_FOUND", " 401 ", " 403 ", " 404 "))


def _is_overloaded(err: Exception) -> bool:
    """Server-side busy/timeouts ('high demand', 503/504): worth retrying, but not immediately."""
    msg = str(err)
    return any(s in msg for s in ("UNAVAILABLE", "DEADLINE_EXCEEDED", "503", "504", "high demand"))


def _suggested_delay(err: Exception) -> float:
    """Gemini's 429 errors say how long to wait ('retryDelay': '37s' / 'retry in 36.5s')."""
    m = re.search(r"retry(?:Delay'?:\s*'|\s+in\s+)(\d+(?:\.\d+)?)s", str(err))
    return float(m.group(1)) + 1 if m else 0.0


_rate_lock = threading.Lock()
_last_call = 0.0


def _respect_rate_limit():
    """Space calls at least RG_LLM_MIN_INTERVAL_S apart (free-tier keys allow a few per minute)."""
    global _last_call
    with _rate_lock:
        wait = config.LLM_MIN_INTERVAL_S - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def call_structured(agent: str, schema: type[BaseModel], system: str, parts: list[dict],
                    model: str | None = None) -> tuple[BaseModel, CallRecord]:
    model = model or config.LLM_MODEL
    key = hashlib.sha256(json.dumps([model, schema.model_json_schema(), system, parts], sort_keys=True).encode()).hexdigest()
    cache_path = config.CACHE_DIR / "llm" / f"{key}.json"
    if config.LLM_CACHE and cache_path.exists():
        saved = json.loads(cache_path.read_text(encoding="utf-8"))
        rec = CallRecord(agent, model, True, True, saved["attempts"], saved["latency_s"], saved["input_tokens"],
                         saved["output_tokens"])
        return schema.model_validate(saved["parsed"]), rec

    try:
        runnable = _chat(model).with_structured_output(schema, include_raw=True)
    except Exception as e:  # e.g. no GOOGLE_API_KEY: fail like any other unavailable agent, don't crash the request
        raise LLMError(agent, e, CallRecord(agent, model, False, False, 0, 0.0, 0, 0, error=f"{type(e).__name__}: {e}")) from e
    messages = [SystemMessage(content=system), HumanMessage(content=parts)]
    start = time.monotonic()
    last_err: Exception | None = None
    for attempt in range(1, config.LLM_MAX_RETRIES + 2):
        try:
            _respect_rate_limit()
            out = runnable.invoke(messages)
            parsed = out.get("parsed")
            if parsed is None:
                raise ValueError(f"output did not match {schema.__name__}: {out.get('parsing_error')}")
            usage = getattr(out.get("raw"), "usage_metadata", None) or {}
            rec = CallRecord(agent, model, True, False, attempt, round(time.monotonic() - start, 2),
                             int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)))
            if config.LLM_CACHE:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps({"parsed": parsed.model_dump(), "attempts": attempt,
                                                  "latency_s": rec.latency_s,
                                                  "input_tokens": rec.input_tokens,
                                                  "output_tokens": rec.output_tokens}), encoding="utf-8")
            return parsed, rec
        except Exception as err:  # network, timeout, quota, invalid output
            last_err = err
            if attempt > config.LLM_MAX_RETRIES or _is_permanent(err):
                break
            wait = min(60, 2 ** attempt)
            if _is_rate_limit(err):
                suggested = _suggested_delay(err)
                if suggested > config.LLM_MAX_WAIT_S:
                    # e.g. daily quota gone ("retry in 79162s"): fail now, the pipeline's fail-safe takes over
                    log.warning("%s: quota exhausted (retry suggested in %.0fs); failing fast", agent, suggested)
                    break
                wait = min(config.LLM_MAX_WAIT_S, max(wait, 20 * attempt, suggested))
            elif _is_overloaded(err):
                wait = min(config.LLM_MAX_WAIT_S, max(wait, 15 * attempt))
            log.warning("%s attempt %d failed (%s); retrying in %ss", agent, attempt, str(err)[:160], wait)
            time.sleep(wait)

    rec = CallRecord(agent, model, False, False, attempt, round(time.monotonic() - start, 2),
                     error=f"{type(last_err).__name__}: {str(last_err)[:300]}")
    raise LLMError(agent, last_err, rec)
