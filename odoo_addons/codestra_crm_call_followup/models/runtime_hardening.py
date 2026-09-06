from odoo import fields, models


class CodestraCrmCallFollowupRuntimeHardening(models.Model):
    """Odoo 19 field overrides required by the integrated extension set."""

    _inherit = "codestra.crm.call.followup"

    # Odoo 19 does not support mail.tracking.value generation for Html fields.
    # Notes remain visible in the immutable chatter summary created by the
    # completion workflow, but the raw Html field itself must not be tracked.
    notes = fields.Html(sanitize=True, tracking=False)
