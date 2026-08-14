# SPEC-1 certificate and secret lifecycle

Production and staging identities are separate. Keys remain local or in the
approved secret manager. Renewal validates chain, exact SANs, EKU, key match and
post-swap readiness, uses atomic replacement and retains the prior valid pair on
failure. Key IDs/fingerprints—not secrets—are audit evidence.
