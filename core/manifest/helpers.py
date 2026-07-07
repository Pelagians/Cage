"""Manifest helper functions."""
from __future__ import annotations

import re
from typing import Any
from dataclasses import dataclass

from .constants import ROOT_FIELDS
from .errors import ManifestError

@dataclass(frozen=True)
class _Token:
    indent: int
    content: str
    line: int


def _load_strict_yaml(text: str) -> Any:
    tokens = _tokenize_yaml(text)
    if not tokens:
        raise ManifestError("YAML document is empty")
    value, index = _parse_yaml_block(tokens, 0, tokens[0].indent)
    if index != len(tokens):
        token = tokens[index]
        raise ManifestError(f"unexpected YAML content at line {token.line}: {token.content}")
    return value


def _tokenize_yaml(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        if "\t" in raw:
            raise ManifestError(f"tabs are not allowed in YAML indentation at line {line_no}")
        stripped_comment = _strip_yaml_comment(raw).rstrip()
        if not stripped_comment.strip():
            continue
        indent = len(stripped_comment) - len(stripped_comment.lstrip(" "))
        if indent % 2 != 0:
            raise ManifestError(f"YAML indentation must use multiples of two spaces at line {line_no}")
        content = stripped_comment.strip()
        if content in {"---", "..."}:
            continue
        _reject_yaml_anchors_aliases_merge(content, line_no)
        tokens.append(_Token(indent, content, line_no))
    return tokens


def _parse_yaml_block(tokens: list[_Token], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(tokens):
        return {}, index
    token = tokens[index]
    if token.indent < indent:
        return {}, index
    if token.indent != indent:
        raise ManifestError(f"unexpected YAML indentation at line {token.line}")
    if token.content.startswith("- ") or token.content == "-":
        return _parse_yaml_list(tokens, index, indent)
    return _parse_yaml_mapping(tokens, index, indent)


def _parse_yaml_mapping(tokens: list[_Token], index: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(tokens):
        token = tokens[index]
        if token.indent < indent:
            break
        if token.indent != indent:
            raise ManifestError(f"unexpected YAML indentation at line {token.line}")
        if token.content.startswith("- ") or token.content == "-":
            break
        key, raw_value = _split_yaml_key_value(token)
        if key in result:
            raise ManifestError(f"duplicate YAML key {key!r} at line {token.line}")
        index += 1
        if raw_value == "":
            if index < len(tokens) and tokens[index].indent > indent:
                value, index = _parse_yaml_block(tokens, index, tokens[index].indent)
            else:
                value = {}
        else:
            value = _parse_yaml_scalar(raw_value, token.line)
        result[key] = value
    return result, index


def _parse_yaml_list(tokens: list[_Token], index: int, indent: int) -> tuple[list[Any], int]:
    result: list[Any] = []
    while index < len(tokens):
        token = tokens[index]
        if token.indent < indent:
            break
        if token.indent != indent:
            raise ManifestError(f"unexpected YAML indentation at line {token.line}")
        if not (token.content.startswith("- ") or token.content == "-"):
            break

        rest = token.content[1:].strip()
        index += 1
        if rest == "":
            if index < len(tokens) and tokens[index].indent > indent:
                value, index = _parse_yaml_block(tokens, index, tokens[index].indent)
            else:
                value = None
            result.append(value)
            continue

        if _looks_like_yaml_key_value(rest):
            key, raw_value = _split_yaml_key_value(_Token(indent + 2, rest, token.line))
            item: dict[str, Any] = {}
            item[key] = _parse_yaml_scalar(raw_value, token.line) if raw_value else {}
            if index < len(tokens) and tokens[index].indent > indent:
                child, index = _parse_yaml_block(tokens, index, tokens[index].indent)
                if not isinstance(child, dict):
                    raise ManifestError(f"YAML list mapping item at line {token.line} must contain mapping children")
                for child_key, child_value in child.items():
                    if child_key in item:
                        raise ManifestError(f"duplicate YAML key {child_key!r} at line {token.line}")
                    item[child_key] = child_value
            result.append(item)
        else:
            result.append(_parse_yaml_scalar(rest, token.line))
            if index < len(tokens) and tokens[index].indent > indent:
                raise ManifestError(f"YAML scalar list item at line {token.line} cannot have nested children")
    return result, index


def _split_yaml_key_value(token: _Token) -> tuple[str, str]:
    if ":" not in token.content:
        raise ManifestError(f"expected YAML key/value pair at line {token.line}")
    key, raw_value = token.content.split(":", 1)
    key = key.strip()
    if not key:
        raise ManifestError(f"empty YAML key at line {token.line}")
    if key == "<<":
        raise ManifestError("YAML anchors, aliases, and merge keys are not supported")
    return key, raw_value.strip()


def _looks_like_yaml_key_value(value: str) -> bool:
    if value.startswith(("'", '"')):
        return False
    if ":" not in value:
        return False
    key, _ = value.split(":", 1)
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key.strip()))


def _parse_yaml_scalar(value: str, line: int) -> Any:
    if value == "":
        return ""
    if value == "[]":
        return []
    if value == "{}":
        return {}
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if value in {"true", "True", "TRUE"}:
        return True
    if value in {"false", "False", "FALSE"}:
        return False
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_yaml_scalar(part.strip(), line) for part in _split_inline_csv(inner)]
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return _parse_quoted_yaml_scalar(value, line)
    if value.startswith(("&", "*")):
        raise ManifestError("YAML anchors, aliases, and merge keys are not supported")
    return value


