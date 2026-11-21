"""Shared retry and private checkpoint handling for approved text-only requests."""

import json
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel

from judge.matching import _cache_folder, _read_cache, _write_cache
from judge.vision import MODEL_TIMEOUT_SECONDS, VisionClient, _client_from_environment


def parse_text[Result: BaseModel](
    *,
    model: str,
    system: str,
    payload: dict[str, object],
    schema: type[Result],
    client: VisionClient | None,
    cache_dir: Path | None,
    usable: Callable[[Result], bool] | None = None,
) -> Result | None:
    """Checkpoint a schema-valid, usable result for the exact approved request."""
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    folder = _cache_folder(cache_dir) if cache_dir is not None else None
    key = sha256(json.dumps((schema.__name__, model, system, content)).encode("utf-8")).hexdigest()
    if folder is not None:
        cached = _read_cache(folder, key, schema)
        if cached is not None and (usable is None or usable(cached)):
            return cached

    transport = client if client is not None else _client_from_environment()
    messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
    for _attempt in range(2):
        try:
            response = transport.responses.parse(
                model=model,
                input=messages,
                text_format=schema,
                timeout=MODEL_TIMEOUT_SECONDS,
                store=False,
            )
            result = schema.model_validate(response.output_parsed)
        except Exception:
            continue
        if usable is not None and not usable(result):
            continue
        if folder is not None:
            _write_cache(folder, key, result)
        return result
    return None
