import hashlib
import json
import subprocess
import sys
from pathlib import Path


def test_release_bundle_is_reproducible_and_fail_closed(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    script = root / "tools" / "build_release_bundle.py"
    outputs = []
    for name in ("one", "two"):
        output = tmp_path / name
        subprocess.run(
            [
                sys.executable,
                str(script),
                "--root",
                str(root),
                "--output",
                str(output),
                "--commit",
                "a" * 40,
                "--run-id",
                "fixture-run",
                "--workflow-ref",
                "fixture-workflow",
            ],
            check=True,
        )
        outputs.append(output)
    archives = [next(path.glob("*.tar.gz")) for path in outputs]
    assert hashlib.sha256(archives[0].read_bytes()).digest() == hashlib.sha256(archives[1].read_bytes()).digest()
    deployment = json.loads((outputs[0] / "deployment-manifest.json").read_text())
    assert deployment["required_flags"]
    assert not any(deployment["required_flags"].values())
    sbom = json.loads((outputs[0] / "sbom.cdx.json").read_text())
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["components"]
