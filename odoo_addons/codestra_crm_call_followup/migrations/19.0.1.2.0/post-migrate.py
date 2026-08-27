from odoo import SUPERUSER_ID, Command, _, api, fields


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    events = env["calendar.event"].with_context(active_test=False).search(
        [("codestra_call_followup_id", "!=", False)]
    )
    legacy_email_alarm = env.ref(
        "codestra_crm_call_followup.calendar_alarm_email_15_minutes",
        raise_if_not_found=False,
    )

    for event in events:
        followup = event.codestra_call_followup_id
        values = {}

        if (
            not event.codestra_schedule_kind
            and followup.schedule_kind in {"callback", "appointment"}
        ):
            values["codestra_schedule_kind"] = followup.schedule_kind

        if legacy_email_alarm and legacy_email_alarm in event.alarm_ids:
            values["alarm_ids"] = [Command.unlink(legacy_email_alarm.id)]

        # Existing client attendees could otherwise continue receiving native
        # Odoo invitation/update/reminder emails. Keep the assigned internal
        # agent as the only attendee; the customer remains linked on followup.
        agent_partner = followup.agent_id.partner_id
        if event.partner_ids != agent_partner:
            values["partner_ids"] = [Command.set(agent_partner.ids)]

        if values:
            event.with_context(
                skip_codestra_followup_sync=True,
                no_mail_to_attendees=True,
                mail_notify_force_send=False,
            ).write(values)

    # Convert unsent mail queued by 19.0.1.1.0 into durable Middleware-owned
    # delivery intents. Cancelling the old mail first prevents the Odoo mail
    # queue from racing with the migration.
    legacy_outgoing = env["codestra.crm.call.followup"].with_context(
        active_test=False
    ).search(
        [("mail_id.state", "in", ["outgoing", "exception"])]
    )
    for followup in legacy_outgoing:
        legacy_mail = followup.mail_id.sudo()
        legacy_mail.write({"state": "cancel"})
        recipient_to = (
            followup.email_to
            or legacy_mail.email_to
            or followup.partner_id.email
            or followup.lead_id.email_from
            or ""
        ).strip()
        if not recipient_to:
            followup._write_from_workflow({"mail_id": False})
            continue
        intent = followup._create_delivery_intent(
            intent_type="post_call_email",
            audience="client",
            idempotency_key=(
                f"call-followup:{followup.company_id.id}:{followup.id}:"
                "post-call-email:v1"
            ),
            available_at=fields.Datetime.now(),
            recipient_to=recipient_to,
            recipient_cc=(
                followup.email_cc or legacy_mail.email_cc or ""
            ).strip()
            or False,
            subject=(
                followup.email_subject
                or legacy_mail.subject
                or _("Call follow-up")
            ).strip(),
            body_html=followup.email_body or legacy_mail.body_html or "",
        )
        followup._write_from_workflow(
            {
                "mail_id": False,
                "immediate_delivery_intent_id": intent.id,
            }
        )

    if legacy_email_alarm:
        legacy_xmlid = env["ir.model.data"].search(
            [
                ("module", "=", "codestra_crm_call_followup"),
                ("name", "=", "calendar_alarm_email_15_minutes"),
            ],
            limit=1,
        )
        legacy_email_alarm.unlink()
        if legacy_xmlid.exists():
            legacy_xmlid.unlink()

    scheduled = events.mapped("codestra_call_followup_id").filtered(
        lambda followup: (
            followup.reminder_email_enabled
            and followup.schedule_kind in {"callback", "appointment"}
            and followup.callback_at
        )
    )
    if scheduled:
        scheduled._sync_reminder_delivery_intents()
