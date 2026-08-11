import re
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def int_param(req: Request, name: str, default: int | None = None) -> int | None:
    raw = req.query_params.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def respond(data: Any, status: int = 200, extra_headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(content=data, status_code=status, headers=extra_headers)


def respond_err(message: str, status: int = 400) -> JSONResponse:
    return respond({"error": message}, status=status)


def is_valid_identifier(s: str) -> bool:
    return bool(_IDENTIFIER_RE.match(s))
