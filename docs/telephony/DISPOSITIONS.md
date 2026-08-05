# Dispositions

The governed registry is `config/disposition-registry.json`. It defines notes,
callback, lead closure, supervisor, Odoo activity, workflow and compliance
effects. `DO_NOT_CALL` blocks outbound communication and creates the Odoo
activity through middleware; it is never a direct VICIdial-to-Odoo write.

