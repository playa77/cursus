"""Strict, stateless M0 contracts (D2 §5.1).

Values are detached JSON-compatible Python values. Validation raises a safe
Problem; ingress layers introduced later map that Problem to their transport.
This module performs no I/O and grants no repository or workflow authority.
"""

from datetime import datetime
import hashlib
import json
import math
import re
from typing import Any
from uuid import UUID

MAX_SEQUENCE = (1 << 63) - 1
MAX_REQUEST_BYTES = 1024 * 1024
MAX_SPEC_BYTES = 256 * 1024


class Problem(ValueError):
    """Stable public error without reflecting untrusted payloads or secrets."""

    def __init__(self, code: str, message: str, entity_id: str | None = None):
        self.code = code
        self.message = message
        self.entity_id = entity_id
        super().__init__(message)

    def as_dict(self) -> dict[str, str]:
        result = {"code": self.code, "message": self.message}
        if self.entity_id is not None:
            result["entity_id"] = self.entity_id
        return result


def _fail(code: str = "invalid_contract", message: str = "Invalid contract value.") -> Any:
    raise Problem(code, message)


def _text(value: Any, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        _fail()
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        _fail("invalid_unicode", "Text must be valid UTF-8.")
    return value


def _object(value: Any, required: set[str], optional: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict) or not required <= value.keys():
        _fail("invalid_fields", "Required object fields are missing.")
    if value.keys() - required - optional:
        _fail("invalid_fields", "Object contains unsupported fields.")
    return value


def _integer(value: Any, minimum: int = 1) -> int:
    # bool is an int subclass, but never a protocol ordinal/count.
    if type(value) is not int or not minimum <= value <= MAX_SEQUENCE:
        _fail("invalid_scalar", "Integer is outside its permitted range.")
    return value


def _enum(value: Any, choices: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in choices:
        _fail("invalid_variant", "Unknown or missing discriminator.")
    return value


def _hex(value: Any, length: int) -> str:
    if not isinstance(value, str) or re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is None:
        _fail("invalid_scalar", "Expected a full lowercase hexadecimal hash.")
    return value


def _id(value: Any) -> str:
    try:
        parsed = UUID(_text(value))
    except (ValueError, AttributeError):
        _fail("invalid_scalar", "Expected a UUID.")
    if str(parsed) != value:
        _fail("invalid_scalar", "Expected a canonical UUID.")
    return value


def _time(value: Any) -> str:
    value = _text(value)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)", value) is None:
        _fail("invalid_scalar", "Expected a UTC RFC3339 timestamp.")
    try:
        datetime.fromisoformat(value)
    except ValueError:
        _fail("invalid_scalar", "Invalid UTC date or time.")
    return value


def _ref(value: Any) -> str:
    """Branch subset of git-check-ref-format; regression-tested against Git.

    Keep Git subprocesses on VPS-A; the control plane also consumes this type.
    Enrollment/ownership checks are separate from lexical ref validation.
    """
    value = _text(value)
    parts = value.split("/")
    if (
        not value.startswith("refs/heads/") or len(parts) < 3
        or value.endswith(".") or ".." in value or "@{" in value
        or any(ord(c) < 33 or ord(c) == 127 or c in "~^:?*[\\" for c in value)
        or any(not p or p.startswith(".") or p.endswith(".lock") for p in parts)
    ):
        _fail("invalid_ref", "Expected a fully qualified legal Git branch ref.")
    return value


def _path(value: Any) -> str:
    value = _text(value)
    if (value.startswith("/") or "\\" in value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or any(p in ("", ".", "..") for p in value.split("/"))):
        _fail("invalid_path", "Expected a safe repository-relative POSIX path.")
    return value


def _repo(value: Any) -> dict:
    obj = _object(value, {"owner", "name", "target_ref"})
    for key in ("owner", "name"):
        token = _text(obj[key])
        if re.fullmatch(r"[A-Za-z0-9_.-]+", token) is None or token in (".", ".."):
            _fail("invalid_scalar", "Invalid repository identifier.")
    _ref(obj["target_ref"])
    return dict(obj)


def _file(value: Any) -> dict:
    obj = _object(value, {"id", "digest", "length", "name", "media_type"})
    _id(obj["id"])
    _hex(obj["digest"], 64)
    _integer(obj["length"], 0)
    name = _text(obj["name"])
    if (name in (".", "..") or any(c in name for c in "/\\")
            or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        _fail("invalid_path", "Invalid display filename.")
    # Names here are already decoded. HTTP upload owns percent decoding once.
    media = _text(obj["media_type"])
    if re.fullmatch(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+", media) is None:
        _fail("invalid_scalar", "Expected a media type without parameters.")
    return dict(obj)


def _source(value: Any, sha_length: int) -> dict:
    if not isinstance(value, dict):
        _fail()
    kind = _enum(value.get("kind"), ("inline", "repo", "interview"))
    if kind == "inline":
        obj = _object(value, {"kind", "text"})
        if len(_text(obj["text"]).encode("utf-8")) > MAX_SPEC_BYTES:
            _fail("payload_too_large", "Specification exceeds its byte limit.")
    elif kind == "repo":
        obj = _object(value, {"kind", "owner", "name", "commit", "path"})
        _repo({"owner": obj["owner"], "name": obj["name"], "target_ref": "refs/heads/main"})
        _hex(obj["commit"], sha_length)
        _path(obj["path"])
    else:
        obj = _object(value, {"kind"})
    return dict(obj)


def _input(value: Any, sha_length: int) -> dict:
    obj = _object(value, {"workflow", "source", "plan_debate", "spec_debate"}, {"form", "repo"})
    workflow = _enum(obj["workflow"], ("code", "debug", "marketing", "grant", "business"))
    result = dict(obj)
    for key in ("plan_debate", "spec_debate"):
        if type(obj[key]) is not bool:
            _fail("invalid_scalar", "Debate flags must be booleans.")
    result["source"] = _source(obj["source"], sha_length)
    if workflow in ("code", "debug"):
        if "repo" not in obj:
            _fail("invalid_fields", "Code and debug require a repository.")
        result["repo"] = _repo(obj["repo"])
    elif "repo" in obj:
        _fail("invalid_variant", "Repository is inapplicable to this workflow.")
    if workflow == "code":
        result["form"] = _enum(obj.get("form", "phase"), ("one-shot", "ticket", "phase"))
    elif "form" in obj:
        _fail("invalid_variant", "Form applies only to code.")
    return result


def _action(value: Any, sha_length: int) -> dict:
    if not isinstance(value, dict):
        _fail()
    kind = _enum(value.get("kind"), (
        "submit", "answer", "steer", "cancel", "declare_unrecoverable", "abandon",
    ))
    if kind == "submit":
        obj = _object(value, {"kind", "input"})
        return {"kind": kind, "input": _input(obj["input"], sha_length)}
    fields = {
        "answer": {"phase_id", "question_id", "text"},
        "steer": {"attempt_id", "text"},
        "cancel": {"phase_id"},
        "declare_unrecoverable": {"attempt_id", "reason"},
        "abandon": {"attempt_id", "reason"},
    }[kind]
    obj = _object(value, {"kind"} | fields)
    for field in fields:
        if field.endswith("_id"):
            _id(obj[field])
        else:
            _text(obj[field])
    return dict(obj)


def _candidate(value: Any, sha_length: int) -> dict:
    if not isinstance(value, dict):
        _fail()
    kind = _enum(value.get("kind"), ("code", "files"))
    if kind == "code":
        obj = _object(value, {"kind", "repo", "base_sha", "attempt_ref", "head_sha"})
        return dict(obj, repo=_repo(obj["repo"]), base_sha=_hex(obj["base_sha"], sha_length),
                    attempt_ref=_ref(obj["attempt_ref"]), head_sha=_hex(obj["head_sha"], sha_length))
    obj = _object(value, {"kind", "files"})
    if not isinstance(obj["files"], list) or not obj["files"]:
        _fail("invalid_variant", "A files candidate requires nonempty ordered files.")
    files = [_file(item) for item in obj["files"]]
    if len({item["id"] for item in files}) != len(files):
        _fail("invalid_contract", "Duplicate file identity.")
    return {"kind": kind, "files": files}


def _json_value(value: Any) -> None:
    if value is None or type(value) in (bool, int):
        return
    if isinstance(value, str):
        _text(value, nonempty=False)
    elif type(value) is float and math.isfinite(value):
        return
    elif isinstance(value, list):
        for item in value:
            _json_value(item)
    elif isinstance(value, dict) and all(isinstance(k, str) for k in value):
        for key, item in value.items():
            _text(key, nonempty=False)
            _json_value(item)
    else:
        _fail("invalid_json", "Expected finite JSON values and string object keys.")


def canonical_json(value: Any) -> bytes:
    """D2 canonical bytes; callers must validate their declared type first."""
    try:
        _json_value(value)
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (RecursionError, ValueError, UnicodeError) as exc:
        if isinstance(exc, Problem):
            raise
        _fail("invalid_json", "Value cannot be serialized as JSON.")


def decode_json(raw: str | bytes) -> Any:
    """Decode bounded strict UTF-8; reject duplicates at every nesting level."""
    def pairs(items: list[tuple[str, Any]]) -> dict:
        result = {}
        for key, value in items:
            if key in result:
                _fail("duplicate_key", "JSON contains duplicate object keys.")
            result[key] = value
        return result

    if not isinstance(raw, (str, bytes)):
        _fail("invalid_json", "Expected JSON text or UTF-8 bytes.")
    try:
        encoded = raw.encode("utf-8") if isinstance(raw, str) else raw
        if len(encoded) > MAX_REQUEST_BYTES:
            _fail("payload_too_large", "JSON exceeds its byte limit.")
        value = json.loads(encoded.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=lambda _: _fail("invalid_json", "Non-finite JSON number."))
        _json_value(value)  # Also rejects overflowed floats and escaped lone surrogates.
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, Problem):
            raise
        _fail("invalid_json", "Malformed JSON or UTF-8.")


def validate(contract: str, value: Any, *, object_format: str = "sha1") -> Any:
    """Validate an introduced contract; never accept an unknown future type.

    SHA format comes from repository enrollment (sha1 by default, sha256 when
    explicit). Authorization and cross-entity/state checks belong to later WPs.
    """
    if object_format not in ("sha1", "sha256"):
        _fail("invalid_scalar", "Unsupported Git object format.")
    length = 40 if object_format == "sha1" else 64
    validators = {
        "Id": _id, "Time": _time, "Seq": _integer,
        "Digest": lambda v: _hex(v, 64), "Sha": lambda v: _hex(v, length),
        "Ref": _ref, "Repo": _repo, "FileRef": _file,
        "Candidate": lambda v: _candidate(v, length),
        "Input": lambda v: _input(v, length), "Action": lambda v: _action(v, length),
    }
    from cursus.runtime_contracts import VALIDATORS
    validators.update(VALIDATORS)
    if contract not in validators:
        _fail("unsupported_contract", "Contract is not available in this milestone.")
    # Detach the result and prohibit Python-only values even on in-process calls.
    detached = decode_json(canonical_json(value))
    return validators[contract](detached)


def digest(contract: str, value: Any, *, object_format: str = "sha1") -> str:
    """Hash canonical *validated* data, including specified defaults."""
    validated = validate(contract, value, object_format=object_format)
    return hashlib.sha256(canonical_json(validated)).hexdigest()
