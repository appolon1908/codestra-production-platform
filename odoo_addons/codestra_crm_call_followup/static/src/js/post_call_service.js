/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

const POST_CALL_CHANNEL = "codestra_crm_call_followup.post_call";
const PENDING_BATCH_SIZE = 20;
const MAX_REFRESH_PAGES = 10;

const postCallService = {
    dependencies: ["action", "bus_service", "notification", "orm"],

    start(env, { action, bus_service, notification, orm }) {
        const queue = [];
        const seenFollowups = new Set();
        let dialogActive = false;
        let loadingPending = false;
        let refreshRequested = false;

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
            }
            openNext();
            return added;
        };

        const loadPending = async () => {
            if (loadingPending) {
                refreshRequested = true;
                return;
            }
            loadingPending = true;
            try {
                for (let page = 0; page < MAX_REFRESH_PAGES; page += 1) {
                    const items = await orm.call(
                        "codestra.crm.call.followup",
                        "get_pending_post_call_actions",
                        [],
                        {
                            limit: PENDING_BATCH_SIZE,
                            exclude_ids: Array.from(seenFollowups).slice(-200),
                        }
                    );
                    enqueue(items);
                    if (!Array.isArray(items) || items.length < PENDING_BATCH_SIZE) {
                        break;
                    }
                }
            } catch {
                // Users without the feature group receive no startup popup.
            } finally {
                loadingPending = false;
                if (refreshRequested) {
                    refreshRequested = false;
                    void loadPending();
                }
            }
        };

        function openNext() {
            if (dialogActive) {
                return;
            }
            if (!queue.length) {
                void loadPending();
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
        }

        bus_service.subscribe(POST_CALL_CHANNEL, enqueue);
        void loadPending();

        return { enqueue, loadPending };
    },
};

registry.category("services").add("codestra_crm_call_followup.post_call", postCallService);
