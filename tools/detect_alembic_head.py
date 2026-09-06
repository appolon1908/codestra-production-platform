#!/usr/bin/env python3
"""Print the sole Alembic head from a directory of revision modules."""

from __future__ import annotations

import ast
import sys
from pathlib import Path


def literal(node: ast.expr | None) -> object:
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError) as exc:
        raise ValueError("Alembic revision metadata must be literal") from exc


def declaration(tree: ast.Module, name: str) -> object:
    matches: list[object] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                matches.append(literal(node.value))
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                matches.append(literal(node.value))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {name} declaration")
    return matches[0]


def find_head(directory: Path) -> str:
    revisions: set[str] = set()
    parents: set[str] = set()
    files = sorted(directory.glob("*.py"))
    if not files:
        raise ValueError("no Alembic revision modules found")
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        revision = declaration(tree, "revision")
        if not isinstance(revision, str) or not revision:
            raise ValueError(f"invalid revision in {path.name}")
        if revision in revisions:
            raise ValueError(f"duplicate revision {revision}")
        revisions.add(revision)
        parent = declaration(tree, "down_revision")
        values = parent if isinstance(parent, (tuple, list)) else (parent,)
        for value in values:
            if value is not None:
                if not isinstance(value, str) or not value:
                    raise ValueError(f"invalid down_revision in {path.name}")
                parents.add(value)
    heads = sorted(revisions - parents)
    if len(heads) != 1:
        raise ValueError(f"expected one Alembic head, found {heads}")
    return heads[0]


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: detect_alembic_head.py REVISION_DIRECTORY")
    print(find_head(Path(sys.argv[1])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
