# Repository Profile — `codestra-production-platform`

## Identity

- **Repository:** `appolon1908-hue/codestra-production-platform`
- **Category:** Production integration, deployment, evidence, and rollback authority
- **Visibility:** Private
- **Default protected branch:** `release/production-activation`
- **Status:** Active protected production-source lineage

## Purpose

This repository coordinates the Codestra application platform where behavior crosses
component boundaries. It owns platform contracts, selected integration services and
Odoo addons, immutable deployment composition, source locks, release evidence,
rollback authority, and production-readback gates.

It is not a duplicate source home for every product. Principal component repositories
remain authoritative for their own implementation and release artifacts.

## Owns

- Cross-component API, event, identity, tenancy, and safety contracts.
- Platform-owned integration code, workers, validators, and selected Odoo 19 addons.
- Immutable server composition and exact component source/image locks.
- Staging, backup, restore, rollback, canary, soak, and production-readback evidence.
- Codestra Orbit deployment/adoption evidence while shared UI packages remain owned
  by `appolon1908-hue/SDK-repository`.
- Fail-closed production activation workflows.

## Does not own

- Canonical source already assigned to principal Middleware, Odoo, n8n, Keycloak,
  Kong, Caddy, observability, VICIdial, or provider repositories.
- Production credentials, private keys, customer records, recordings, or database
  dumps.
- A right to activate live effects merely because source was merged.

## Source-authority rule

Every external component reference must identify its authoritative repository,
protected commit SHA, immutable artifact digest, and verification evidence. Copied or
historical component trees are non-authoritative unless a documented migration makes
this repository their explicit source home.

## Branch and promotion rule

All active changes target `release/production-activation` through protected pull
requests. A stale feature branch, draft, local checkout, mutable image tag, or
unverified archive is not release authority.

Source promotion requires exact-head checks and a normal protected merge. Runtime
deployment remains a separate decision requiring environment evidence, rollback,
readback, and all applicable safety gates.

## Current operational priorities

1. Keep source authority unambiguous across principal repositories.
2. Remove or close obsolete stacked drafts after preserving their useful requirements.
3. Pin every production component to an accepted SHA and immutable digest.
4. Maintain paired database/filestore recovery for Odoo changes.
5. Keep outbound email, SMS, PSTN, provider, callback, and campaign effects disabled
   until their separate activation gates pass.
6. Preserve audited rollback and exact production readback for every runtime change.

## Safety boundary

This profile is source governance only. It does not deploy software, modify SSH,
rotate secrets, change DNS or firewall state, reload Caddy or Kong, migrate a live
database, recreate containers, enable workflows, send communications, or place calls.
