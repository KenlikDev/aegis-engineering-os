#!/usr/bin/env python3
"""Define and validate the canonical Aegis evidence provenance envelope."""

from __future__ import annotations

import json
import math
import os
import re
import stat
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
MAX_JSON_BYTES = 65536
MAX_STRING_LENGTH = 4096
MAX_UNCERTAINTIES = 32
MAX_REFERENCES = 32
ALLOWED_STATUSES = frozenset({"verified", "failed", "pending", "unknown"})
KIND_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
HTTPS_REFERENCE_RE = re.compile(r"^https://[^\s]+$")
SECRET_KEY_RE = re.compile(
    r"(token|secret|password|passwd|api[_-]?key|authorization|credential|private[_-]?key)",
    re.IGNORECASE,
)
SECRET_VALUE_PATTERNS = (
    re.compile(r"ghp_[A-Za-z0-9_]+"),
    re.compile(r"github_pat_[A-Za-z0-9_]+"),
    re.compile(r"gho_[A-Za-z0-9_]+"),
    re.compile(r"ghu_[A-Za-z0-9_]+"),
    re.compile(r"ghs_[A-Za-z0-9_]+"),
    re.compile(r"ghr_[A-Za-z0-9_]+"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ASIA[0-9A-Z]{16}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
)
IDENTITY_KEYS = frozenset({"evidence_id", "evidence_sha256"})
COMMON_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "source",
        "subject",
        "revision",
        "observed_at",
        "status",
        "result",
        "uncertainty",
        "references",
        "artifact_sha256",
    }
)
REQUIRED_KEYS = COMMON_KEYS | IDENTITY_KEYS
INPUT_KEYS = COMMON_KEYS


class EvidenceContractError(RuntimeError):
    """Raised when an evidence record violates the canonical contract."""


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """Canonical provider-neutral evidence record."""

    schema_version: int
    evidence_id: str
    kind: str
    source: str
    subject: str
    revision: str | None
    observed_at: str
    status: str
    result: Mapping[str, Any]
    uncertainty: tuple[str, ...]
    references: tuple[str, ...]
    artifact_sha256: str | None
    evidence_sha256: str


def _reject_constants(value: str) -> None:
    raise EvidenceContractError(f"JSON constant {value!r} is not allowed.")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceContractError(f"Duplicate JSON key: {key!r}.")
        result[key] = value
    return result


