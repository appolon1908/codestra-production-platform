# Protected release workflow plan

PR #12 introduces the first deterministic protected release workflow. Before it
can publish, configure `CODESTRA_RELEASE_SIGNING_KEY` and
`CODESTRA_RELEASE_SIGNING_PUBLIC_KEY` as Actions secrets. Follow-up release work
must pin every third-party action by immutable commit, build each deployable
image, scan secrets/dependencies/images, fail on unapproved High/Critical
findings, publish to the approved private registry, generate component SBOM and
provenance, sign digests/manifests and independently verify them.

The current source-bundle workflow is an implemented foundation, not sufficient
evidence for a multi-component production deployment. Deployment stays blocked
until all runtime images have exact digests and signed manifests.
