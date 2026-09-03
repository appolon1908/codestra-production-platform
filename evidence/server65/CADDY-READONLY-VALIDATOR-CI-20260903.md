# Caddy bounded read-only validator CI evidence

Captured: 2026-09-03
Repository: `appolon1908-hue/Caddy`
PR: https://github.com/appolon1908-hue/Caddy/pull/42
Exact head: `7cc5fc7f4212cd2f4499d6d272ec50f628b71944`

The branch was updated from the current `origin/main` and its canonical
observability source-bundle checksum was regenerated and validated as:

`d9ad617b0e335e92c2cc598719df1de650f3fe63973e7e5645450f9d5ea6a347`

Protected checks at the exact head:

- `validate`: PASS
- `validate-source`: PASS
- `validate-merge-result`: PASS

The reviewed validator remains source-only and permits only fixed-target
`caddy validate`, sanitized adaptation, and service-status inspection. It does
not install itself, reload Caddy, alter SSH, or grant an arbitrary shell.

PR state is open with `REVIEW_REQUIRED`; the change is not merged or installed
on Server 65. Therefore this evidence does not certify live Caddy runtime
alignment. `PRODUCTION_CHANGED=NO`; `SSH_CHANGED=NO`.
