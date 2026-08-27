#!/usr/bin/env bash
set -Eeuo pipefail

workspace=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
run_id="${GITHUB_RUN_ID:-local}-$$"
network="codestra-call-followup-ci-${run_id}"
postgres_container="codestra-call-followup-pg-${run_id}"
postgres_volume="codestra_call_followup_pg_${run_id}"
database=call_followup_ci
database_user=odoo_test
database_password=disposable-ci-only
odoo_image='odoo@sha256:94a4f480b8039dc9ca2bca9e77e59f97d3311f66e2aad663cf2670be9c66d4ea'
postgres_image='postgres@sha256:ef257d85f76e48da1c64832459b59fcaba1a4dac97bf5d7450c77753542eee94'

cleanup() {
    docker rm -f "$postgres_container" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
    docker volume rm "$postgres_volume" >/dev/null 2>&1 || true
}
trap cleanup EXIT

network_args=(--internal)
if [[ -n "${ODOO_TEST_SUBNET:-}" ]]; then
    network_args+=(--subnet "$ODOO_TEST_SUBNET")
fi
docker network create "${network_args[@]}" "$network" >/dev/null
docker volume create "$postgres_volume" >/dev/null
docker run -d --name "$postgres_container" \
    --network "$network" --network-alias call-followup-postgres \
    -e "POSTGRES_DB=$database" \
    -e "POSTGRES_USER=$database_user" \
    -e "POSTGRES_PASSWORD=$database_password" \
    -v "$postgres_volume:/var/lib/postgresql/data" \
    "$postgres_image" >/dev/null

for attempt in $(seq 1 40); do
    if docker exec "$postgres_container" \
        pg_isready -U "$database_user" -d "$database" >/dev/null 2>&1; then
        break
    fi
    if [[ "$attempt" -eq 40 ]]; then
        docker logs "$postgres_container"
        exit 1
    fi
    sleep 1
done

odoo() {
    docker run --rm -i --network "$network" \
        -e HOST=call-followup-postgres \
        -e PORT=5432 \
        -e "USER=$database_user" \
        -e "PASSWORD=$database_password" \
        -v "$workspace/odoo_addons:/mnt/extra-addons:ro" \
        "$odoo_image" odoo \
        -d "$database" \
        --db_host=call-followup-postgres \
        --db_port=5432 \
        --db_user="$database_user" \
        --db_password="$database_password" \
        --addons-path=/mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons \
        --stop-after-init --max-cron-threads=0 --workers=0 --without-demo \
        --log-level=warn \
        --log-handler=odoo.tests:TEST \
        --log-handler=odoo.addons.codestra_crm_call_followup:TEST \
        "$@"
}

odoo_shell() {
    docker run --rm -i --network "$network" \
        -e HOST=call-followup-postgres \
        -e PORT=5432 \
        -e "USER=$database_user" \
        -e "PASSWORD=$database_password" \
        -v "$workspace/odoo_addons:/mnt/extra-addons:ro" \
        "$odoo_image" odoo shell \
        -d "$database" \
        --db_host=call-followup-postgres \
        --db_port=5432 \
        --db_user="$database_user" \
        --db_password="$database_password" \
        --addons-path=/mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons \
        --no-http --max-cron-threads=0 --log-level=warn
}

echo 'DISPOSABLE_INSTALL_TEST=START'
odoo -i codestra_crm_call_followup \
    --test-enable --test-tags /codestra_crm_call_followup
echo 'DISPOSABLE_INSTALL_AND_TEST_SUITE=PASS'

# Build a pre-19.0.1.2.0 data shape after clean installation, then lower the
# installed version so the real migration runner must backfill it during -u.
cat <<'PY' | odoo_shell
from datetime import timedelta
from odoo import fields
from odoo.fields import Command

agent = env.ref('base.user_admin')
agent.email = 'legacy-agent@test.invalid'
customer = env['res.partner'].create({
    'name': 'Legacy Migration Customer',
    'email': 'legacy-customer@test.invalid',
})
callback_at = fields.Datetime.now() + timedelta(days=2)
followup = env['codestra.crm.call.followup'].sudo().create({
    'name': 'Legacy migration follow-up',
    'event_id': 'legacy-migration-event',
    'company_id': env.company.id,
    'agent_id': agent.id,
    'partner_id': customer.id,
    'ended_at': fields.Datetime.now(),
    'duration_seconds': 60,
    'state': 'completed',
    'disposition': 'callback',
    'schedule_kind': 'callback',
    'callback_at': callback_at,
    'duration_minutes': 30,
    'reminder_email_enabled': True,
    'send_post_call_email': False,
})
legacy_template = env.ref(
    'codestra_crm_call_followup.mail_template_callback_reminder_client_15'
)
legacy_alarm = env['calendar.alarm'].create({
    'name': 'Legacy direct email reminder',
    'alarm_type': 'email',
    'duration': 15,
    'interval': 'minutes',
    'mail_template_id': legacy_template.id,
})
env['ir.model.data'].create({
    'module': 'codestra_crm_call_followup',
    'name': 'calendar_alarm_email_15_minutes',
    'model': 'calendar.alarm',
    'res_id': legacy_alarm.id,
    'noupdate': True,
})
prepare_alarm = env.ref(
    'codestra_crm_call_followup.calendar_alarm_prepare_30_minutes'
)
event = env['calendar.event'].with_context(no_mail_to_attendees=True).create({
    'name': 'Legacy migration callback',
    'start': callback_at,
    'stop': callback_at + timedelta(minutes=30),
    'user_id': agent.id,
    'partner_ids': [Command.set([customer.id, agent.partner_id.id])],
    'alarm_ids': [Command.set([prepare_alarm.id, legacy_alarm.id])],
    'codestra_call_followup_id': followup.id,
    'codestra_schedule_kind': False,
})
mail_id = env.ref(
    'codestra_crm_call_followup.mail_template_post_call_followup'
).send_mail(
    followup.id,
    force_send=False,
    email_values={
        'email_to': customer.email,
        'email_cc': agent.email,
        'subject': 'Legacy queued post-call email',
    },
)
followup._write_from_workflow({
    'calendar_event_id': event.id,
    'mail_id': mail_id,
    'send_post_call_email': True,
    'email_to': customer.email,
    'email_cc': agent.email,
    'email_subject': 'Legacy queued post-call email',
    'email_body': '<p>Legacy queued post-call email.</p>',
})
env.cr.commit()
print(f'LEGACY_FIXTURE_EVENT_ID={event.id}')
print(f'LEGACY_FIXTURE_MAIL_ID={mail_id}')
PY

