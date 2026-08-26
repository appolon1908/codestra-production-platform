# syntax=docker/dockerfile:1.7

ARG ODOO_BASE_IMAGE=odoo@sha256:f54272f31d5f77e4146b887efb3761c98480317daf687e4b4b5e76ed8bcc08c5
FROM ${ODOO_BASE_IMAGE}

ARG VCS_REF
ARG BUILD_DATE

LABEL org.opencontainers.image.title="Codestra Odoo 19 Call Follow-up" \
      org.opencontainers.image.description="Odoo 19 CRM post-call workflow, API, UX, and fail-closed automation addons" \
      org.opencontainers.image.source="https://github.com/appolon1908-hue/codestra-production-platform" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      com.codestra.release.integration-sha="b9b55274d726b2375f0a48ae30a2b1369c47e91c" \
      com.codestra.call-followup.automation-default="disabled"

USER root

RUN install -d -o odoo -g odoo /opt/codestra/addons /opt/codestra/release

COPY --chown=odoo:odoo odoo_addons/codestra_crm_call_followup /opt/codestra/addons/codestra_crm_call_followup
COPY --chown=odoo:odoo odoo_addons/codestra_crm_call_followup_api /opt/codestra/addons/codestra_crm_call_followup_api
COPY --chown=odoo:odoo odoo_addons/codestra_crm_call_followup_ux /opt/codestra/addons/codestra_crm_call_followup_ux
COPY --chown=odoo:odoo odoo_addons/codestra_crm_call_followup_automation /opt/codestra/addons/codestra_crm_call_followup_automation

COPY --chown=root:root deploy/odoo/call-followup-release/healthcheck.py /usr/local/bin/codestra-odoo-healthcheck
COPY --chown=root:root deploy/odoo/call-followup-release/release-manifest.json /opt/codestra/release/call-followup-manifest.json

RUN chmod 0555 /usr/local/bin/codestra-odoo-healthcheck \
    && python3 -m compileall -q /opt/codestra/addons \
    && find /opt/codestra/addons -type d -name __pycache__ -prune -exec rm -rf '{}' +

ENV PYTHONDONTWRITEBYTECODE=1

USER odoo

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=10 \
    CMD ["/usr/local/bin/codestra-odoo-healthcheck"]
