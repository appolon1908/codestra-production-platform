#!/usr/bin/env python3
import argparse
import hashlib
import sqlite3
from pathlib import Path

parser = argparse.ArgumentParser(); parser.add_argument("source"); parser.add_argument("destination"); args = parser.parse_args()
source = Path(args.source).resolve(); destination = Path(args.destination).resolve()
if source == destination: raise SystemExit("source and destination must differ")
destination.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst: src.backup(dst)
digest = hashlib.sha256(destination.read_bytes()).hexdigest()
destination.with_suffix(destination.suffix + ".sha256").write_text(f"{digest}  {destination.name}\n")
print(destination)
