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

The complete `control_plane/` Python source tree is byte-identical between the
runtime revision and the protected head. The 16 runtime Python modules sampled
from the running image were previously shown to match the runtime revision.
Consequently the protected head preserves the currently certified application
implementation.

The histories diverge in deployment and migration material. The runtime branch
contains older/different control-plane Compose and Dockerfile definitions and
does not contain protected migration files `000_runtime_store.sql` and
`005_postal_inbound_inbox.sql`. It also differs in migrations 002 through 004.
Those files must not be copied wholesale over protected authority: doing so
would discard protected-only controls and change migration behavior.

## Decision

Disposition C — partially reconciled.

- Application source authority: protected head, because its `control_plane/`
  tree exactly preserves the runtime application source.
- Deployment and migration authority: protected head.
- Runtime-only history: retained by immutable Git object
  `44d2addf48ae31da6eeb3c3f9ab3fe34d999042c` and this reconciliation record.
- Production replacement: prohibited in this phase.
- Migration execution: prohibited in this phase.

## Change classes

- `CONTROL_PLANE_RUNTIME_ONLY_CHANGES`: historical migration RBAC delta within
  the divergent branch; no runtime Python module delta.
- `CONTROL_PLANE_PROTECTED_ONLY_CHANGES`: protected deployment hardening,
  runtime-store and Postal-inbox migrations, and subsequent reviewed controls.
- `CONTROL_PLANE_CONFLICTS`: Dockerfile, Compose definitions, and migrations
  002 through 004. Protected versions remain authoritative.

## Future immutable candidate gate

A candidate image may be built only from a merged protected commit, with OCI
source/revision/version labels, SBOM, provenance, vulnerability result, and an
exact digest. Deployment requires a later owner authorization and an explicit
migration-safety determination.
