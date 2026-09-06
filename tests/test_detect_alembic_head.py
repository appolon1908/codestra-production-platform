from pathlib import Path

import pytest

from tools.detect_alembic_head import find_head


def test_detects_annotated_and_merge_revision_head(tmp_path: Path) -> None:
    (tmp_path / "one.py").write_text("revision = 'one'\ndown_revision = None\n")
    (tmp_path / "two.py").write_text("revision: str = 'two'\ndown_revision: str = 'one'\n")
    (tmp_path / "other.py").write_text("revision = 'other'\ndown_revision = 'one'\n")
    (tmp_path / "merge.py").write_text(
        "revision: str = 'merge'\ndown_revision = ('two', 'other')\n"
    )
    assert find_head(tmp_path) == "merge"


def test_rejects_multiple_heads(tmp_path: Path) -> None:
    (tmp_path / "one.py").write_text("revision = 'one'\ndown_revision = None\n")
    (tmp_path / "two.py").write_text("revision = 'two'\ndown_revision = None\n")
    with pytest.raises(ValueError, match="expected one Alembic head"):
        find_head(tmp_path)
