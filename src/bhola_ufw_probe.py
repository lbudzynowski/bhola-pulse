#!/usr/bin/python3
"""Privileged, read-only UFW runtime probe with a minimal public result."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any


NFT_PATH = "/usr/sbin/nft"
NFT_COMMAND = (NFT_PATH, "--json", "list", "ruleset")
NFT_TIMEOUT_SECONDS = 3.0
MAX_NFT_OUTPUT_BYTES = 1024 * 1024
STATE_PATH = Path("/run/bhola-pulse/ufw-status.json")
CONFIG_PATH = Path("/etc/ufw/ufw.conf")
MAX_STATE_BYTES = 4096

CONFIG_VALUES = frozenset({"enabled", "disabled", "unknown"})
RUNTIME_VALUES = frozenset({"active", "inactive", "unconfirmed", "error"})
DETAIL_VALUES = frozenset(
    {
        "verified_runtime_active",
        "verified_runtime_inactive",
        "orphan_ufw_runtime",
        "inconsistent_ruleset",
        "command_failed",
        "timeout",
        "invalid_json",
        "empty_output",
        "oversized_output",
        "program_missing",
    }
)
UFW_CHAIN_RE = re.compile(r"^(?:ufw|ufw6)-[A-Za-z0-9_-]+$")

CommandRunner = Callable[..., subprocess.CompletedProcess[bytes]]
ChainKey = tuple[str, str, str]


@dataclass(frozen=True)
class ProbeEvidence:
    runtime: str
    verified: bool
    detail: str


def read_ufw_config(path: Path = CONFIG_PATH) -> str:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return "unknown"
    match = re.search(r"(?im)^\s*ENABLED\s*=\s*(yes|no)\s*$", content)
    if not match:
        return "unknown"
    return "enabled" if match.group(1).lower() == "yes" else "disabled"


def _chain_key(value: Mapping[str, Any]) -> ChainKey | None:
    parts = (value.get("family"), value.get("table"), value.get("name"))
    if not all(isinstance(part, str) and part for part in parts):
        return None
    return parts  # type: ignore[return-value]


def _rule_chain_key(value: Mapping[str, Any]) -> ChainKey | None:
    parts = (value.get("family"), value.get("table"), value.get("chain"))
    if not all(isinstance(part, str) and part for part in parts):
        return None
    return parts  # type: ignore[return-value]


def _jump_targets(expression: Any) -> tuple[set[str], bool]:
    targets: set[str] = set()
    invalid = False
    if isinstance(expression, list):
        for item in expression:
            nested, nested_invalid = _jump_targets(item)
            targets.update(nested)
            invalid = invalid or nested_invalid
    elif isinstance(expression, dict):
        for key, value in expression.items():
            if key in {"jump", "goto"}:
                if not isinstance(value, dict) or not isinstance(value.get("target"), str):
                    invalid = True
                else:
                    targets.add(value["target"])
            else:
                nested, nested_invalid = _jump_targets(value)
                targets.update(nested)
                invalid = invalid or nested_invalid
    return targets, invalid


def classify_ruleset(document: Any) -> ProbeEvidence:
    """Classify structural UFW attachment to a real nftables input hook."""
    if not isinstance(document, dict) or not isinstance(document.get("nftables"), list):
        return ProbeEvidence("unconfirmed", False, "inconsistent_ruleset")

    chains: dict[ChainKey, dict[str, Any]] = {}
    graph: dict[ChainKey, set[ChainKey]] = defaultdict(set)
    rule_counts: dict[ChainKey, int] = defaultdict(int)
    inconsistent = False
    ufw_jump_seen = False

    for entry in document["nftables"]:
        if not isinstance(entry, dict):
            inconsistent = True
            continue
        chain = entry.get("chain")
        if chain is not None:
            if not isinstance(chain, dict):
                inconsistent = True
                continue
            key = _chain_key(chain)
            if key is None or key in chains:
                inconsistent = True
                continue
            hook = chain.get("hook")
            if hook is not None and not isinstance(hook, str):
                inconsistent = True
            chains[key] = chain

    for entry in document["nftables"]:
        if not isinstance(entry, dict) or "rule" not in entry:
            continue
        rule = entry["rule"]
        if not isinstance(rule, dict):
            inconsistent = True
            continue
        source = _rule_chain_key(rule)
        expression = rule.get("expr")
        if source is None or not isinstance(expression, list) or source not in chains:
            inconsistent = True
            continue
        rule_counts[source] += 1
        targets, invalid = _jump_targets(expression)
        inconsistent = inconsistent or invalid
        for target_name in targets:
            target = (source[0], source[1], target_name)
            graph[source].add(target)
            if UFW_CHAIN_RE.fullmatch(target_name):
                ufw_jump_seen = True
            if target not in chains:
                inconsistent = True

    ufw_chains = {key for key in chains if UFW_CHAIN_RE.fullmatch(key[2])}
    input_bases = {
        key
        for key, value in chains.items()
        if value.get("hook") == "input" and isinstance(value.get("type"), str)
    }

    if inconsistent:
        return ProbeEvidence("unconfirmed", False, "inconsistent_ruleset")

    reachable: set[ChainKey] = set()
    queue: deque[ChainKey] = deque(input_bases)
    while queue:
        current = queue.popleft()
        if current in reachable:
            continue
        reachable.add(current)
        queue.extend(graph.get(current, ()))

    reachable_ufw = reachable & ufw_chains
    if reachable_ufw:
        if any(rule_counts[key] > 0 for key in reachable_ufw):
            return ProbeEvidence("active", True, "verified_runtime_active")
        return ProbeEvidence("inactive", True, "verified_runtime_inactive")
    if ufw_chains or ufw_jump_seen:
        return ProbeEvidence("unconfirmed", False, "orphan_ufw_runtime")
    return ProbeEvidence("inactive", True, "verified_runtime_inactive")


def run_probe(
    runner: CommandRunner = subprocess.run,
    *,
    timeout: float = NFT_TIMEOUT_SECONDS,
) -> ProbeEvidence:
    try:
        completed = runner(
            list(NFT_COMMAND),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except FileNotFoundError:
        return ProbeEvidence("error", False, "program_missing")
    except subprocess.TimeoutExpired:
        return ProbeEvidence("error", False, "timeout")
    except OSError:
        return ProbeEvidence("error", False, "command_failed")

    if completed.returncode != 0:
        return ProbeEvidence("error", False, "command_failed")
    output = completed.stdout or b""
    if isinstance(output, str):
        output = output.encode("utf-8", "strict")
    if not output:
        return ProbeEvidence("error", False, "empty_output")
    if len(output) > MAX_NFT_OUTPUT_BYTES:
        return ProbeEvidence("error", False, "oversized_output")
    try:
        document = json.loads(output.decode("utf-8", "strict"))
    except (UnicodeError, json.JSONDecodeError):
        return ProbeEvidence("error", False, "invalid_json")
    return classify_ruleset(document)


def build_state(
    evidence: ProbeEvidence,
    config: str,
    observed_at_epoch: int,
) -> dict[str, object]:
    if config not in CONFIG_VALUES:
        raise ValueError("invalid config state")
    if evidence.runtime not in RUNTIME_VALUES or evidence.detail not in DETAIL_VALUES:
        raise ValueError("invalid probe evidence")
    if evidence.verified != (evidence.runtime in {"active", "inactive"}):
        raise ValueError("runtime verification invariant violated")
    if type(observed_at_epoch) is not int or observed_at_epoch <= 0:
        raise ValueError("invalid observation time")
    return {
        "schema_version": 1,
        "observed_at_epoch": observed_at_epoch,
        "config": config,
        "runtime": evidence.runtime,
        "verified": evidence.verified,
        "source": "nftables",
        "detail": evidence.detail,
    }


def atomic_write_state(
    state: Mapping[str, object],
    path: Path = STATE_PATH,
    *,
    trusted_uid: int = 0,
) -> None:
    parent_info = path.parent.lstat()
    if not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != trusted_uid:
        raise OSError("unsafe runtime directory")
    if parent_info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise OSError("writable runtime directory")

    payload = json.dumps(
        dict(state), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii") + b"\n"
    if len(payload) > MAX_STATE_BYTES:
        raise ValueError("state exceeds size limit")

    descriptor = -1
    temporary_name = ""
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".ufw-status.", dir=path.parent
        )
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
        temporary_name = ""
        directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv if argv is None else argv
    if len(arguments) != 1:
        return 2
    evidence = run_probe()
    try:
        state = build_state(evidence, read_ufw_config(), int(time.time()))
        atomic_write_state(state)
    except (OSError, ValueError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
