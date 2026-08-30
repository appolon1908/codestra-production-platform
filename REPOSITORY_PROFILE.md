# Repository Profile — `codestra-production-platform`

## Identity

- **Repository:** `appolon1908-hue/codestra-production-platform`
- **Category:** Platform reference and production evidence
- **Visibility:** `private`
- **Default branch:** `release/production-activation`
- **Authority:** Reference/evidence package; not a replacement for principal component repositories
- **Status:** Active production-package lineage with a nonstandard default branch.

## Purpose

Coordinates application-server production packaging, control-plane evidence, deployment instructions, and cross-component activation material for Codestra.

## Owns

- Cross-component production package and evidence
- Release coordination and server-A installation instructions
- Combined deployment references and activation records

## Does not own

- Canonical application/runtime source already owned by Middleware, Odoo, n8n, Keycloak, Kong, Caddy, or provider repositories
- Unreviewed live deployment authority
- Production secrets

## Key integrations

- Middleware
- Odoo
- n8n
- Redis
- Keycloak
- reverse proxy and monitoring repositories

## Current priorities

1. Keep it reference/evidence-only
2. Pin every component to exact accepted SHA and image digest
3. Remove server-specific instructions from reusable architecture where practical
4. Maintain backup, rollback, and go/no-go evidence

## Governance and safety

- Target promotion model: `feature/docs/fix/security/upgrade -> development -> test -> staging -> production -> main`.
- Use pull requests and exact-head/merge-result validation; merging source never authorizes deployment.
- Never commit secrets, credentials, private keys, customer data, database dumps, or secret-bearing evidence.
- Production images and releases must be immutable; mutable `latest` tags are not release authority.
- This document does not deploy software, enable live effects, apply identity state, alter DNS/firewalls, reload Caddy, expose native ports, initialize OpenBao, or activate production.

## Account-wide catalog

See `appolon1908-hue/documentaions/REPOSITORY_CATALOG.md`.