docker exec "$postgres_container" psql \
    -U "$database_user" -d "$database" -v ON_ERROR_STOP=1 \
    -c "UPDATE ir_module_module SET latest_version='19.0.1.1.0' WHERE name='codestra_crm_call_followup'" \
    >/dev/null

echo 'DISPOSABLE_MIGRATION_TEST=START'
odoo -u codestra_crm_call_followup
cat <<'PY' | odoo_shell
module = env['ir.module.module'].search([
    ('name', '=', 'codestra_crm_call_followup')
], limit=1)
assert module.state == 'installed', module.state
assert module.latest_version == '19.0.1.2.0', module.latest_version
followup = env['codestra.crm.call.followup'].sudo().search([
    ('event_id', '=', 'legacy-migration-event')
], limit=1)
assert followup, 'legacy follow-up missing'
event = followup.calendar_event_id.with_context(active_test=False)
assert event, 'legacy event missing'
assert event.codestra_schedule_kind == 'callback', event.codestra_schedule_kind
assert event.partner_ids == followup.agent_id.partner_id, event.partner_ids
legacy_alarm = env.ref(
    'codestra_crm_call_followup.calendar_alarm_email_15_minutes',
    raise_if_not_found=False,
)
assert not legacy_alarm or legacy_alarm not in event.alarm_ids, event.alarm_ids
legacy_mail = env['mail.mail'].sudo().search([
    ('subject', '=', 'Legacy queued post-call email')
], limit=1)
assert legacy_mail.state == 'cancel', legacy_mail.state
assert not followup.mail_id, followup.mail_id
immediate = followup.immediate_delivery_intent_id
assert immediate, 'legacy queued email was not migrated to Middleware intent'
assert immediate.state == 'pending', immediate.state
assert immediate.intent_type == 'post_call_email', immediate.intent_type
reminders = followup.delivery_intent_ids.filtered(
    lambda item: item.intent_type == 'callback_reminder'
)
assert len(reminders) == 2, reminders
assert set(reminders.mapped('audience')) == {'client', 'agent'}, reminders
assert set(reminders.mapped('state')) == {'pending'}, reminders
print('MIGRATION_SCHEDULE_KIND_BACKFILL=PASS')
print('MIGRATION_NATIVE_EMAIL_REMOVAL=PASS')
print('MIGRATION_QUEUED_MAIL_TO_MIDDLEWARE_INTENT=PASS')
print('MIGRATION_MIDDLEWARE_REMINDER_INTENTS=PASS')
PY

echo 'DISPOSABLE_MIGRATION_TEST=PASS'

module_state=$(docker exec "$postgres_container" psql \
    -U "$database_user" -d "$database" -Atqc \
    "SELECT state || ':' || latest_version FROM ir_module_module WHERE name='codestra_crm_call_followup'")
[[ "$module_state" == 'installed:19.0.1.2.0' ]]
echo "DISPOSABLE_UPGRADE_TEST=PASS state=$module_state"

cat <<'PY' | odoo_shell
module = env['ir.module.module'].search([
    ('name', '=', 'codestra_crm_call_followup')
], limit=1)
assert module.state == 'installed', module.state
module.button_immediate_uninstall()
env.cr.commit()
PY

module_state=$(docker exec "$postgres_container" psql \
    -U "$database_user" -d "$database" -Atqc \
    "SELECT state FROM ir_module_module WHERE name='codestra_crm_call_followup'")
followup_table_count=$(docker exec "$postgres_container" psql \
    -U "$database_user" -d "$database" -Atqc \
    "SELECT count(*) FROM pg_class WHERE relname='codestra_crm_call_followup'")
intent_table_count=$(docker exec "$postgres_container" psql \
    -U "$database_user" -d "$database" -Atqc \
    "SELECT count(*) FROM pg_class WHERE relname='codestra_crm_call_delivery_intent'")
[[ "$module_state" == 'uninstalled' ]]
[[ "$followup_table_count" == '0' ]]
[[ "$intent_table_count" == '0' ]]
echo "DISPOSABLE_UNINSTALL_TEST=PASS state=$module_state followup_table=$followup_table_count intent_table=$intent_table_count"
echo 'DISPOSABLE_DATABASE_CLEANUP=PASS'
