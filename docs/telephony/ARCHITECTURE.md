# Telephony architecture

VICIdial and Asterisk own call runtime only. The restricted adapter exposes
allowlisted, authenticated operations and never makes VICIdial the customer
system of record. Middleware at `65.109.65.169` owns customer identity,
permissions, approvals, workflow, audit and Odoo synchronization. Voice AI at
`5.9.108.250` receives only authenticated staging media context and cannot
activate campaigns, modify carriers or dial arbitrary destinations.

All production activation, bulk outbound, arbitrary-number calling,
autonomous customer calls/messages, carrier changes and trunk changes remain
disabled. The passive AMI gateway stores events in a local durable outbox while
external delivery remains disabled pending Section 2 verification.

