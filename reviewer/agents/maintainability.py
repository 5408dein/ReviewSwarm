"""Maintainability agent: AST code-smell metrics + LLM analysis.

Workflow:
    1. Scan changed Python files with AST for code smells that hurt long-term
       maintainability: over-long functions, too-many-parameters, and god
       classes (too many methods).
    2. Pass the metrics table + PR diff to the LLM for interpretation and
       concrete refactoring suggestions.

Same reliability shape as the other agents: catches everything, returns an
``agents_failed`` patch on failure rather than raising.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from reviewer import config
from reviewer.agents.base import FindingList, analyze_with_schema
from reviewer.graph.state import AGENT_NODE_TO_LABEL, ReviewState
from reviewer.tools.ast_inspector import find_classes, find_functions

log = logging.getLogger(__name__)

MAINTAINABILITY_LABEL = AGENT_NODE_TO_LABEL["maintainability_agent"]
MAINTAINABILITY_TIMEOUT_S = 60.0  # default; override via REVIEWER_MAINTAINABILITY_TIMEOUT_S

# Code-smell thresholds.
LONG_FUNCTION_LINES = 40   # functions >= this many lines are flagged
MANY_PARAMS = 5            # functions with > this many params are flagged
GOD_CLASS_METHODS = 10     # classes with >= this many methods are god-class suspects

MAINTAINABILITY_SYSTEM_PROMPT = (
    "You are a senior software engineer reviewing Python for long-term "
    "maintainability. You receive an AST-derived code-smell table (long "
    "functions, many parameters, god classes) and a unified PR diff. "
    "Identify concrete refactorings that reduce future maintenance cost. "
    'Use the FindingList schema. Set ``category`` to "maintainability". Use '
    '``agent`` "maintainability". Severity guidance: large monolithic code is '
    "medium; minor readability nits are low; reserve high for smells likely to "
    "cause real defects over time."
)


def _python_targets(state: ReviewState) -> list[str]:
    return [
        f["path"]
        for f in state.get("changed_files", [])
        if f.get("path", "").endswith(".py") and f.get("change_type") != "removed"
    ]


def _metrics_table(state: ReviewState) -> str:
    """Build a code-smell table from changed Python sources via AST."""
    rows: list[str] = []
    for f in state.get("changed_files", []):
        path = f.get("path", "")
        if not path.endswith(".py") or f.get("change_type") == "removed":
            continue
        content = f.get("content", "")
        try:
            for fn in find_functions(content):
                length = fn.line_end - fn.line_start + 1
                flags: list[str] = []
                if length >= LONG_FUNCTION_LINES:
                    flags.append(f"{length} lines")
                if len(fn.args) > MANY_PARAMS:
                    flags.append(f"{len(fn.args)} params")
                if flags:
                    rows.append(
                        f"- {path}:{fn.line_start} {fn.qualname} ({', '.join(flags)})"
                    )
            for cls in find_classes(content):
                if len(cls.methods) >= GOD_CLASS_METHODS:
                    rows.append(
                        f"- {path}:{cls.line_start} class {cls.name} "
                        f"({len(cls.methods)} methods, god-class suspect)"
                    )
        except SyntaxError as e:
            rows.append(f"- {path}: <syntax error: {e}>")
    return "\n".join(rows) if rows else "(no maintainability smells)"


def _build_maintainability_prompt(diff: str, metrics_table: str) -> str:
    return (
        "## Code-smell metrics (changed files)\n"
        f"{metrics_table}\n\n"
        "## PR unified diff\n"
        f"{diff}\n\n"
        "Return findings in the FindingList schema. Empty list if nothing to flag."
    )


async def maintainability_agent_node(state: ReviewState) -> dict[str, Any]:
    """LangGraph node entrypoint. Always returns a state patch — never raises."""
    timeout_s = config.agent_timeout("maintainability", MAINTAINABILITY_TIMEOUT_S)
    try:
        async with asyncio.timeout(timeout_s):
            return await _run(state)
    except TimeoutError:
        log.warning("maintainability agent timed out after %.0fs", timeout_s)
        return {
            "agents_failed": [
                {"agent": MAINTAINABILITY_LABEL, "error": f"timeout after {timeout_s:.0f}s"}
            ]
        }
    except Exception as e:  # noqa: BLE001
        log.exception("maintainability agent crashed: %s", e)
        return {"agents_failed": [{"agent": MAINTAINABILITY_LABEL, "error": str(e)}]}


async def _run(state: ReviewState) -> dict[str, Any]:
    targets = _python_targets(state)
    if not targets:
        return {"agents_succeeded": [MAINTAINABILITY_LABEL]}

    table = _metrics_table(state)
    prompt = _build_maintainability_prompt(state.get("pr_diff", ""), table)

    try:
        result = await analyze_with_schema(
            prompt, FindingList, system=MAINTAINABILITY_SYSTEM_PROMPT
        )
        llm_findings = list(result.findings) if isinstance(result, FindingList) else []
    except Exception as e:  # noqa: BLE001
        log.warning("maintainability LLM call failed; returning no findings: %s", e)
        llm_findings = []

    normalized = [f.model_copy(update={"agent": MAINTAINABILITY_LABEL}) for f in llm_findings]
    return {
        "findings": normalized,
        "agents_succeeded": [MAINTAINABILITY_LABEL],
    }
