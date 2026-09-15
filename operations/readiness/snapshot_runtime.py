#!/usr/bin/env python3
"""Capture and verify the runtime files needed by the paired backup.

Only metadata is emitted. Secret-bearing configuration is copied directly into
the protected backup archive, never printed. No image pulls or runtime writes.
"""

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import tarfile


CONTAINERS = (
    "codestra-postgres-1", "codestra-redis-1", "codestra-odoo-1",
    "codestra-middleware-1", "codestra-n8n-1",
    "codestra-identity-identity-db-1", "codestra-identity-keycloak-1",
    "codestra-identity-auth-gateway-1",
)
BASE_PATHS = (
    "/etc/codestra/secrets", "/etc/caddy", "/opt/codestra/env",
    "/opt/codestra/config/odoo", "/opt/codestra/odoo-addons",
    "/opt/codestra/staging-sources/app-odoo-identity-timezone-57ab123cded2-r2",
)
APPLICATION_VOLUMES = {
    "odoo": ("codestra-odoo-1", "codestra_odoo_data", "/var/lib/odoo"),
    "n8n": ("codestra-n8n-1", "codestra_n8n_data", "/home/node/.n8n"),
}


def docker_json(*arguments):
    return json.loads(subprocess.run(
        ["docker", *arguments], check=True, capture_output=True, text=True,
        timeout=30,
    ).stdout)


def validate_path(raw):
    path = Path(raw)
    if (not path.is_absolute() or ".." in path.parts or len(path.parts) < 3
            or any(c in raw for c in "\n\r\0")
            or path.parts[1] in {"proc", "sys", "dev", "run"}):
        raise ValueError("unsafe backup source path")
    info = path.stat()
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise ValueError("backup source must be a file or directory")
    return path


def minimal_paths(paths):
    result = []
    for path in sorted(set(paths), key=lambda p: (len(p.parts), str(p))):
        if not any(parent == path or parent in path.parents for parent in result):
            result.append(path)
    return sorted(result, key=str)


def make_layout(containers, volumes, base_paths=BASE_PATHS):
    by_name = {item["Name"].lstrip("/"): item for item in containers}
    if set(by_name) != set(CONTAINERS):
        raise ValueError("incomplete runtime container inventory")
    config_paths = set()

    def include(raw):
        path = validate_path(raw)
        config_paths.add(path)
        # Preserve both the link and its target when a mounted path is a link.
        if path.resolve() != path:
            config_paths.add(validate_path(str(path.resolve())))

    for raw in base_paths:
        include(raw)
    records = []
    for name in CONTAINERS:
        item = by_name[name]
        if item["State"]["Status"] != "running" or item["State"].get("Paused"):
            raise ValueError("runtime container is not running")
        labels = item["Config"].get("Labels") or {}
        files = labels.get("com.docker.compose.project.config_files", "").split(",")
        if not files or any(not name for name in files):
            raise ValueError("missing effective Compose file list")
        for path in files:
            include(path)
        binds = []
        for mount in item["Mounts"]:
            if mount["Type"] != "bind":
                continue
            # The shared PostgreSQL WAL spool is mutable database recovery
            # data. Logical dumps cover these databases in this backup.
            if mount["RW"]:
                if (name == "codestra-postgres-1"
                        and mount["Destination"] == "/var/spool/codestra/postgresql-shared/wal"):
                    continue
                raise ValueError("unclassified writable runtime bind mount")
            include(mount["Source"])
            binds.append({"source": mount["Source"], "destination": mount["Destination"]})
        records.append({
            "name": name, "container_id": item["Id"], "image_id": item["Image"],
            "user": item["Config"].get("User", ""), "compose_files": files,
            "readonly_binds": sorted(binds, key=lambda x: x["destination"]),
        })
    app_volumes = {}
    for alias, (name, volume_name, destination) in APPLICATION_VOLUMES.items():
        mounts = [m for m in by_name[name]["Mounts"]
                  if m["Type"] == "volume" and m.get("Name") == volume_name
                  and m["Destination"] == destination]
        volume = volumes[volume_name]
        if len(mounts) != 1 or volume["Driver"] != "local" or volume.get("Options"):
            raise ValueError("unexpected application volume layout")
        path = validate_path(volume["Mountpoint"])
        if not path.is_dir() or path.is_symlink() or mounts[0]["Source"] != str(path):
            raise ValueError("application volume mount does not match inspection")
        owner = path.stat()
        app_volumes[alias] = {"name": volume_name, "mountpoint": str(path),
                              "uid": owner.st_uid, "gid": owner.st_gid}
    command = by_name["codestra-odoo-1"]["Config"].get("Cmd") or []
    addon_paths = []
    for index, argument in enumerate(command):
        if argument.startswith("--addons-path="):
            addon_paths.append(argument.split("=", 1)[1])
        elif argument == "--addons-path" and index + 1 < len(command):
            addon_paths.append(command[index + 1])
    if len(addon_paths) != 1 or not addon_paths[0]:
        raise ValueError("effective Odoo addon path is not explicit")
    return {
        "schema_version": 1, "containers": records,
        "configuration_paths": [str(p) for p in minimal_paths(config_paths)],
        "application_volumes": app_volumes, "odoo_addons_path": addon_paths[0],
    }


def capture():
    containers = docker_json("inspect", *CONTAINERS)
    volumes = docker_json("volume", "inspect", *(x[1] for x in APPLICATION_VOLUMES.values()))
    return make_layout(containers, {v["Name"]: v for v in volumes})


def archive_volumes(layout, output):
    with tarfile.open(output, "w:gz", dereference=False) as archive:
        for alias in sorted(APPLICATION_VOLUMES):
            path = validate_path(layout["application_volumes"][alias]["mountpoint"])
            archive.add(path, arcname=alias)


def verify_configuration(layout, archive_path):
    with tarfile.open(archive_path, "r:gz") as archive:
        names = {member.name.rstrip("/") for member in archive.getmembers()}
    required = set(layout["configuration_paths"])
    for container in layout["containers"]:
        required.update(container["compose_files"])
        required.update(mount["source"] for mount in container["readonly_binds"])
    for path in required:
        if path.lstrip("/") not in names:
            raise ValueError("runtime configuration source missing from archive")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("inventory", "verify-layout", "archive-volumes", "verify-configuration"))
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    manifest = args.work_dir / "runtime-layout.json"
    if args.action == "inventory":
        layout = capture()
        manifest.write_text(json.dumps(layout, indent=2, sort_keys=True) + "\n")
        (args.work_dir / "configuration-paths.nul").write_bytes(
            b"".join(path.lstrip("/").encode() + b"\0" for path in layout["configuration_paths"]))
        volume = layout["application_volumes"]["odoo"]
        (args.work_dir / "odoo-volume-owner.txt").write_text(f"{volume['uid']}:{volume['gid']}\n")
        print("RUNTIME_BACKUP_PREFLIGHT=PASS")
        return
    layout = json.loads(manifest.read_text())
    if args.action == "verify-layout":
        if layout != capture():
            raise ValueError("runtime changed during backup")
        print("RUNTIME_LAYOUT_UNCHANGED=PASS")
    elif args.action == "archive-volumes":
        archive_volumes(layout, args.work_dir / "application-volumes.tar.gz")
    else:
        verify_configuration(layout, args.work_dir / "configuration.tar.gz")
        print("CONFIGURATION_SCOPE_GATE=PASS_EXACT_ACTIVE_PATHS")


if __name__ == "__main__":
    main()
