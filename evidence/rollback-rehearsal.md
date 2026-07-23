# Rollback rehearsal

The pre-migration Odoo 18 database and matching filestore recovery mechanics
passed in 30 seconds, including registry, users, and five attachments across
five models after restart. A rollback from an actually migrated Odoo 19
representative database was not possible because migration was not authorized
through an available route. Rollback owner approval is absent.

Result: `BLOCKED_EXTERNAL_PREREQUISITE`

