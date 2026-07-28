import hashlib
from pathlib import Path


ROOT = Path(__file__).parents[1]

AUTHORITATIVE_SHA256 = {
    "scripts/canonical_event_client.py.reference": (
        "03c17d910768d3ccb11d421953e9fc916f510c6d0097b8b47418f978c4ce1806"
    ),
    "scripts/vicidial_sync.py.candidate": (
        "f8a329b1808331c53ca6d5e02c9c002de3bd10437b3061a26d030e594a199b9c"
    ),
}


def test_recovered_root_test_dependencies_match_deployed_evidence():
    for relative_path, expected_sha256 in AUTHORITATIVE_SHA256.items():
        payload = (ROOT / relative_path).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == expected_sha256
