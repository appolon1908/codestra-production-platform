"""Exercise the protected release consumer, not just its shared JSON parser."""

import base64
import hashlib
import json

import pytest

from tools import verify_signed_release_attestations as gate


def write(path, document):
    path.write_text(json.dumps(document), encoding="utf-8")


def envelope(predicate, kind, digest):
    statement = {
        "_type": "https://in-toto.io/Statement/v0.1",
        "predicateType": kind,
        "subject": [{"name": "ghcr.io/appolon1908-hue/codestra-middleware", "digest": {"sha256": digest.removeprefix("sha256:")}}],
        "predicate": predicate,
    }
    return {"payload": base64.b64encode(json.dumps(statement).encode()).decode()}


@pytest.fixture
def release(tmp_path):
    source, digest = "a" * 40, "sha256:" + "b" * 64
    manifest, copied, provenance, sbom = [tmp_path / name for name in ("manifest.json", "middleware.spdx.json", "provenance.json", "sbom.json")]
    sbom_doc = {"spdxVersion": "SPDX-2.3", "packages": [{"SPDXID": "SPDXRef-TEST", "filesAnalyzed": True}]}
    write(copied, sbom_doc)
    image = "ghcr.io/appolon1908-hue/codestra-middleware"
    write(manifest, {
        "source": {"git_sha": source},
        "image": {"digest": digest, "repository": image, "reference": image + "@" + digest, "platforms": ["linux/amd64"]},
        "build": {"workflow_identity": gate.AUTHORIZED_BUILDER},
        "artifacts": {"sbom": {"path": "middleware.spdx.json", "sha256": "sha256:" + hashlib.sha256(copied.read_bytes()).hexdigest()}},
    })
    predicate = {
        "buildDefinition": {
            "buildType": gate.EXPECTED_BUILD_TYPE,
            "externalParameters": {"sourceSha": source, "platform": "linux/amd64"},
            "resolvedDependencies": [{"uri": f"git+{gate.SOURCE_REPOSITORY}@{source}", "digest": {"gitCommit": source}}],
        },
        "runDetails": {"builder": {"id": gate.AUTHORIZED_BUILDER}},
    }
    write(provenance, envelope(predicate, "https://slsa.dev/provenance/v1", digest))
    write(sbom, envelope(sbom_doc, "https://spdx.dev/Document", digest))
    return manifest, copied, provenance, sbom, source, digest


@pytest.mark.parametrize("container", ["object", "array", "json-lines"])
def test_release_consumer_accepts_matching_authenticated_content(release, container):
    for path in release[2:4]:
        record = path.read_text()
        if container == "array":
            path.write_text("[" + record + "," + record + "]")
        elif container == "json-lines":
            path.write_text(record + "\n" + record)
    gate.validate(*release)


def test_release_consumer_rejects_boolean_integer_sbom_alias(release):
    sbom = release[3]
    record = json.loads(sbom.read_text())
    statement = json.loads(base64.b64decode(record["payload"]))
    statement["predicate"]["packages"][0]["filesAnalyzed"] = 1
    record["payload"] = base64.b64encode(json.dumps(statement).encode()).decode()
    write(sbom, record)
    with pytest.raises(ValueError, match="differs"):
        gate.validate(*release)


@pytest.mark.parametrize("field,value", [
    ("_type", "untrusted-statement"),
    ("predicateType", "untrusted-predicate"),
    ("subject", [{"name": "ghcr.io/untrusted/image", "digest": {"sha256": "b" * 64}}]),
    ("subject", [{"name": "ghcr.io/appolon1908-hue/codestra-middleware", "digest": {"sha256": "c" * 64}}]),
])
def test_release_consumer_preserves_type_and_digest_authority(release, field, value):
    record = json.loads(release[2].read_text())
    statement = json.loads(base64.b64decode(record["payload"]))
    statement[field] = value
    record["payload"] = base64.b64encode(json.dumps(statement).encode()).decode()
    write(release[2], record)
    with pytest.raises(ValueError):
        gate.validate(*release)


@pytest.mark.parametrize("index", [2, 3])
def test_release_consumer_requires_nonempty_verification_for_both_attestations(release, index):
    release[index].write_text("[]")
    with pytest.raises(ValueError):
        gate.validate(*release)


def test_release_consumer_rejects_duplicate_manifest_keys(release):
    manifest = release[0]
    original = manifest.read_text()
    image = json.loads(original)["image"]
    manifest.write_text(original[:-1] + ',"image":' + json.dumps(image) + '}')
    with pytest.raises(ValueError, match="duplicate JSON keys"):
        gate.validate(*release)


def test_release_consumer_rejects_duplicate_sbom_keys_even_with_correct_hash(release):
    manifest, copied = release[:2]
    copied.write_text(copied.read_text()[:-1] + ',"spdxVersion":"SPDX-2.3"}')
    record = json.loads(manifest.read_text())
    record["artifacts"]["sbom"]["sha256"] = "sha256:" + hashlib.sha256(copied.read_bytes()).hexdigest()
    write(manifest, record)
    with pytest.raises(ValueError, match="duplicate JSON keys"):
        gate.validate(*release)


@pytest.mark.parametrize("layer", ["envelope", "statement"])
def test_release_consumer_rejects_duplicate_verified_json_keys(release, layer):
    verified = release[3]
    record = json.loads(verified.read_text())
    if layer == "envelope":
        verified.write_text(json.dumps(record)[:-1] + ',"payload":' + json.dumps(record["payload"]) + '}')
    else:
        decoded = base64.b64decode(record["payload"]).decode()
        predicate = json.loads(decoded)["predicate"]
        decoded = decoded[:-1] + ',"predicate":' + json.dumps(predicate) + '}'
        record["payload"] = base64.b64encode(decoded.encode()).decode()
        write(verified, record)
    with pytest.raises(ValueError, match="duplicate JSON keys"):
        gate.validate(*release)
