#!/usr/bin/env python3
"""Materialize the reviewed authority payload after exact release verification."""
from __future__ import annotations
import argparse, base64, hashlib, importlib.util, io, json, os, tarfile, tempfile
from pathlib import Path, PurePosixPath

PAYLOAD_SHA256 = "9faf571c4bd3cfad5c1ffc0ad35145adb4affbe3d67850186822c1df4cc869bb"
PAYLOAD_DIR = ".authority-payload"
EXPECTED = {
    ".github/workflows/protected-release.yml", "PRODUCTION-SOURCE-LOCK.yaml",
    "config/jetstream-dlq-worker.env.example", "config/production-release-tuple.json",
    "config/server-a-production-release-manifest.json.example",
    "deploy/middleware/approved-release-lock.json",
    "deploy/middleware/compose.approved-release.yaml",
    "deploy/middleware/compose.openai-provider.yaml",
    "deploy/middleware/openai-provider-release-lock.json",
    "docs/APPOLON_MIDDLEWARE_PRODUCTION_AUTHORITY_MIGRATION_20260903.md",
    "docs/SERVER_A_PRODUCTION_RELEASE_TUPLE.md",
    "tests/test_jetstream_worker_image.py", "tests/test_middleware_approved_release.py",
    "tests/test_middleware_release_evidence.py", "tests/test_release_bundle.py",
    "tests/test_server_a_release_tuple.py", "tools/build_release_bundle.py",
    "tools/validate_openai_provider_runtime_contract.py",
    "tools/verify_jetstream_worker_image.py",
    "tools/verify_middleware_release_evidence.py",
}
REMOVE = {
    ".github/workflows/appolon-middleware-authority-migration.yml",
    ".github/workflows/appolon-middleware-authority-gate.yml",
    ".github/workflows/appolon-middleware-authority-finalizer.yml",
    ".github/workflows/appolon-middleware-post-merge-release.yml",
    "tools/migrate_middleware_authority.py", "authority-migration-result.json",
}

def materialize(root: Path, staging: Path) -> None:
    parts = sorted((root / PAYLOAD_DIR).glob("part*"))
    if not parts:
        raise RuntimeError("authority payload parts are missing")
    encoded = "".join("".join(path.read_text().split()) for path in parts)
    payload = base64.b64decode(encoded, validate=True)
    if hashlib.sha256(payload).hexdigest() != PAYLOAD_SHA256:
        raise RuntimeError("authority payload checksum differs")
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        members = archive.getmembers()
        names = {m.name for m in members}
        if names != EXPECTED:
            raise RuntimeError(f"authority file set differs: {sorted(names ^ EXPECTED)}")
        for member in members:
            posix = PurePosixPath(member.name)
            if posix.is_absolute() or ".." in posix.parts or not member.isfile() or member.issym() or member.islnk():
                raise RuntimeError(f"unsafe authority member: {member.name}")
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError(f"unreadable authority member: {member.name}")
            destination = staging / member.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read())
            destination.chmod(0o755 if member.name.startswith("tools/") else 0o644)

def verify(staging: Path, evidence: Path) -> dict[str, str]:
    path = staging / "tools/verify_middleware_release_evidence.py"
    spec = importlib.util.spec_from_file_location("exact_middleware_release", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load exact release verifier")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.validate(evidence, staging / "config/production-release-tuple.json")

def install(root: Path, staging: Path) -> None:
    for relative in sorted(EXPECTED):
        source, destination = staging / relative, root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".authority-new")
        temporary.write_bytes(source.read_bytes()); temporary.chmod(source.stat().st_mode & 0o777)
        os.replace(temporary, destination)
    for relative in REMOVE:
        path = root / relative
        if path.exists() or path.is_symlink(): path.unlink()
    for path in sorted((root / PAYLOAD_DIR).glob("part*")):
        path.unlink()
    try: (root / PAYLOAD_DIR).rmdir()
    except OSError: pass

def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--root",type=Path,required=True); parser.add_argument("--evidence",type=Path,required=True); parser.add_argument("--output",type=Path)
    args=parser.parse_args(); root=args.root.resolve(); evidence=args.evidence.resolve()
    with tempfile.TemporaryDirectory(prefix="codestra-authority-") as directory:
        staging=Path(directory); materialize(root, staging); values=verify(staging,evidence); install(root,staging)
    result={"status":"GENERATED_REVIEW_ONLY","source_sha":values["MIDDLEWARE_PROTECTED_SHA"],"source_tree":values["MIDDLEWARE_SOURCE_TREE"],"image_reference":values["MIDDLEWARE_IMAGE_REFERENCE"],"migration_head":values["MIDDLEWARE_MIGRATION_HEAD"],"production_deployment_authorized":False,"external_effects":"DISABLED"}
    text=json.dumps(result,indent=2,sort_keys=True)+"\n"
    if args.output: args.output.write_text(text)
    print(text,end=""); return 0
if __name__ == "__main__": raise SystemExit(main())
