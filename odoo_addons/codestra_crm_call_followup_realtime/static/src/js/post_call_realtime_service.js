/** @odoo-module **/

import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

const CHANNEL = "codestra_crm_call_followup.post_call";
const API_MODEL = "codestra.crm.call.followup.realtime.api";
const CLIENT_KEY = "codestra.crm.call_followup.browser_client.v1";
const LEASE_SECONDS = 90;
const HEARTBEAT_MS = 45000;
const BUSY_RETRY_MS = 15000;

function browserClientId() {
    let value = browser.sessionStorage.getItem(CLIENT_KEY);
    if (!value) {
        value = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
        browser.sessionStorage.setItem(CLIENT_KEY, value);
    }
    return value;
}

const realtimePostCallService = {
    dependencies: ["action", "bus_service", "notification", "orm"],

    start(env, { action, bus_service, notification, orm }) {
        const clientId = browserClientId();
        const queue = [];
        const seen = new Set();
        let active = null;
        let heartbeat = null;

        const stopHeartbeat = () => {
            if (heartbeat) {
                browser.clearInterval(heartbeat);
                heartbeat = null;
            }
        };

        const release = async (reason = "closed") => {
            stopHeartbeat();
            if (!active) {
                return;
            }
            const current = active;
            active = null;
            try {
                await orm.call(
                    API_MODEL,
                    "release_v1",
                    [current.followupId, current.claimToken],
                    { reason }
                );
            } catch {
                // The lease expires server-side and is safely redelivered.
            }
        };

        const startHeartbeat = () => {
            stopHeartbeat();
            heartbeat = browser.setInterval(async () => {
                if (!active) {
                    return;
                }
                try {
                    const result = await orm.call(
                        API_MODEL,
                        "renew_v1",
                        [active.followupId, active.claimToken],
                        { lease_seconds: LEASE_SECONDS }
                    );
                    if (!result || !["renewed", "claimed"].includes(result.status)) {
                        stopHeartbeat();
                        notification.add(
                            _t("This post-call form lost its browser claim. Save your notes before reopening it from Call Follow-ups."),
                            { title: _t("Post-call claim expired"), type: "warning", sticky: true }
                        );
                    }
                } catch {
                    notification.add(
                        _t("The post-call claim heartbeat is temporarily unavailable. Odoo will recover the action if the lease expires."),
                        { title: _t("Connection interrupted"), type: "warning" }
                    );
                }
            }, HEARTBEAT_MS);
        };

        const openNext = async () => {
            if (active || !queue.length) {
                return;
            }
            const item = queue.shift();
            let claim;
            try {
                claim = await orm.call(
                    API_MODEL,
                    "claim_v1",
                    [item.followup_id, clientId],
                    { lease_seconds: LEASE_SECONDS }
                );
            } catch {
                seen.delete(item.followup_id);
                notification.add(
                    _t("The post-call action could not be claimed. It remains available in CRM › Call Follow-ups."),
                    { title: _t("Post-call action pending"), type: "warning", sticky: true }
                );
                void openNext();
                return;
            }

            if (claim.status === "busy") {
                browser.setTimeout(() => {
                    seen.delete(item.followup_id);
                    enqueue(item);
                }, BUSY_RETRY_MS);
                void openNext();
                return;
            }
            if (claim.status !== "claimed" || !claim.claim_token || !claim.action) {
                void openNext();
                return;
            }

            active = {
                followupId: item.followup_id,
                claimToken: claim.claim_token,
            };
            startHeartbeat();

            const actionPromise = action.doAction(claim.action, {
                onClose: async () => {
                    await release("closed");
                    void openNext();
                },
            });
            void orm.call(
                API_MODEL,
                "acknowledge_opened_v1",
                [item.followup_id, claim.claim_token]
            ).catch(() => {});

            Promise.resolve(actionPromise).catch(async () => {
                await release("error");
                seen.delete(item.followup_id);
                notification.add(
                    _t("The post-call form could not be opened. Use CRM › Call Follow-ups to complete it."),
                    { title: _t("Post-call action pending"), type: "warning", sticky: true }
                );
                void openNext();
            });
        };

        const enqueue = (payload) => {
            for (const raw of Array.isArray(payload) ? payload : [payload]) {
                const followupId = Number(raw?.followup_id);
                if (!followupId || seen.has(followupId)) {
                    continue;
                }
                seen.add(followupId);
                queue.push({ ...raw, followup_id: followupId });
            }
            void openNext();
        };

        bus_service.subscribe(CHANNEL, enqueue);
        orm.call(API_MODEL, "recover_v1", [clientId], { limit: 20 })
            .then((result) => enqueue(result?.items || []))
            .catch(() => {
                // Non-feature users and temporary startup failures remain silent.
            });

        return {
            enqueue,
            release,
            get activeFollowupId() {
                return active?.followupId || false;
            },
        };
    },
};

registry.category("services").add(
    "codestra_crm_call_followup.post_call",
    realtimePostCallService,
    { force: true }
);
