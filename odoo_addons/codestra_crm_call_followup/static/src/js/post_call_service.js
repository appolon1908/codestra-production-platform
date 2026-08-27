/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

const POST_CALL_CHANNEL = "codestra_crm_call_followup.post_call";
const PENDING_BATCH_SIZE = 20;
const MAX_REFRESH_PAGES = 100;
const RECOVERY_POLL_MS = 60_000;
const UNSAVED_CLOSE_DEFER_MS = 60_000;

const parseServerDateTime = (value) => {
    if (!value) {
        return Number.NaN;
    }
    const text = String(value).trim();
    if (!text) {
        return Number.NaN;
    }
    if (/[zZ]$|[+-]\d\d:\d\d$/.test(text)) {
        return Date.parse(text);
    }
    return Date.parse(`${text.replace(" ", "T")}Z`);
};

const postCallService = {
    dependencies: ["action", "bus_service", "notification", "orm"],

    start(env, { action, bus_service, notification, orm }) {
        const queue = [];
        const queuedOrOpen = new Set();
        const terminalFollowups = new Set();
        const deferredUntil = new Map();
        const wakeTimers = new Map();
        let dialogActive = false;
        let loadingPending = false;
        let refreshRequested = false;

        const clearWakeTimer = (followupId) => {
            const timer = wakeTimers.get(followupId);
            if (timer) {
                clearTimeout(timer);
                wakeTimers.delete(followupId);
            }
        };

        const scheduleWakeup = (followupId, wakeAt, fallbackDelay = RECOVERY_POLL_MS) => {
            clearWakeTimer(followupId);
            const parsed = parseServerDateTime(wakeAt);
            const target = Number.isFinite(parsed) ? parsed : Date.now() + fallbackDelay;
            const delay = Math.max(0, target - Date.now());
            deferredUntil.set(followupId, target);
            const timer = setTimeout(() => {
                wakeTimers.delete(followupId);
                deferredUntil.delete(followupId);
                terminalFollowups.delete(followupId);
                void loadPending();
            }, Math.min(delay, 2_147_483_647));
            wakeTimers.set(followupId, timer);
        };

        const handleStatusEvent = (item) => {
            const followupId = Number(item && item.followup_id);
            if (!followupId || !item.status) {
                return false;
            }
            if (item.status === "snoozed") {
                queuedOrOpen.delete(followupId);
                terminalFollowups.delete(followupId);
                scheduleWakeup(
                    followupId,
                    item.snoozed_until,
                    10 * 60_000
                );
                return true;
            }
            if (["completed", "cancelled"].includes(item.status)) {
                terminalFollowups.add(followupId);
                queuedOrOpen.delete(followupId);
                deferredUntil.delete(followupId);
                clearWakeTimer(followupId);
                return true;
            }
            return false;
        };

        const enqueue = (payload) => {
            let added = 0;
            for (const item of Array.isArray(payload) ? payload : [payload]) {
                if (handleStatusEvent(item)) {
                    continue;
                }
                const followupId = Number(item && item.followup_id);
                if (!followupId || terminalFollowups.has(followupId)) {
                    continue;
                }
                const deferred = deferredUntil.get(followupId);
                if (deferred && deferred > Date.now()) {
                    continue;
                }
                if (deferred) {
                    deferredUntil.delete(followupId);
                }
                if (queuedOrOpen.has(followupId)) {
                    continue;
                }
                queuedOrOpen.add(followupId);
                queue.push({ ...item, followup_id: followupId });
                added += 1;
            }
            if (added) {
                openNext();
            }
            return added;
        };

        const loadPending = async () => {
            if (loadingPending) {
                refreshRequested = true;
                return;
            }
            loadingPending = true;
            try {
                let afterEndedAt = false;
                let afterId = false;
                for (let page = 0; page < MAX_REFRESH_PAGES; page += 1) {
                    const items = await orm.call(
                        "codestra.crm.call.followup",
                        "get_pending_post_call_actions",
                        [],
                        {
                            limit: PENDING_BATCH_SIZE,
                            after_ended_at: afterEndedAt,
                            after_id: afterId,
                        }
                    );
                    if (!Array.isArray(items) || !items.length) {
                        break;
                    }

                    enqueue(items);
                    const last = items[items.length - 1];
                    afterEndedAt = last.ended_at;
                    afterId = last.followup_id;
                    if (
                        items.length < PENDING_BATCH_SIZE
                        || !afterEndedAt
                        || !afterId
                    ) {
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
            const followupId = item.followup_id;
            dialogActive = true;
            const actionDefinition = {
                type: "ir.actions.act_window",
                name: _t("Post-call follow-up"),
                res_model: "codestra.crm.post.call.wizard",
                view_mode: "form",
                views: [[false, "form"]],
                target: "new",
                context: {
                    default_followup_id: followupId,
                    dialog_size: "large",
                },
            };

            Promise.resolve(
                action.doAction(actionDefinition, {
                    onClose: () => {
                        dialogActive = false;
                        queuedOrOpen.delete(followupId);
                        if (
                            !terminalFollowups.has(followupId)
                            && !wakeTimers.has(followupId)
                        ) {
                            scheduleWakeup(
                                followupId,
                                Date.now() + UNSAVED_CLOSE_DEFER_MS
                            );
                        }
                        openNext();
                        void loadPending();
                    },
                })
            ).catch(() => {
                dialogActive = false;
                queuedOrOpen.delete(followupId);
                scheduleWakeup(
                    followupId,
                    Date.now() + UNSAVED_CLOSE_DEFER_MS
                );
                notification.add(
                    _t(
                        "The post-call form could not be opened. Open CRM › Call Follow-ups to complete it."
                    ),
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
        setInterval(() => void loadPending(), RECOVERY_POLL_MS);
        void loadPending();

        return { enqueue, loadPending };
    },
};

registry
    .category("services")
    .add("codestra_crm_call_followup.post_call", postCallService);
