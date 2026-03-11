from __future__ import annotations

from functools import lru_cache
from fastapi import HTTPException

try:
    import language_tool_python
except ImportError:  # pragma: no cover - handled at runtime
    language_tool_python = None

from app.config import LANGUAGE_TOOL_LANGUAGE, REQUIRE_LANGUAGE_TOOL


@lru_cache(maxsize=1)
def _get_language_tool():
    if language_tool_python is None:
        if REQUIRE_LANGUAGE_TOOL:
            raise HTTPException(status_code=503, detail="Grammar service unavailable")
        return None

    try:
        return language_tool_python.LanguageTool(LANGUAGE_TOOL_LANGUAGE)
    except Exception:
        if REQUIRE_LANGUAGE_TOOL:
            raise HTTPException(status_code=503, detail="Grammar service unavailable")
        return None


def correct_grammar(text: str) -> str:
    tool = _get_language_tool()

    if tool is None:
        return text

    try:
        return tool.correct(text)
    except Exception:
        if REQUIRE_LANGUAGE_TOOL:
            raise HTTPException(status_code=503, detail="Grammar service unavailable")
        return text


def warm_grammar_service():
    _get_language_tool()
