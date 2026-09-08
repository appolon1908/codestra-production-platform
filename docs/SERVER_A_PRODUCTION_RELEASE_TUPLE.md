# Server A production release tuple authority

This document removes the source-to-runtime ambiguity between the two Server A
repositories. It is an ownership contract, not production activation.

| Element | Authority | Candidate identity | Runtime artifact |
| --- | --- | --- | --- |
| Orchestration, JetStream definitions, host policy and evidence tooling | `appolon1908-hue/codestra-production-platform` | PR 15 exact protected merge SHA | signed deployment/configuration bundle |
| Middleware executable source | `appolon1908-hue/Middleware-` | protected source-lock exact SHA | `ghcr.io/appolon1908-hue/codestra-middleware@sha256:<production-approved-digest>` |
| Database migrations | canonical middleware image and its Alembic revision | read from the exact image | migration owner executes; runtime roles never own schemas |
| JetStream server contract | production-platform `eventing/jetstream_contract.json` | checksum from protected configuration bundle | applied and read back by `tools/apply_jetstream_contract.py` |
| JetStream publisher and DLQ worker | canonical middleware image | exact protected Appolon Middleware SHA | `app.eventing.jetstream` and `app.entrypoints.jetstream_dlq_worker` |
| Keycloak production middleware contract | `config/keycloak-production-contract.env.example` | checksum from the protected configuration bundle | production middleware issuer/client; not a webphone credential |
| Keycloak internal staging contract | `config/keycloak-staging-contract.env.example` | checksum from the protected configuration bundle | internal staging issuer/client/secret only; production delivery prohibited |
| Canonical TEST_SYN webphone machine contract | `config/keycloak-webphone-machine-contract.env.example`, `config/keycloak-webphone-machine-client.json`, and `config/keycloak-webphone-allowed-tenants.json` | checksums from the protected configuration bundle | canonical `.co` issuer, `codestra-provisioning-service-staging`, least-privilege service account, no production delivery |
| Odoo and n8n integration logic | canonical middleware image | exact protected middleware SHA | versioned image digest |
| Callback adapter contract | production-platform policy plus canonical middleware image | exact checksums and image digest | private authenticated adapter only |

The protected source lock currently selects Appolon Middleware source
`63b6c0c8bca5168a1178895bd12858d0b1e8086e` and signed digest
`sha256:bca7a220b9ce50411ae67e2115507329656c4ee351333d14568af3695e3c347a`.
That tuple is not deployed and remains pending protected staging, restore,
rollback and canary certification. Selection as forward authority is not
production authorization.

`Codestra-SRL/codestra-middleware` remains former rollback evidence only. Its
source, image and migration lineage must not populate a forward candidate or be
combined with the Appolon tuple.

Production deployment requires a generated manifest in which every placeholder
below is replaced by an exact protected merge SHA, digest or checksum. The
release gate must reject feature-branch SHAs, mutable image tags, a staging-only
approval, absent signatures, or any mismatch found by runtime readback.

## Change ownership

| Change | Owning repository | Reason | Required runtime artifact | Coverage |
| --- | --- | --- | --- | --- |
| Stream/consumer topology, retries, retention and replay policy | production-platform | infrastructure contract | signed configuration bundle | isolated real-NATS contract tests |
| Keycloak production/staging contract and PostgreSQL role policy | production-platform | deployment security policy | signed configuration bundle | authorization and isolated PostgreSQL tests |
| Event envelope validation and tenant/campaign subjects | canonical middleware | executable application behavior | middleware image | transport contract tests |
| Stable message-ID publication | canonical middleware | executable NATS client behavior | middleware image | publisher unit tests |
| Maximum-delivery advisory subscription and DLQ forwarding | both | platform provisions policy; middleware executes it | configuration bundle plus middleware image | real-NATS runtime and middleware worker tests |
| Odoo/n8n/callback effective-once implementation | canonical middleware | business integration behavior | middleware image | canonical integration suite |

Production flags remain false throughout candidate construction and staging.

The canonical webphone machine contract is authoritative for Keycloak client
creation only after its protected merge SHA is recorded. It does not activate
the client or repair runtime drift by itself. In particular, the provisioning
verifier must reject its currently deployed legacy `.agency` issuer setting and
be reconciled to the contract's canonical `.co` issuer in a separate approved
release before machine-token certification.

## Out-of-band release trust anchor

Before the canonical middleware worker can be enabled, a security owner must
deliver the approved SSH signing public key and its SHA-256 fingerprint through
independent protected channels. The public key is deliberately not trusted from
the release bundle that it authenticates. A host administrator provisions it
idempotently before installing the signed release:

```text
sudo python3 tools/provision_release_trust_anchor.py \
  --public-key /secure-bootstrap/codestra-release.pub \
  --expected-sha256 <independently-verified-64-hex-fingerprint> \
  --destination /etc/codestra/release/allowed_signers
```

The DLQ worker remains fail closed while this protected trust anchor, the signed
checksum manifest, or its signature is absent or inconsistent.