def _parse_quoted_yaml_scalar(value: str, line: int) -> str:
    quote = value[0]
    body = value[1:-1]
    if quote == "'":
        return body.replace("''", "'")
    try:
        return bytes(body, "utf-8").decode("unicode_escape")
    except UnicodeDecodeError as exc:
        raise ManifestError(f"invalid quoted YAML scalar at line {line}: {exc}") from exc


def _split_inline_csv(value: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escape = False
    for char in value:
        if escape:
            current.append(char)
            escape = False
            continue
        if char == "\\" and quote == '"':
            current.append(char)
            escape = True
            continue
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
            current.append(char)
            continue
        if char == ",":
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    if quote:
        raise ManifestError("unterminated quoted scalar in inline YAML list")
    parts.append("".join(current).strip())
    return parts


def _strip_yaml_comment(raw: str) -> str:
    quote: str | None = None
    escape = False
    result: list[str] = []
    for char in raw:
        if escape:
            result.append(char)
            escape = False
            continue
        if char == "\\" and quote == '"':
            result.append(char)
            escape = True
            continue
        if quote:
            result.append(char)
            if char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
            result.append(char)
            continue
        if char == "#":
            break
        result.append(char)
    return "".join(result)


def _reject_yaml_anchors_aliases_merge(content: str, line: int) -> None:
    if content.startswith("<<:"):
        raise ManifestError("YAML anchors, aliases, and merge keys are not supported")
    # Reject YAML anchors and aliases without treating Windows paths or ordinary
    # words as special. This intentionally supports only a strict recipe subset.
    if re.search(r"(^|[\s:])([&*][A-Za-z0-9_-]+)(\s|$)", content):
        raise ManifestError("YAML anchors, aliases, and merge keys are not supported")


# ---- validation helpers ---------------------------------------------------

def _reject_unknown(data: dict[str, Any], allowed: set[str], location: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        label = "field" if len(unknown) == 1 else "fields"
        raise ManifestError(f"unknown manifest {label} at {location}: " + ", ".join(unknown))


def _required_str(data, key):
    value = data.get(key.split(".")[-1])
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{key} must be a non-empty string")
    return value


def _optional_str(data, key):
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{key} must be a non-empty string when present")
    return value


def _list(value, key):
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
        raise ManifestError(f"{key} must be a list of objects")
    return value


def _string_list(value, key):
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value):
        raise ManifestError(f"{key} must be a list of non-empty strings")
    return value


def _object(value, key):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ManifestError(f"{key} must be an object")
    return value


def _drop_none(data):
    return {k: v for k, v in data.items() if v is not None and v != [] and v != {}}
