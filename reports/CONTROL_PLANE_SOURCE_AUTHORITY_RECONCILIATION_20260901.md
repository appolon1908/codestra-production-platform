# Control-plane source-authority reconciliation

Date: 2026-09-01

This is source-governance evidence only. It does not authorize or perform a
production build, deployment, restart, or migration.

## Compared authorities

- Runtime revision: `44d2addf48ae31da6eeb3c3f9ab3fe34d999042c`
- Protected authority head: `aa3d903648d5f7c4cc10acee93e509a37ac36f76`
- Protected branch: `release/production-activation`
- Repository: `appolon1908-hue/codestra-production-platform`

## Result

The runtime application is under `control_plane_service/`, not `control_plane/`.
The protected baseline differs from the runtime revision in eight existing
modules and adds three modules. The earlier byte-identical conclusion was
incorrect and is withdrawn. The checked-in
`CONTROL_PLANE_RUNTIME_44D2_SERVICE_TREE.patch` is an inspectable reconstruction
bundle from the named protected baseline to the exact runtime service tree; CI
reconstructs it and compares every file byte-for-byte with the runtime commit.

The histories diverge in deployment and migration material. The runtime branch
contains older/different control-plane Compose and Dockerfile definitions and
does not contain protected migration files `000_runtime_store.sql` and
`005_postal_inbound_inbox.sql`. It also differs in migrations 002 through 004.
Those files must not be copied wholesale over protected authority: doing so
would discard protected-only controls and change migration behavior.

## Decision

Disposition C — partially reconciled.

- Application source authority: the protected successor remains the proposed
  authority, but its differences from the certified runtime are explicit and
  require immutable-candidate behavioral validation before any deployment.
- Deployment and migration authority: protected head.
- Runtime-only source: retained by the reviewed reconstruction bundle
  `reports/CONTROL_PLANE_RUNTIME_44D2_SERVICE_TREE.patch`. CI applies it to
  protected baseline `aa3d903648d5f7c4cc10acee93e509a37ac36f76` and verifies
  the complete `control_plane_service/` file set and contents against
  `44d2addf48ae31da6eeb3c3f9ab3fe34d999042c`. This evidence survives the
  required squash merge without relying on PR ancestry.
- Production replacement: prohibited in this phase.
- Migration execution: prohibited in this phase.

## Change classes

- `CONTROL_PLANE_RUNTIME_ONLY_CHANGES`: the reconstruction patch records the
  exact runtime forms of eight differing service modules.
- `CONTROL_PLANE_PROTECTED_ONLY_CHANGES`: three service modules plus protected
  deployment hardening, runtime-store and Postal-inbox migrations, and
  subsequent reviewed controls.
- `CONTROL_PLANE_CONFLICTS`: Dockerfile, Compose definitions, and migrations
  002 through 004. Protected versions remain authoritative.

## Future immutable candidate gate

A candidate image may be built only from a merged protected commit, with OCI
source/revision/version labels, SBOM, provenance, vulnerability result, and an
exact digest. Deployment requires a later owner authorization and an explicit
migration-safety determination.
