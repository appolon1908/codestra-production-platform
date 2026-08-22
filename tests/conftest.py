"""Deterministic writable database path for clean-checkout test collection."""
import os
import tempfile


os.environ.setdefault(
    "CONTROL_PLANE_DB",
    os.path.join(tempfile.gettempdir(), f"codestra-control-plane-test-{os.getpid()}.db"),
)
