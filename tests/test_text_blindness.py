"""The flagship claim, checked structurally instead of by example.

`tests/test_injection.py` shows that twenty-two payloads and five substituted bodies never change a
verdict. That is evidence about a corpus. This file asserts the stronger, structural version: the
policy engine cannot read document text, because its source never reaches for it, and it cannot
execute anything, because it does not import the tools.

A check like this can rot into a vacuous one, so the positive control points the same scanner at
`tools.py`, which does read bodies, and requires it to find one.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "agentgate"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _attributes(tree: ast.Module) -> set[str]:
    return {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}


def _imports(tree: ast.Module) -> set[str]:
    """Top-level module names imported, e.g. `from .models import X` contributes `models`."""
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module.split(".")[-1])
            else:
                modules |= {alias.name for alias in node.names}
    return modules


def test_the_policy_engine_never_reaches_for_document_text():
    attributes = _attributes(_tree(ENGINE / "policy.py"))
    assert "body" not in attributes, "policy.py reads a .body attribute"
    assert "splitlines" not in attributes


def test_the_policy_engine_cannot_execute_anything():
    """No import of the tools, the store, or the gateway: the policy is a pure function of metadata."""
    imported = _imports(_tree(ENGINE / "policy.py"))
    forbidden = {"tools", "store", "gateway", "sessions", "workflow", "proposer"}
    assert not imported & forbidden, f"policy.py imports {imported & forbidden}"
    assert imported <= {"labels", "models", "annotations", "hashlib", "json", "pathlib",
                        "typing", "__future__"}, imported


def test_the_label_lattice_never_reaches_for_document_text():
    attributes = _attributes(_tree(ENGINE / "labels.py"))
    assert "body" not in attributes


def test_the_integrity_guard_decides_on_metadata_only():
    attributes = _attributes(_tree(ENGINE / "policy_guard.py"))
    assert "body" not in attributes, "the guard reads document text"


def test_the_gateway_never_branches_on_document_text():
    """`declassify` copies a body into a new artifact; nothing in the gateway compares or indexes one."""
    tree = _tree(ENGINE / "gateway.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "body":
            assert isinstance(node.ctx, ast.Load), "gateway.py assigns to a document body"
        if isinstance(node, ast.Compare):
            compared = [side for side in [node.left, *node.comparators]
                        if isinstance(side, ast.Attribute) and side.attr == "body"]
            assert not compared, "gateway.py compares a document body"

    # And the one legitimate use is the release copy, not a decision.
    owners = set()
    for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]:
        if "body" in _attributes(function):
            owners.add(function.name)
    assert owners == {"declassify"}, owners


def test_the_scanner_would_notice_a_body_read():
    """Positive control: `tools.py` does read bodies, and the scanner above must say so."""
    attributes = _attributes(_tree(ENGINE / "tools.py"))
    assert "body" in attributes and "splitlines" in attributes
