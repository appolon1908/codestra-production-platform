# Cross-service contract catalog

`catalog.v1.json` is the central inventory of contracts that cross repository
or service boundaries. Adding a contract requires a stable ID, one authority
path, explicit consumers, compatibility policy, and a fail-closed activation
state.

Service repositories may own private implementation schemas. A contract that
is consumed by another service must be registered here before its release is
eligible for the central platform manifest. Registration does not copy private
keys, credentials, runtime payloads, or customer data into this repository.

Contract changes use a short-lived `contract/<domain>-v<version>` branch,
pass the platform source gate, and merge into the protected
`release/production-activation` baseline before dependent service releases are
pinned.
