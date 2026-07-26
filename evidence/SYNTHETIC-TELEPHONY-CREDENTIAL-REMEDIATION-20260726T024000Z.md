# Synthetic telephony credential remediation

Date: 2026-07-26 UTC  
Scope: staging synthetic identity acceptance only

## Trigger

The reviewed VICIdial provisioning verification script was run against a
previously verified-unused staging extension (`6198`) and a newly generated
synthetic username. The supported VICIdial Non-Agent API rejected the first
`add_user` operation. No VICIdial user, phone, managed PJSIP fragment, endpoint
registration, or adapter state record was created.

During diagnosis, the API response reflected a historical plaintext credential
from the adapter's configured legacy environment backup. The credential value
is intentionally omitted from all evidence and must be considered exposed even
though the API rejected it.

## Immediate containment

- Stopped `codestra-telephony-provisioning-adapter.service`.
- Encrypted the exact historical environment file into the root-only quarantine
  artifact below.
- Securely removed the plaintext legacy environment file.
- Left all persistent telephony and delivery kill switches disabled.
- Did not modify VICIdial MariaDB directly.
- Did not create or activate a synthetic telephony identity.

## Preserved artifact

- Host: `codestra-vicidial`
- Encrypted artifact:
  `/root/codestra-secret-quarantine/20260726T024000Z/vicidial-api-legacy.env.enc`
- Artifact SHA-256:
  `06a08d75191c16ddaa2761cd3279a4daf3b2fc27cac9de37d3330b9356212e11`
- Ownership/mode: root-only (`0600`)
- Plaintext source remaining: no
- Adapter final state: inactive

The encryption key and credential content are not included in this repository.

## Acceptance consequence

This event is not evidence of a runtime provisioning pass. VICIdial, SIP,
Agent Desktop, synthetic end-to-end, reconciliation, and rollback gates remain
unpassed until a valid dedicated staging API principal is proven through
redacted probes and a fresh synthetic lifecycle completes.
