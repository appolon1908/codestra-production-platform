/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

const POST_CALL_CHANNEL = "codestra_crm_call_followup.post_call";
const FOLLOWUP_ACTION = "codestra_crm_call_followup.action_codestra_call_followup";

const postCallService = {
    dependencies: ["action", "bus_service", "notification", "orm"],

    start(env, { action, bus_service, notification, orm }) {
        const queue = [];
        const seenFollowups = new Set();
        const urgentNotified = new Set();
        let dialogActive = false;

        const openFollowupQueue = () => action.doAction(FOLLOWUP_ACTION);

        const warnOpenFailure = (item) => {
            notification.add(
                _t(
                    "The post-call form could not be opened. The action remains in CRM › Call Follow-ups."
                ),
                {
                    title: _t("Post-call action still pending"),
                    type: "warning",
                    sticky: true,
                    buttons: [
                        {
                            name: _t("Open Call Follow-ups"),
                            primary: true,
                            onClick: openFollowupQueue,
                        },
                    ],
                }
            );
            seenFollowups.delete(item.followup_id);
        };

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
                warnOpenFailure(item);
                openNext();
            });
        };

        const enqueue = (payload) => {
            let added = 0;
            for (const item of Array.isArray(payload) ? payload : [payload]) {
                const followupId = Number(item && item.followup_id);
                if (!followupId || seenFollowups.has(followupId)) {
                    continue;
                }
                seenFollowups.add(followupId);
                queue.push({ ...item, followup_id: followupId });
                added += 1;

                if (
                    item.priority === "urgent" &&
                    dialogActive &&
                    !urgentNotified.has(followupId)
                ) {
                    urgentNotified.add(followupId);
                    notification.add(
                        _t("An urgent post-call action is waiting behind the current form."),
                        {
                            title: _t("Urgent follow-up queued"),
                            type: "warning",
                            sticky: true,
                            buttons: [
                                {
                                    name: _t("Open Queue"),
                                    onClick: openFollowupQueue,
                                },
                            ],
                        }
                    );
                }
            }

            if (added > 1) {
                notification.add(
                    _t("%s post-call actions are ready for completion.", added),
                    {
                        title: _t("Post-call queue recovered"),
                        type: "info",
                        buttons: [
                            {
                                name: _t("Open Queue"),
                                onClick: openFollowupQueue,
                            },
                        ],
                    }
                );
            }
            openNext();
        };

        const refreshPending = () =>
            Promise.resolve(
                orm.call(
                    "codestra.crm.call.followup",
                    "get_pending_post_call_actions",
                    [],
                    { limit: 20 }
                )
            )
                .then(enqueue)
                .catch(() => {
                    // Users without the feature group receive no startup popup.
                });

        bus_service.subscribe(POST_CALL_CHANNEL, enqueue);
        bus_service.start();
        refreshPending();

        return {
            enqueue,
            refreshPending,
            openFollowupQueue,
        };
    },
};

registry.category("services").add(
    "codestra_crm_call_followup.post_call",
    postCallService
);
