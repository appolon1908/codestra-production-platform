/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

const POST_CALL_CHANNEL = "codestra_crm_call_followup.post_call";

const postCallService = {
    dependencies: ["action", "bus_service", "notification", "orm"],

    start(env, { action, bus_service, notification, orm }) {
        const queue = [];
        const seenFollowups = new Set();
        let dialogActive = false;

        const openNext = () => {
            if (dialogActive || !queue.length) {
                return;
            }
            const item = queue.shift();
            dialogActive = true;

            const actionDefinition = {
                type: "ir.actions.act_window",
                name: _t("Post-call follow-up"),
                res_model: "codestra.crm.post.call.wizard",
                view_mode: "form",
                views: [[false, "form"]],
                target: "new",
                context: {
                    default_followup_id: item.followup_id,
                    dialog_size: "large",
                },
            };

            Promise.resolve(
                action.doAction(actionDefinition, {
                    onClose: () => {
                        dialogActive = false;
                        openNext();
                    },
                })
            ).catch(() => {
                dialogActive = false;
                seenFollowups.delete(item.followup_id);
                notification.add(
                    _t("The post-call form could not be opened. Open CRM › Call Follow-ups to complete it."),
                    {
                        title: _t("Post-call action pending"),
                        type: "warning",
                        sticky: true,
                    }
                );
                openNext();
            });
        };

        const enqueue = (payload) => {
            for (const item of Array.isArray(payload) ? payload : [payload]) {
                const followupId = Number(item && item.followup_id);
                if (!followupId || seenFollowups.has(followupId)) {
                    continue;
                }
                seenFollowups.add(followupId);
                queue.push({ ...item, followup_id: followupId });
            }
            openNext();
        };

        bus_service.subscribe(POST_CALL_CHANNEL, enqueue);

        Promise.resolve(
            orm.call(
                "codestra.crm.call.followup",
                "get_pending_post_call_actions",
                [],
                { limit: 10 }
            )
        )
            .then(enqueue)
            .catch(() => {
                // Users without the feature group receive no startup popup.
            });

        return { enqueue };
    },
};

registry.category("services").add("codestra_crm_call_followup.post_call", postCallService);
