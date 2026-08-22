# Extension reconciliation

Extension number, Asterisk endpoint, VICIdial phone/device, and agent assignment are distinct records. A partial unique index guarantees one active owner per extension. Reconciliation reads both VICIdial and Asterisk. Missing inactive test mappings may be remediated; ownership changes, endpoint collisions, and unexpected registrations require approval. Extension 6101 is reserved for bounded `TEST_SYN` certification and does not authorize live calls.