def parse_json_object(
    raw: bytes | str,
    *,
    label: str = "JSON input",
) -> dict[str, Any]:
    """Parse a bounded JSON object while rejecting ambiguous JSON syntax."""
    if isinstance(raw, str):
        encoded = raw.encode("utf-8")
    elif isinstance(raw, bytes):
        encoded = raw
    else:
        raise EvidenceContractError(f"{label} must be text or bytes.")
    if len(encoded) > MAX_JSON_BYTES:
        raise EvidenceContractError(
            f"{label} exceeds the {MAX_JSON_BYTES}-byte limit."
        )
    try:
        value = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constants,
        )
    except EvidenceContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceContractError(f"{label} is invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceContractError(f"{label} must contain an object.")
    return value


def load_json_object(path: str | Path) -> dict[str, Any]:
    """Read a bounded JSON object and reject ambiguous JSON syntax."""
    file_path = Path(path).expanduser().resolve()
    try:
        raw = file_path.read_bytes()
    except OSError as exc:
        raise EvidenceContractError(
            f"Unable to read evidence input {file_path}: {exc}"
        ) from exc
    if len(raw) > MAX_JSON_BYTES:
        raise EvidenceContractError(
            f"Evidence JSON exceeds the {MAX_JSON_BYTES}-byte limit."
        )
    return parse_json_object(raw, label="Evidence JSON")


def _validate_string(
    value: object,
    field: str,
    *,
    max_length: int = MAX_STRING_LENGTH,
) -> str:
    if not isinstance(value, str):
        raise EvidenceContractError(f"{field} must be a string.")
    if not value or value != value.strip():
        raise EvidenceContractError(f"{field} must be a non-empty trimmed string.")
    if len(value) > max_length or any(char in value for char in "\x00\r\n"):
        raise EvidenceContractError(f"{field} contains invalid or oversized text.")
    return value


def _validate_optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _validate_string(value, field)


def _scan_sensitive(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise EvidenceContractError(f"{path} contains a non-string object key.")
            if SECRET_KEY_RE.search(key):
                raise EvidenceContractError(
                    f"{path}.{key} uses a secret-like field name and cannot be recorded."
                )
            _scan_sensitive(child, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _scan_sensitive(child, f"{path}[{index}]")
        return
    if isinstance(value, str):
        for pattern in SECRET_VALUE_PATTERNS:
            if pattern.search(value):
                raise EvidenceContractError(
                    f"{path} contains credential-like material and cannot be recorded."
                )


def _validate_json_value(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str) and len(value) > MAX_STRING_LENGTH:
            raise EvidenceContractError(f"{path} contains an oversized string.")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EvidenceContractError(f"{path} contains a non-finite number.")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise EvidenceContractError(f"{path} contains a non-string object key.")
            _validate_json_value(child, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_json_value(child, f"{path}[{index}]")
        return
    raise EvidenceContractError(f"{path} contains an unsupported JSON value.")


def _normalize_observed_at(value: object) -> str:
    text = _validate_string(value, "observed_at", max_length=64)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise EvidenceContractError(
            "observed_at must be an ISO-8601 timestamp."
        ) from exc
    if parsed.tzinfo is None:
        raise EvidenceContractError("observed_at must include an explicit timezone.")
    return (
        parsed.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _canonical_payload(payload: Mapping[str, Any]) -> bytes:
    unsigned = {
        key: value
        for key, value in payload.items()
        if key not in IDENTITY_KEYS
    }
    return json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _calculate_evidence_sha256(payload: Mapping[str, Any]) -> str:
    return sha256(_canonical_payload(payload)).hexdigest()


def _validate_semantics(payload: Mapping[str, Any]) -> tuple[str, str, str, str | None, str, Mapping[str, Any], tuple[str, ...], tuple[str, ...], str | None]:
    if set(payload) != INPUT_KEYS:
        missing = sorted(INPUT_KEYS - set(payload))
        extra = sorted(set(payload) - INPUT_KEYS)
        details = []
        if missing:
            details.append(f"missing keys: {', '.join(missing)}")
        if extra:
            details.append(f"unknown keys: {', '.join(extra)}")
        raise EvidenceContractError(
            "Evidence payload schema is malformed (" + "; ".join(details) + ")."
        )

    if payload["schema_version"] != SCHEMA_VERSION:
        raise EvidenceContractError(
            f"Unsupported evidence schema version: {payload['schema_version']!r}."
        )

    kind = _validate_string(payload["kind"], "kind", max_length=64)
    if not KIND_RE.fullmatch(kind):
        raise EvidenceContractError("kind must use lowercase kebab-case.")
    source = _validate_string(payload["source"], "source")
    subject = _validate_string(payload["subject"], "subject")
    revision = _validate_optional_string(payload["revision"], "revision")
    observed_at = _normalize_observed_at(payload["observed_at"])

    status = _validate_string(payload["status"], "status", max_length=32)
    if status not in ALLOWED_STATUSES:
        raise EvidenceContractError(
            f"Unsupported evidence status {status!r}; expected one of {sorted(ALLOWED_STATUSES)}."
        )

    result = payload["result"]
    if not isinstance(result, Mapping):
        raise EvidenceContractError("result must be a JSON object.")
    _validate_json_value(result, "$.result")
    _scan_sensitive(result)

    raw_uncertainty = payload["uncertainty"]
    if not isinstance(raw_uncertainty, list):
        raise EvidenceContractError("uncertainty must be a JSON array.")
    if len(raw_uncertainty) > MAX_UNCERTAINTIES:
        raise EvidenceContractError("uncertainty contains too many entries.")
    uncertainty = tuple(
        _validate_string(item, f"uncertainty[{index}]", max_length=1024)
        for index, item in enumerate(raw_uncertainty)
    )

    raw_references = payload["references"]
    if not isinstance(raw_references, list):
        raise EvidenceContractError("references must be a JSON array.")
    if len(raw_references) > MAX_REFERENCES:
        raise EvidenceContractError("references contains too many entries.")
    references = tuple(
        _validate_string(item, f"references[{index}]", max_length=2048)
        for index, item in enumerate(raw_references)
    )
    for reference in references:
        if not HTTPS_REFERENCE_RE.fullmatch(reference):
            raise EvidenceContractError(
                "Evidence references must use HTTPS and contain no whitespace."
            )

    artifact_sha256 = payload["artifact_sha256"]
    if artifact_sha256 is not None:
        artifact_sha256 = _validate_string(
            artifact_sha256,
            "artifact_sha256",
            max_length=64,
        )
        if not SHA256_RE.fullmatch(artifact_sha256):
            raise EvidenceContractError("artifact_sha256 must be a lowercase SHA-256 value.")

    _scan_sensitive(source, "$.source")
    _scan_sensitive(subject, "$.subject")
    _scan_sensitive(revision, "$.revision")
    _scan_sensitive(uncertainty, "$.uncertainty")
    _scan_sensitive(references, "$.references")
    return (
        kind,
        source,
        subject,
        revision,
        observed_at,
        dict(result),
        uncertainty,
        references,
        artifact_sha256,
    )


def build_evidence(payload: Mapping[str, Any]) -> EvidenceRecord:
    """Normalize explicit evidence input, calculate its canonical self-hash, and return it."""
    if set(payload) != INPUT_KEYS:
        missing = sorted(INPUT_KEYS - set(payload))
        extra = sorted(set(payload) - INPUT_KEYS)
        details = []
        if missing:
            details.append(f"missing keys: {', '.join(missing)}")
        if extra:
            details.append(f"unknown keys: {', '.join(extra)}")
        raise EvidenceContractError(
            "Evidence input schema is malformed (" + "; ".join(details) + ")."
        )

    normalized = dict(payload)
    normalized["observed_at"] = _normalize_observed_at(normalized["observed_at"])
    (
        kind,
        source,
        subject,
        revision,
        observed_at,
        result,
        uncertainty,
        references,
        artifact_sha256,
    ) = _validate_semantics(normalized)

    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "source": source,
        "subject": subject,
        "revision": revision,
        "observed_at": observed_at,
        "status": normalized["status"],
        "result": result,
        "uncertainty": list(uncertainty),
        "references": list(references),
        "artifact_sha256": artifact_sha256,
    }
    digest = _calculate_evidence_sha256(unsigned)
    return EvidenceRecord(
        schema_version=SCHEMA_VERSION,
        evidence_id=digest,
        kind=kind,
        source=source,
        subject=subject,
        revision=revision,
        observed_at=observed_at,
        status=normalized["status"],
        result=result,
        uncertainty=uncertainty,
        references=references,
        artifact_sha256=artifact_sha256,
        evidence_sha256=digest,
    )


def _payload_from_record(record: EvidenceRecord) -> dict[str, Any]:
    return {
        "schema_version": record.schema_version,
        "evidence_id": record.evidence_id,
        "kind": record.kind,
        "source": record.source,
        "subject": record.subject,
        "revision": record.revision,
        "observed_at": record.observed_at,
        "status": record.status,
        "result": record.result,
        "uncertainty": list(record.uncertainty),
        "references": list(record.references),
        "artifact_sha256": record.artifact_sha256,
        "evidence_sha256": record.evidence_sha256,
    }


def _validate_record(payload: Mapping[str, Any]) -> EvidenceRecord:
    if set(payload) != REQUIRED_KEYS:
        missing = sorted(REQUIRED_KEYS - set(payload))
        extra = sorted(set(payload) - REQUIRED_KEYS)
        details = []
        if missing:
            details.append(f"missing keys: {', '.join(missing)}")
        if extra:
            details.append(f"unknown keys: {', '.join(extra)}")
        raise EvidenceContractError(
            "Malformed evidence schema (" + "; ".join(details) + ")."
        )

    evidence_id = _validate_string(payload["evidence_id"], "evidence_id", max_length=64)
    evidence_sha256 = _validate_string(
        payload["evidence_sha256"],
        "evidence_sha256",
        max_length=64,
    )
    if not SHA256_RE.fullmatch(evidence_id) or not SHA256_RE.fullmatch(evidence_sha256):
        raise EvidenceContractError("Evidence identity fields must be lowercase SHA-256 values.")

    unsigned = {key: value for key, value in payload.items() if key not in IDENTITY_KEYS}
    (
        _kind,
        _source,
        _subject,
        _revision,
        _observed_at,
        _result,
        _uncertainty,
        _references,
        _artifact_sha256,
    ) = _validate_semantics(unsigned)
    calculated = _calculate_evidence_sha256(unsigned)
    if evidence_id != evidence_sha256 or evidence_id != calculated:
        raise EvidenceContractError(
            "Evidence identity hash is inconsistent with the canonical payload."
        )

    record = dict(payload)
    return EvidenceRecord(
        schema_version=SCHEMA_VERSION,
        evidence_id=evidence_id,
        kind=record["kind"],
        source=record["source"],
        subject=record["subject"],
        revision=record["revision"],
        observed_at=_normalize_observed_at(record["observed_at"]),
        status=record["status"],
        result=dict(record["result"]),
        uncertainty=tuple(record["uncertainty"]),
        references=tuple(record["references"]),
        artifact_sha256=record["artifact_sha256"],
        evidence_sha256=evidence_sha256,
    )


def _open_secure_destination_directory(
    path: Path,
    *,
    error_type: type[Exception],
) -> tuple[int, str]:
    """Open the destination directory without following symlinked path components."""
    if (
        os.name != "posix"
        or not hasattr(os, "O_DIRECTORY")
        or not hasattr(os, "O_NOFOLLOW")
    ):
        raise error_type(
            "Atomic JSON output requires POSIX directory-FD and no-follow support."
        )

    absolute = Path(os.path.abspath(path))
    if absolute == Path(absolute.anchor):
        raise error_type("JSON output must identify a file path.")

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        directory_fd = os.open(absolute.anchor, flags)
    except OSError as exc:
        raise error_type(
            f"Unable to securely open the JSON output filesystem root: {absolute.anchor}"
        ) from exc

    try:
        for component in absolute.parent.parts:
            if component == absolute.anchor:
                continue
            try:
                next_fd = os.open(component, flags, dir_fd=directory_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(component, 0o700, dir_fd=directory_fd)
                except FileExistsError:
                    pass
                next_fd = os.open(component, flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
    except Exception as exc:
        os.close(directory_fd)
        if isinstance(exc, error_type):
            raise
        raise error_type(
            f"Unable to securely open JSON output directory: {absolute.parent}"
        ) from exc

    return directory_fd, absolute.name



def write_bytes_atomically(
    payload: bytes,
    output_path: str | Path,
    *,
    error_type: type[Exception] = EvidenceContractError,
    file_mode: int = 0o600,
) -> None:
    """Write raw bytes through an anchored directory FD and atomic replacement."""
    if not isinstance(payload, bytes):
        raise error_type("Atomic byte output payload must be bytes.")
    if not isinstance(file_mode, int) or file_mode < 0 or file_mode > 0o777:
        raise error_type("Atomic byte output file mode must be a valid POSIX mode.")

    path = Path(output_path).expanduser()
    directory_fd, filename = _open_secure_destination_directory(
        path,
        error_type=error_type,
    )
    temporary_name: str | None = None
    file_descriptor: int | None = None

    try:
        try:
            destination_stat = os.stat(
                filename,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            destination_stat = None
        if destination_stat is not None and stat.S_ISLNK(destination_stat.st_mode):
            raise error_type("Atomic byte output must not be a symbolic link.")

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        for _ in range(32):
            candidate = f".{filename}.{uuid.uuid4().hex}.tmp"
            try:
                file_descriptor = os.open(
                    candidate,
                    flags,
                    file_mode,
                    dir_fd=directory_fd,
                )
            except FileExistsError:
                continue
            temporary_name = candidate
            break
        else:
            raise error_type("Unable to allocate a unique temporary byte output path.")

        with os.fdopen(file_descriptor, "wb") as handle:
            file_descriptor = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(
            temporary_name,
            filename,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary_name = None
        os.fsync(directory_fd)
    except Exception:
        if file_descriptor is not None:
            os.close(file_descriptor)
            file_descriptor = None
        raise
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)


def copy_file_atomically(
    source_path: str | Path,
    output_path: str | Path,
    *,
    error_type: type[Exception] = EvidenceContractError,
) -> None:
    """Copy one regular source file into a destination through the atomic byte writer."""
    source = Path(source_path).expanduser()
    if source.is_symlink() or not source.is_file():
        raise error_type(f"Atomic copy source must be a regular non-symlink file: {source}")
    try:
        payload = source.read_bytes()
        mode = stat.S_IMODE(source.stat().st_mode)
    except (OSError, UnicodeError) as exc:
        raise error_type(f"Unable to read atomic copy source: {source}") from exc

    write_bytes_atomically(
        payload,
        output_path,
        error_type=error_type,
        file_mode=mode,
    )

def write_json_atomically(
    payload: Mapping[str, Any],
    output_path: str | Path,
    *,
    error_type: type[Exception] = EvidenceContractError,
) -> None:
    """Write JSON through an anchored directory FD and atomic replacement."""
    if not isinstance(payload, Mapping):
        raise error_type("JSON output payload must be an object.")

    path = Path(output_path).expanduser()
    directory_fd, filename = _open_secure_destination_directory(
        path,
        error_type=error_type,
    )
    temporary_name: str | None = None
    file_descriptor: int | None = None

    try:
        try:
            destination_stat = os.stat(
                filename,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            destination_stat = None
        if destination_stat is not None and stat.S_ISLNK(destination_stat.st_mode):
            raise error_type("JSON output must not be a symbolic link.")

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        for _ in range(32):
            candidate = f".{filename}.{uuid.uuid4().hex}.tmp"
            try:
                file_descriptor = os.open(
                    candidate,
                    flags,
                    0o600,
                    dir_fd=directory_fd,
                )
            except FileExistsError:
                continue
            temporary_name = candidate
            break
        else:
            raise error_type("Unable to allocate a unique temporary JSON output path.")

        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            file_descriptor = None
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(
            temporary_name,
            filename,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary_name = None
        os.fsync(directory_fd)
    except Exception:
        if file_descriptor is not None:
            os.close(file_descriptor)
            file_descriptor = None
        raise
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)


def write_evidence(record: EvidenceRecord, output_path: str | Path) -> None:
    """Write a validated evidence record as canonical JSON."""
    write_json_atomically(
        _payload_from_record(record),
        output_path,
        error_type=EvidenceContractError,
    )


def read_and_validate_evidence(path: str | Path) -> EvidenceRecord:
    """Read an existing evidence artifact and verify its provenance hash."""
    return _validate_record(load_json_object(path))
