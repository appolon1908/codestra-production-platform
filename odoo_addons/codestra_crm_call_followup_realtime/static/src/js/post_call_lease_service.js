/** @odoo-module **/

import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

const POST_CALL_CHANNEL = "codestra_crm_call_followup.post_call";
const FOLLOWUP_MODEL = "codestra.crm.call.followup";
const FOLLOWUP_ACTION = "codestra_crm_call_followup.action_codestra_call_followup";
const CLIENT_STORAGE_KEY = "codestra.crm_call_followup.client_instance";
const RENEW_INTERVAL_MS = 40_000;
const RECOVERY_INTERVAL_MS = 60_000;

function makeClientInstanceId() {
    let value = browser.sessionStorage.getItem(CLIENT_STORAGE_KEY);
    if (value) {
        return value;
    }
    value = globalThis.crypto?.randomUUID?.()
        || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    browser.sessionStorage.setItem(CLIENT_STORAGE_KEY, value);
    return value;
}

const realtimePostCallService = {
    dependencies: ["action", "bus_service", "notification", "orm"],

    start(env, { action, bus_service, notification, orm }) {
        const clientInstanceId = makeClientInstanceId();
        let activeLease = null;
        let claimInFlight = false;
        let renewTimer = null;

        const openFollowupQueue = () => action.doAction(FOLLOWUP_ACTION);

        const clearRenewTimer = () => {
            if (renewTimer) {
                browser.clearInterval(renewTimer);
                renewTimer = null;
            }
        };

        const releaseLease = async (lease) => {
            if (!lease) {
                return;
            }
            try {
                await orm.call(
                    FOLLOWUP_MODEL,
                    "release_popup_lease",
                    [[lease.followup_id], clientInstanceId, lease.lease_token]
                );
            } catch {
                // Completion and snooze clear the lease server-side, so a stale
                // release is expected and does not make the action disappear.
            }
        };

        const renewLease = async () => {
            if (!activeLease) {
                return;
            }
            try {
                const result = await orm.call(
                    FOLLOWUP_MODEL,
                    "renew_popup_lease",
                    [
                        [activeLease.followup_id],
                        clientInstanceId,
                        activeLease.lease_token,
                    ]
                );
                activeLease.lease_expires_at = result.lease_expires_at;
            } catch {
                clearRenewTimer();
                notification.add(
                    _t("This post-call form is no longer owned by this browser tab. Close it and reopen the queue."),
                    {
                        title: _t("Popup lease expired"),
                        type: "warning",
                        sticky: true,
                        buttons: [
                            {
                                name: _t("Open Queue"),
                                primary: true,
                                onClick: openFollowupQueue,
                            },
                        ],
                    }
                );
            }
        };

        const claimAndOpen = async () => {
            if (activeLease || claimInFlight) {
                return;
            }
            claimInFlight = true;
            try {
                const claimed = await orm.call(
                    FOLLOWUP_MODEL,
                    "claim_pending_post_call_actions",
                    [clientInstanceId],
                    { limit: 1 }
                );
                const item = claimed[0];
                if (!item) {
                    return;
                }
                activeLease = item;
                renewTimer = browser.setInterval(renewLease, RENEW_INTERVAL_MS);

                await action.doAction(
                    {
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
                    },
                    {
                        onClose: async () => {
                            const lease = activeLease;
                            activeLease = null;
                            clearRenewTimer();
                            await releaseLease(lease);
                            claimAndOpen();
                        },
                    }
                );
            } catch {
                const lease = activeLease;
                activeLease = null;
                clearRenewTimer();
                await releaseLease(lease);
                notification.add(
                    _t("The leased post-call form could not be opened. The action remains in the shared queue."),
                    {
                        title: _t("Post-call action pending"),
                        type: "warning",
                        sticky: true,
                        buttons: [
                            {
                                name: _t("Open Queue"),
                                primary: true,
                                onClick: openFollowupQueue,
                            },
                        ],
                    }
                );
            } finally {
                claimInFlight = false;
            }
        };

        bus_service.subscribe(POST_CALL_CHANNEL, claimAndOpen);
        bus_service.start();
        claimAndOpen();
        browser.setInterval(claimAndOpen, RECOVERY_INTERVAL_MS);

        return {
            claimAndOpen,
            openFollowupQueue,
            clientInstanceId,
        };
    },
};

registry.category("services").add(
    "codestra_crm_call_followup.post_call",
    realtimePostCallService,
    { force: true }
);
