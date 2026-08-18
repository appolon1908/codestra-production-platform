import base64
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

VICIDIAL_PRIVATE_HOSTS = frozenset(
    {
        "authorization.internal.codestra.agency",
        "edge.internal.codestra.agency",
    }
)
VICIDIAL_PRIVATE_PORT = 8443
VICIDIAL_ENDPOINT_ADAPTER_PORT = 8444
VICIDIAL_SECRET_ROOT = Path("/run/secrets/vicidial-mtls")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")
    database_url: str = "postgresql+asyncpg://localhost/codestra_middleware"
    database_url_file: str = ""
    redis_url: str = "redis://localhost:6379/2"
    redis_url_file: str = ""
    registry_snapshot_signing_key_file: str = ""
    registry_l1_ttl_seconds: int = 15
    registry_l2_ttl_seconds: int = 60
    registry_stale_grace_seconds: int = 300
    registry_service_issuer: str = ""
    registry_service_audience: str = "codestra-middleware"
    registry_service_jwks_url: str = ""
    registry_service_client_id: str = "codestra-registry-client"
    ingestion_hmac_secret: str = ""
    ingestion_token: str = ""
    middleware_secret: str = ""
    middleware_secret_file: str = ""
    webhook_shared_secret: str = ""
    webhook_shared_secret_file: str = ""
    vicidial_callback_hmac_secret_file: str = ""
    signature_ttl_seconds: int = 300
    request_max_bytes: int = 262144
    database_pool_size: int = 8
    database_max_overflow: int = 4
    database_pool_timeout_seconds: int = 5
    enabled_event_types: str = (
        "vicidial.call.started,vicidial.call.connected,vicidial.call.ended"
    )
    allowed_client_instances: str = "vicidial-server-b"
    live_writes_enabled: bool = False
    odoo_write_enabled: bool = False
    allow_non_test_campaigns: bool = False
    odoo_delivery_enabled: bool = False
    n8n_delivery_enabled: bool = False
    n8n_event_delivery_enabled: bool = False
    order_orchestration_enabled: bool = False
    n8n_order_dispatch_enabled: bool = False
    n8n_production_workflows_enabled: bool = False
    automation_actions_enabled: bool = False
    odoo_automation_writes_enabled: bool = False
    vicidial_read_enabled: bool = False
    vicidial_write_enabled: bool = False
    transfer_control_enabled: bool = False
    vicidial_authorization_url: str = ""
    vicidial_edge_url: str = ""
    vicidial_ca_file: str = ""
    vicidial_client_cert_file: str = ""
    vicidial_client_key_file: str = ""
    vicidial_crl_file: str = ""
    callback_dispatch_enabled: bool = False
    messaging_enabled: bool = False
    external_dial_enabled: bool = False
    ai_private_api_enabled: bool = False
    ai_service_id: str = "qwen"
    ai_worker_service_id: str = "qwen-polling-worker"
    ai_worker_source_cidrs: str = "10.40.0.4/32"
    ai_worker_trusted_proxy_cidr: str = "10.250.241.2/32"
    ai_worker_certificate_serial: str = "3008"
    ai_worker_certificate_ip: str = "10.40.0.4"
    ai_worker_spiffe_id: str = "spiffe://codestra.internal/worker/qwen"
    ai_worker_hmac_key_id: str = "qwen-polling-worker-hmac-v1"
    ai_worker_id: str = "qwen-ai-01-worker"
    ai_worker_tenant_id: str = ""
    ai_worker_workspace_id: str = ""
    ai_worker_client_ca_file: str = ""
    ai_hmac_secret_file: str = ""
    ai_audit_log_file: str = ""
    ai_signature_ttl_seconds: int = 300
    ai_rate_limit_per_minute: int = 60
    ai_command_timeout_seconds: int = 10
    ai_job_lease_seconds: int = 60
    ai_job_max_attempts: int = 5
    ai_job_max_context_bytes: int = 131072
    ai_job_max_output_bytes: int = 1048576
    ai_job_project_allowlist: str = ""
    ai_submissions_enabled: bool = False
    ai_orchestration_enabled: bool = False
    ai_worker_claims_enabled: bool = False
    ai_default_max_queued_per_tenant: int = 100
    ai_default_max_running_per_tenant: int = 5
    ai_daily_token_quota: int = 100000
    ai_global_emergency_limit: int = 0
    openai_provider_enabled: bool = False
    openai_worker_service_id: str = "openai-responses-provider"
    openai_worker_id: str = "codestra-openai-01"
    openai_worker_max_concurrency: int = 1
    openai_api_key_file: str = ""
    openai_safety_salt_file: str = ""
    openai_chat_model: str = "gpt-5.6-terra"
    openai_coding_model: str = "gpt-5.6-sol"
    openai_chat_reasoning_effort: str = "low"
    openai_coding_reasoning_effort: str = "medium"
    openai_request_timeout_seconds: float = 120.0
    openai_max_retries: int = 2
    openai_daily_user_token_limit: int = 100000
    openai_daily_project_token_limit: int = 250000
    openai_max_estimated_cost_micro_usd: int = 300000
    elevenlabs_provider_enabled: bool = False
    elevenlabs_base_url: str = "https://api.elevenlabs.io"
    elevenlabs_api_key_file: str = "/run/secrets/elevenlabs-api-key"
    elevenlabs_model_id: str = "eleven_flash_v2_5"
    elevenlabs_canary_voice_id: str = ""
    elevenlabs_browser_output_format: str = "mp3_44100_128"
    elevenlabs_telephony_output_format: str = "ulaw_8000"
    elevenlabs_max_text_characters: int = 1000
    elevenlabs_max_concurrency: int = 1
    elevenlabs_connect_timeout_seconds: float = 10.0
    elevenlabs_read_timeout_seconds: float = 60.0
    elevenlabs_total_timeout_seconds: float = 90.0
    elevenlabs_max_retries: int = 2
    elevenlabs_request_logging_mode: str = "standard"
    controller_approval_signing_key_file: str = ""
    controller_workspace_allowlist: str = (
        "/opt/codestra/middleware,/opt/codestra/worktrees"
    )
    controller_private_enabled: bool = False
    server_a_agent_enabled: bool = False
    server_a_agent_bind: str = "10.40.0.1:9443"
    send_events: bool = False
    broad_event_delivery_enabled: bool = False
    production_n8n_enabled: bool = False
    enable_external_delivery: bool = False
    controlled_broad_event_activation: bool = False
    broad_event_business_unit_allowlist: str = ""
    broad_event_campaign_allowlist: str = ""
    broad_event_workflow_allowlist: str = ""
    broad_event_type_allowlist: str = ""
    broad_event_activation_high_water_mark: str = ""
    broad_event_submission_limit: int = 0
    n8n_production_target_url: str = ""
    n8n_production_target_identity: str = ""
    n8n_production_image_digest: str = ""
    n8n_production_instance_id: str = ""
    n8n_production_version: str = ""
    n8n_runtime_health_url: str = ""
    webphone_origin_scheme: str = "https"
    webphone_origin_host: str = "phone.codestra.agency"
    webphone_expected_user: str = "preprod"
    webphone_staging_campaign: str = "TEST_SYN"
    webphone_staging_endpoint: str = "6101"
    n8n_workflow_package_sha256: str = ""
    n8n_target_ca_file: str = ""
    n8n_service_issuer: str = ""
    n8n_service_audience: str = "codestra-middleware"
    n8n_service_jwks_url: str = ""
    n8n_service_client_id: str = "codestra-n8n-production"
    middleware_n8n_token_url: str = ""
    middleware_n8n_client_id: str = "codestra-middleware-production"
    middleware_n8n_client_secret_file: str = ""
    middleware_n8n_audience: str = "codestra-n8n-production"
    middleware_n8n_scope: str = "n8n.events.submit"
    odoo_results_client_id: str = "codestra-middleware-odoo-results"
    odoo_results_client_secret_file: str = ""
    odoo_results_ca_file: str = ""
    odoo_service_credential_reference: str = ""
    odoo_service_private_key_file: str = ""
    odoo_result_delivery_enabled: bool = False
    test_syn_odoo_result_delivery_enabled: bool = False
    test_syn_odoo_tenant_id: str = "TEST_SYN_TENANT"
    test_syn_odoo_workflow_code: str = "TEST_SYN_ROUTER"
    test_syn_odoo_workflow_version: str = "1"
    test_syn_odoo_event_type: str = "test.synthetic.odoo_result"
    test_syn_odoo_event_id: str = ""
    test_syn_odoo_correlation_id: str = ""
    test_syn_odoo_organization_public_id: str = ""
    test_syn_odoo_business_unit_public_id: str = ""
    test_syn_odoo_campaign_public_id: str = ""
    test_syn_odoo_outbox_public_id: str = ""
    odoo_read_enabled: bool = False
    odoo_sync_worker_enabled: bool = False
    odoo_staging_writes_enabled: bool = False
    odoo_production_writes_enabled: bool = False
    odoo_base_url: str = ""
    odoo_token_url: str = ""
    odoo_client_id: str = "codestra-middleware-staging"
    odoo_client_secret_file: str = ""
    odoo_audience: str = "codestra-odoo-integration"
    odoo_scope: str = ""
    odoo_ca_file: str = ""
    odoo_connect_timeout: float = 5.0
    odoo_read_timeout: float = 15.0
    odoo_max_retries: int = 3
    odoo_sync_worker_id: str = "codestra-middleware-odoo-sync"
    odoo_sync_batch_size: int = 25
    odoo_sync_lease_seconds: int = 60
    odoo_sync_business_units: str = ""
    email_dispatch_enabled: bool = False
    sms_dispatch_enabled: bool = False
    allow_live_email: bool = False
    allow_live_sms: bool = False
    ai_enrichment_enabled: bool = False
    qwen_base_url_file: str = ""
    qwen_api_key_file: str = ""
    litellm_base_url_file: str = ""
    litellm_api_key_file: str = ""
    report_delivery_enabled: bool = False
    outbox_worker_enabled: bool = False
    outbox_max_attempts: int = 5
    outbox_base_delay_seconds: int = 5
    outbox_max_delay_seconds: int = 300
    outbox_lease_seconds: int = 60
    odoo_concurrency: int = 4
    n8n_concurrency: int = 8
    n8n_runtime_enabled: bool = False
    n8n_runtime_environment: str = "staging"
    n8n_runtime_base_url: str = ""
    n8n_runtime_hmac_secret_file: str = ""
    n8n_runtime_dispatch_timeout_seconds: float = 10.0
    n8n_runtime_workflow_timeout_seconds: int = 600
    n8n_runtime_max_attempts: int = 5
    redis_runtime_enabled: bool = False
    redis_runtime_environment: str = "staging"
    redis_runtime_prefix: str = "codestra"
    redis_runtime_socket_timeout_seconds: float = 1.0
    recording_concurrency: int = 2
    retention_worker_enabled: bool = True
    retention_delete_enabled: bool = False
    export_upload_enabled: bool = False
    odoo_recording_write_enabled: bool = False
    odoo_recording_hmac_secret: str = ""
    odoo_recording_hmac_secret_file: str = ""
    n8n_recording_workflow_enabled: bool = False
    n8n_recording_binding_enabled: bool = False
    n8n_recording_workflow_active: bool = False
    recording_upload_url_ttl_seconds: int = 300
    recording_playback_url_ttl_seconds: int = 120
    reconciliation_concurrency: int = 1
    keycloak_issuer: str = ""
    keycloak_audience: str = ""
    keycloak_jwks_url: str = ""
    keycloak_authorized_parties: str = ""
    keycloak_userinfo_url: str = ""
    provisioning_service_url: str = ""
    provisioning_service_token_url: str = ""
    provisioning_service_client_id: str = ""
    provisioning_service_client_secret_file: str = ""
    provisioning_service_ca_file: str = ""
    odoo_identity_lookup_url: str = ""
    odoo_identity_lookup_hmac_file: str = ""
    maintenance_interval_seconds: int = 30
    automation_allowed_campaigns: str = "TEST_SYN"
    automation_environment: str = "test"
    automation_hmac_secret: str = ""
    environment: str = "preproduction"
    publisher_hmac_keys_file: str = ""
    publisher_canary_enabled: bool = False
    breero_ingress_enabled: bool = False
    breero_odoo_delivery_enabled: bool = False
    breero_hmac_identities_file: str = ""
    breero_rate_limit_per_minute: int = 30
    breero_signature_ttl_seconds: int = 300
    breero_request_max_bytes: int = 32768
    breero_odoo_url: str = ""
    breero_odoo_database: str = ""
    breero_odoo_username: str = ""
    breero_odoo_api_key_file: str = ""
    breero_worker_batch_size: int = 8
    breero_worker_lease_seconds: int = 60
    breero_worker_max_attempts: int = 8
    readiness_server_identity: str = "server-a-middleware"
    readiness_approved_source_ip: str = "10.40.0.2"
    readiness_publisher_key_id: str = ""
    readiness_publisher_cert_sha256: str = ""
    readiness_ttl_seconds: int = 60
    readiness_clock_skew_seconds: int = 5
    readiness_request_max_bytes: int = 4096
    readiness_rate_limit_per_minute: int = 10
    deployed_source_sha: str = ""
    runtime_artifact_checksum: str = ""
    quarantine_encryption_key_file: str = ""
    quarantine_encryption_key_version: str = "v1"
    quarantine_fingerprint_secret_file: str = ""
    quarantine_reviewer_secret_file: str = ""
    quarantine_retention_days: int = 90
    quarantine_retention_policy_version: str = "2026-07-26.1"
    quarantine_store_authenticated_raw: bool = True
    quarantine_rate_limit_per_minute: int = 30
    webphone_staging_provisioning_enabled: bool = False
    webphone_keycloak_enabled: bool = False
    webphone_endpoint_adapter_url: str = ""
    extension_allocator_enabled: bool = False
    telephony_provisioning_enabled: bool = False
    telephony_command_worker_enabled: bool = False
    telephony_service_client_id: str = "codestra-middleware-telephony"
    telephony_credential_directory: str = ""
    vicidial_provisioning_enabled: bool = False
    postiz_internal_base_url: str = ""
    postiz_api_key_file: str = ""
    postiz_organization_reference: str = ""
    postiz_timeout_seconds: float = 10.0
    postiz_delivery_enabled: bool = False
    postiz_publish_enabled: bool = False
    postiz_media_upload_enabled: bool = False
    postiz_analytics_enabled: bool = False
    social_integration_enabled: bool = False
    social_publish_enabled: bool = False
    social_provider: str = "disabled"
    social_provider_mode: str = "single"
    social_provider_migration_mode: str = "disabled"
    social_n8n_events_enabled: bool = False
    social_n8n_delivery_worker_enabled: bool = False
    social_n8n_delivery_worker_id: str = "social-n8n-delivery-01"
    social_n8n_delivery_batch_size: int = 8
    social_n8n_delivery_lease_seconds: int = 60
    postly_polling_enabled: bool = False
    postly_poll_interval_seconds: int = 60
    postly_poll_lookback_seconds: int = 300
    postly_poll_batch_size: int = 100
    social_odoo_sync_enabled: bool = False
    social_odoo_write_enabled: bool = False
    social_analytics_sync_enabled: bool = False
    social_sql_repository_enabled: bool = False
    social_worker_enabled: bool = False
    social_worker_id: str = "postly-social-01"
    social_worker_concurrency: int = 1
    social_worker_lease_seconds: int = 60
    social_worker_poll_seconds: float = 1.0
    social_job_max_attempts: int = 5
    social_production_mode: bool = False
    social_production_canary_enabled: bool = False
    social_production_canary_account_ids: str = ""
    social_production_canary_tenant_ids: str = ""
    social_production_canary_campaign_ids: str = ""
    social_production_backup_gate_verified: bool = False
    social_production_rollback_gate_verified: bool = False
    social_production_webhook_gate_verified: bool = False
    social_production_monitoring_gate_verified: bool = False
    social_automatic_provider_failover_enabled: bool = False
    social_automatic_dual_publish_enabled: bool = False
    social_webhook_ttl_seconds: int = 300
    postly_webhook_secret: str = ""
    postly_webhook_secret_file: str = ""
    hootsuite_enabled: bool = False
    hootsuite_client_id_file: str = ""
    hootsuite_client_secret_file: str = ""
    hootsuite_redirect_uri: str = ""
    pjsip_provisioning_enabled: bool = False
    webphone_session_issuer_enabled: bool = False
    agent_websocket_enabled: bool = False
    telephony_reconciliation_enabled: bool = False
    telephony_notifications_enabled: bool = False
    telephony_evidence_enabled: bool = False
    lead_automation_enabled: bool = False
    lead_create_enabled: bool = False
    lead_update_enabled: bool = False
    lead_assignment_enabled: bool = False
    lead_status_change_enabled: bool = False
    lead_callback_create_enabled: bool = False
    n8n_lead_binding_enabled: bool = False
    n8n_result_processing_enabled: bool = False
    odoo_lead_apply_enabled: bool = False
    lead_automation_hmac_secret: str = ""
    sales_lead_intake_enabled: bool = False
    sales_identity_resolution_enabled: bool = False
    sales_odoo_read_only_lookup_enabled: bool = False
    sales_verification_jobs_enabled: bool = False
    scraper_result_ingest_enabled: bool = False
    scraper_middleware_delivery_enabled: bool = False
    scraper_odoo_apply_url: str = ""
    scraper_odoo_company_key: str = "COMPANY-1"
    scraper_odoo_business_unit_key: str = "web-mobile-ai"
    lead_verification_dry_run_only: bool = True
    lead_outreach_enabled: bool = False
    odoo_lead_write_enabled: bool = False
    vicidial_lead_write_enabled: bool = False
    n8n_lead_delivery_enabled: bool = False
    postly_lead_delivery_enabled: bool = False
    hunter_provider_enabled: bool = False
    apollo_provider_enabled: bool = False
    twilio_lookup_provider_enabled: bool = False
    opencorporates_provider_enabled: bool = False
    openai_lead_classification_enabled: bool = False
    vicidial_publication_enabled: bool = False
    outreach_enabled: bool = False
    sales_lead_request_max_bytes: int = 131072
    sales_verification_max_concurrency: int = 4
    sales_scraper_identity: str = ""
    sales_scraper_tenant_id: str = ""
    sales_scraper_campaign_allowlist: str = ""
    sales_scraper_hmac_key_ids: str = ""
    sales_scraper_hmac_keys_directory: str = ""
    sales_scraper_jwt_issuer: str = ""
    sales_scraper_jwt_audience: str = "codestra-scraper-ingress"
    sales_scraper_jwt_jwks_url: str = ""
    sales_scraper_jwt_authorized_parties: str = ""
    sales_scraper_jwt_required_scope: str = "scraper.events.write"
    sales_scraper_jwt_required_role: str = "scraper-publisher"
    sales_scraper_rate_limit_per_minute: int = 60

    def validate_safety(self) -> None:
        if self.social_n8n_delivery_batch_size not in range(1, 26):
            raise ValueError("social n8n delivery batch size must be between 1 and 25")
        if self.social_n8n_delivery_lease_seconds not in range(10, 601):
            raise ValueError("social n8n delivery lease must be between 10 and 600 seconds")
        if self.postly_poll_interval_seconds not in range(30, 3601):
            raise ValueError("Postly polling interval must be between 30 and 3600 seconds")
        if self.postly_poll_lookback_seconds not in range(60, 86401):
            raise ValueError("Postly polling lookback must be between 60 seconds and one day")
        if self.postly_poll_batch_size not in range(1, 501):
            raise ValueError("Postly polling batch size must be between 1 and 500")
        if self.social_worker_concurrency != 1:
            raise ValueError(
                "social worker concurrency must remain 1 in controlled staging"
            )
        broad_event_switches = (
            self.send_events,
            self.broad_event_delivery_enabled,
            self.production_n8n_enabled,
            self.n8n_production_workflows_enabled,
        )
        production_switches = (
            self.live_writes_enabled,
            self.odoo_write_enabled,
            self.allow_non_test_campaigns,
            self.vicidial_write_enabled,
            self.messaging_enabled,
            self.external_dial_enabled,
            self.enable_external_delivery,
            self.email_dispatch_enabled,
            self.sms_dispatch_enabled,
            self.allow_live_email,
            self.allow_live_sms,
            self.outbox_worker_enabled,
            self.odoo_recording_write_enabled,
            self.n8n_recording_workflow_enabled,
            self.n8n_recording_binding_enabled,
            self.n8n_recording_workflow_active,
            self.telephony_provisioning_enabled,
            self.telephony_command_worker_enabled,
            self.vicidial_provisioning_enabled,
            self.pjsip_provisioning_enabled,
            self.vicidial_publication_enabled,
            self.outreach_enabled,
            not self.lead_verification_dry_run_only,
            self.lead_outreach_enabled,
            self.odoo_lead_write_enabled,
            self.vicidial_lead_write_enabled,
            self.n8n_lead_delivery_enabled,
            self.postly_lead_delivery_enabled,
            self.odoo_production_writes_enabled,
            self.social_odoo_write_enabled,
        )
        if any(production_switches):
            raise ValueError("live writes and non-TEST_SYN campaigns are disabled")
        if self.scraper_middleware_delivery_enabled:
            campaigns = {
                value.strip()
                for value in self.sales_scraper_campaign_allowlist.split(",")
                if value.strip()
            }
            if (
                self.environment not in {"test", "staging"}
                or campaigns != {"TEST_SYN"}
                or not self.scraper_odoo_apply_url.startswith(("http://", "https://"))
                or not self.lead_automation_hmac_secret
            ):
                raise ValueError("scraper delivery requires isolated TEST_SYN staging")
        if self.scraper_result_ingest_enabled:
            key_ids = {
                value.strip()
                for value in self.sales_scraper_hmac_key_ids.split(",")
                if value.strip()
            }
            authorized_parties = {
                value.strip()
                for value in self.sales_scraper_jwt_authorized_parties.split(",")
                if value.strip()
            }
            if (
                not self.sales_scraper_identity
                or not self.sales_scraper_tenant_id
                or not self.sales_scraper_campaign_allowlist
                or not self.sales_scraper_hmac_keys_directory
                or not 1 <= len(key_ids) <= 3
                or not self.sales_scraper_jwt_issuer
                or not self.sales_scraper_jwt_audience
                or not self.sales_scraper_jwt_jwks_url
                or self.sales_scraper_identity not in authorized_parties
                or not self.sales_scraper_jwt_required_scope
                or not self.sales_scraper_jwt_required_role
                or self.sales_scraper_rate_limit_per_minute not in range(1, 601)
            ):
                raise ValueError("scraper ingress authentication is incomplete")
            if set(self.sales_scraper_hmac_keys) != key_ids:
                raise ValueError("scraper HMAC key enrollment is inconsistent")
        social_publish_switches = (
            self.social_publish_enabled,
            self.postiz_publish_enabled,
        )
        if any(social_publish_switches):
            if not all(social_publish_switches):
                raise ValueError("social and provider publish switches must agree")
            if not all(
                (
                    self.social_production_mode,
                    self.social_integration_enabled,
                    self.social_production_canary_enabled,
                    self.social_production_backup_gate_verified,
                    self.social_production_rollback_gate_verified,
                    self.social_production_webhook_gate_verified,
                    self.social_production_monitoring_gate_verified,
                    self.social_sql_repository_enabled,
                    self.social_worker_enabled,
                    self.postiz_delivery_enabled,
                    self.social_production_canary_account_ids.strip(),
                )
            ):
                raise ValueError(
                    "production social publishing requires every canary gate"
                )
            if not all(
                (
                    self.postiz_internal_base_url.strip(),
                    self.postiz_api_key_file.strip(),
                    self.postly_webhook_secret_file.strip(),
                )
            ):
                raise ValueError("production Postly secrets and endpoint are required")
            self.postiz_api_key
            self.postly_webhook_verification_secret
        if (
            self.social_automatic_provider_failover_enabled
            or self.social_automatic_dual_publish_enabled
        ):
            raise ValueError(
                "automatic provider failover and dual publishing are forbidden"
            )
        if any(broad_event_switches):
            if not all(broad_event_switches):
                raise ValueError("broad-event activation requires every canonical gate")
            required_scope = (
                self.broad_event_business_unit_allowlist,
                self.broad_event_campaign_allowlist,
                self.broad_event_workflow_allowlist,
                self.broad_event_type_allowlist,
                self.broad_event_activation_high_water_mark,
            )
            if (
                not self.controlled_broad_event_activation
                or not all(value.strip() for value in required_scope)
                or self.broad_event_submission_limit not in range(1, 26)
            ):
                raise ValueError(
                    "broad-event activation requires bounded explicit scope"
                )

    @property
    def broad_event_pipeline_enabled(self) -> bool:
        """Require every internal broad-event gate; external delivery is separate."""
        return all(
            (
                self.send_events,
                self.broad_event_delivery_enabled,
                self.production_n8n_enabled,
                self.n8n_production_workflows_enabled,
            )
        )

    def load_secret_files(self) -> None:
        """Load runtime secrets without placing their values in environment metadata."""
        mappings = (
            ("database_url", self.database_url_file),
            ("redis_url", self.redis_url_file),
            ("middleware_secret", self.middleware_secret_file),
            # Ingestion deliberately has no legacy shared-secret fallback.
            ("ingestion_hmac_secret", self.vicidial_callback_hmac_secret_file),
            ("odoo_recording_hmac_secret", self.odoo_recording_hmac_secret_file),
        )
        for attribute, filename in mappings:
            if filename:
                path = Path(filename)
                if not path.is_absolute() or not path.is_file():
                    raise ValueError(f"required {attribute} secret file is unavailable")
                value = path.read_text().strip()
                if not value:
                    raise ValueError(f"required {attribute} secret file is empty")
                setattr(self, attribute, value)

    @property
    def sales_scraper_hmac_keys(self) -> dict[str, bytes]:
        directory = Path(self.sales_scraper_hmac_keys_directory)
        if (
            not directory.is_absolute()
            or directory.is_symlink()
            or not directory.is_dir()
            or directory.stat().st_mode & 0o077
            or directory.stat().st_uid != os.geteuid()
        ):
            raise ValueError("sales scraper HMAC key directory is unavailable or unsafe")
        key_ids = [
            value.strip()
            for value in self.sales_scraper_hmac_key_ids.split(",")
            if value.strip()
        ]
        if not 1 <= len(key_ids) <= 3 or len(key_ids) != len(set(key_ids)):
            raise ValueError("sales scraper HMAC trusted-key set is invalid")
        keys: dict[str, bytes] = {}
        for key_id in key_ids:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", key_id):
                raise ValueError("sales scraper HMAC key ID is invalid")
            path = self._protected_secret_path(
                str(directory / f"{key_id}.key"), "sales scraper HMAC"
            )
            if path.stat().st_uid != os.geteuid():
                raise ValueError("sales scraper HMAC secret has an unsafe owner")
            value = path.read_bytes().strip()
            if len(value) < 32:
                raise ValueError("sales scraper HMAC secret is too short")
            keys[key_id] = value
        return keys

    @staticmethod
    def _optional_secret(filename: str, label: str) -> str:
        if not filename:
            return ""
        path = Path(filename)
        if not path.is_absolute() or not path.is_file():
            raise ValueError(f"{label} secret file is unavailable")
        value = path.read_text().strip()
        if not value:
            raise ValueError(f"{label} secret file is empty")
        return value

    @property
    def qwen_base_url(self) -> str:
        return self._optional_secret(self.qwen_base_url_file, "Qwen base URL")

    @property
    def qwen_api_key(self) -> str:
        return self._optional_secret(self.qwen_api_key_file, "Qwen API key")

    @property
    def litellm_base_url(self) -> str:
        return self._optional_secret(self.litellm_base_url_file, "LiteLLM base URL")

    @property
    def litellm_api_key(self) -> str:
        return self._optional_secret(self.litellm_api_key_file, "LiteLLM API key")

    @property
    def openai_api_key(self) -> str:
        return self._protected_secret(self.openai_api_key_file, "OpenAI API key")

    @property
    def openai_safety_salt(self) -> bytes:
        path = self._protected_secret_path(
            self.openai_safety_salt_file, "OpenAI safety identifier salt"
        )
        value = path.read_bytes()
        if len(value) < 32:
            raise ValueError("OpenAI safety identifier salt is too short")
        return value

    @property
    def elevenlabs_api_key(self) -> str:
        """Load an ASCII API key without ever including it in an error."""
        if self.elevenlabs_api_key_file != "/run/secrets/elevenlabs-api-key":
            raise ValueError("ElevenLabs API key path is not approved")
        return self._protected_text_secret(
            self.elevenlabs_api_key_file, "ElevenLabs API key"
        )

    @classmethod
    def _protected_text_secret(cls, filename: str, label: str) -> str:
        path = cls._protected_secret_path(filename, label)
        metadata = path.stat()
        if (
            metadata.st_uid != os.geteuid()
            or metadata.st_gid != os.getegid()
            or metadata.st_mode & 0o777 != 0o400
        ):
            raise ValueError(f"{label} secret file metadata is unsafe")
        value = path.read_bytes()
        if value.endswith(b"\r\n"):
            value = value[:-2]
        elif value.endswith((b"\r", b"\n")):
            value = value[:-1]
        if not value or b"\x00" in value or any(byte in b" \t\r\n" for byte in value):
            raise ValueError("ElevenLabs API key is malformed")
        try:
            return value.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("ElevenLabs API key is malformed") from exc

    @staticmethod
    def _protected_secret_path(filename: str, label: str) -> Path:
        path = Path(filename)
        if (
            not filename
            or not path.is_absolute()
            or path.is_symlink()
            or not path.is_file()
            or path.stat().st_mode & 0o077
        ):
            raise ValueError(f"{label} secret file is unavailable or unsafe")
        return path

    @classmethod
    def _protected_secret(cls, filename: str, label: str) -> str:
        path = cls._protected_secret_path(filename, label)
        value = path.read_text().strip()
        if not value:
            raise ValueError(f"{label} secret file is empty")
        return value

    @property
    def postiz_api_key(self) -> str:
        if not self.postiz_api_key_file:
            return ""
        return self._protected_secret(self.postiz_api_key_file, "Postiz API key")

    @property
    def postly_webhook_verification_secret(self) -> str:
        if self.postly_webhook_secret_file:
            return self._protected_secret(
                self.postly_webhook_secret_file, "Postly webhook"
            )
        if self.social_production_mode:
            return ""
        return self.postly_webhook_secret

    def load_registry_snapshot_key(self) -> bytes:
        path = Path(self.registry_snapshot_signing_key_file)
        if not path.is_absolute() or not path.is_file():
            raise ValueError("registry snapshot signing key file is unavailable")
        value = path.read_bytes().strip()
        if len(value) < 32:
            raise ValueError("registry snapshot signing key is too short")
        return value

    @field_validator("openai_worker_max_concurrency")
    @classmethod
    def validate_openai_worker_max_concurrency(cls, value: int) -> int:
        if value != 1:
            raise ValueError("OpenAI worker concurrency must equal one")
        return value

    @field_validator("elevenlabs_base_url")
    @classmethod
    def validate_elevenlabs_base_url(cls, value: str) -> str:
        if value != "https://api.elevenlabs.io":
            raise ValueError("ElevenLabs base URL must be the approved HTTPS host")
        return value

    @field_validator("elevenlabs_model_id")
    @classmethod
    def validate_elevenlabs_model_id(cls, value: str) -> str:
        if value != "eleven_flash_v2_5":
            raise ValueError("ElevenLabs model is not approved")
        return value

    @field_validator("elevenlabs_canary_voice_id")
    @classmethod
    def validate_elevenlabs_canary_voice_id(cls, value: str) -> str:
        if value and not re.fullmatch(r"[A-Za-z0-9]{1,64}", value):
            raise ValueError("ElevenLabs voice identifier is invalid")
        return value

    @field_validator("elevenlabs_browser_output_format")
    @classmethod
    def validate_elevenlabs_browser_output_format(cls, value: str) -> str:
        if value != "mp3_44100_128":
            raise ValueError("ElevenLabs browser output format is not approved")
        return value

    @field_validator("elevenlabs_telephony_output_format")
    @classmethod
    def validate_elevenlabs_telephony_output_format(cls, value: str) -> str:
        if value != "ulaw_8000":
            raise ValueError("ElevenLabs telephony output format is not approved")
        return value

    @field_validator("elevenlabs_max_concurrency")
    @classmethod
    def validate_elevenlabs_max_concurrency(cls, value: int) -> int:
        if value != 1:
            raise ValueError("ElevenLabs concurrency must equal one")
        return value

    @field_validator("elevenlabs_max_text_characters")
    @classmethod
    def validate_elevenlabs_max_text_characters(cls, value: int) -> int:
        if value != 1000:
            raise ValueError("ElevenLabs text limit must equal 1000")
        return value

    @field_validator(
        "elevenlabs_connect_timeout_seconds",
        "elevenlabs_read_timeout_seconds",
        "elevenlabs_total_timeout_seconds",
    )
    @classmethod
    def validate_elevenlabs_timeout(cls, value: float) -> float:
        if value <= 0 or value > 120:
            raise ValueError("ElevenLabs timeout is invalid")
        return value

    @field_validator("elevenlabs_max_retries")
    @classmethod
    def validate_elevenlabs_max_retries(cls, value: int) -> int:
        if value not in range(0, 3):
            raise ValueError("ElevenLabs retry count is invalid")
        return value

    @field_validator("elevenlabs_request_logging_mode")
    @classmethod
    def validate_elevenlabs_logging_mode(cls, value: str) -> str:
        if value not in {"standard", "zero_retention"}:
            raise ValueError("ElevenLabs request logging mode is invalid")
        return value

    @field_validator("vicidial_authorization_url", "vicidial_edge_url")
    @classmethod
    def validate_vicidial_private_url(cls, value: str) -> str:
        if not value:
            return value
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in VICIDIAL_PRIVATE_HOSTS
            or parsed.port != VICIDIAL_PRIVATE_PORT
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("VICIdial URL must use an approved private HTTPS endpoint")
        return value.rstrip("/")

    @field_validator("n8n_production_target_url")
    @classmethod
    def validate_n8n_production_target_url(cls, value: str) -> str:
        if not value:
            return value
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "n8n.internal.codestra.agency"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path != "/webhook/codestra/v1/events"
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("n8n target must be the approved internal webhook")
        return value

    @field_validator("n8n_workflow_package_sha256")
    @classmethod
    def validate_workflow_package_sha256(cls, value: str) -> str:
        if value and not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("workflow package identity must be an exact SHA-256")
        return value

    @field_validator("n8n_production_image_digest")
    @classmethod
    def validate_n8n_production_image_digest(cls, value: str) -> str:
        if value and not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
            raise ValueError("n8n image identity must be an exact sha256 digest")
        return value

    @field_validator("webphone_endpoint_adapter_url")
    @classmethod
    def validate_webphone_endpoint_adapter_url(cls, value: str) -> str:
        if not value:
            return value
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "authorization.internal.codestra.agency"
            or parsed.port != VICIDIAL_ENDPOINT_ADAPTER_PORT
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("webphone endpoint adapter must use private HTTPS")
        return value.rstrip("/")

    @field_validator(
        "vicidial_ca_file",
        "vicidial_client_cert_file",
        "vicidial_client_key_file",
        "vicidial_crl_file",
    )
    @classmethod
    def validate_vicidial_secret_path(cls, value: str) -> str:
        if not value:
            return value
        path = Path(value)
        if not path.is_absolute() or path.parent != VICIDIAL_SECRET_ROOT:
            raise ValueError(
                "VICIdial mTLS files must be direct children of the secret mount"
            )
        return value

    @property
    def vicidial_mtls_configured(self) -> bool:
        return all(
            (
                self.vicidial_authorization_url,
                self.vicidial_edge_url,
                self.vicidial_ca_file,
                self.vicidial_client_cert_file,
                self.vicidial_client_key_file,
            )
        )

    @property
    def allowed_campaigns(self) -> frozenset[str]:
        return frozenset(
            value.strip()
            for value in self.automation_allowed_campaigns.split(",")
            if value.strip()
        )

    @property
    def auth_ready(self) -> bool:
        return bool(self.middleware_secret and self.ingestion_hmac_secret)

    @property
    def webphone_identity_ready(self) -> bool:
        return all(
            (
                self.webphone_staging_provisioning_enabled,
                self.keycloak_issuer,
                self.keycloak_audience,
                self.keycloak_jwks_url,
                self.keycloak_authorized_parties,
                self.keycloak_userinfo_url,
                self.provisioning_service_url,
                self.provisioning_service_token_url,
                self.provisioning_service_client_id,
                self.provisioning_service_client_secret_file,
                self.provisioning_service_ca_file,
            )
        )

    @property
    def publisher_hmac_keys(self) -> dict[str, bytes]:
        if not self.publisher_hmac_keys_file:
            return {}
        path = Path(self.publisher_hmac_keys_file)
        if not path.is_absolute() or not path.is_file():
            raise ValueError("publisher key file unavailable")
        values = json.loads(path.read_text())
        if not isinstance(values, dict) or not values:
            raise ValueError("publisher key file invalid")
        return {
            key_id: base64.urlsafe_b64decode(value + "===")
            for key_id, value in values.items()
        }

    @staticmethod
    def _load_binary_secret(filename: str, label: str) -> bytes:
        path = Path(filename)
        if not filename or not path.is_absolute() or not path.is_file():
            raise ValueError(f"{label} file unavailable")
        try:
            value = base64.urlsafe_b64decode(path.read_text().strip() + "===")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{label} file invalid") from exc
        if len(value) < 32:
            raise ValueError(f"{label} must contain at least 256 bits")
        return value

    @property
    def quarantine_encryption_key(self) -> bytes:
        value = self._load_binary_secret(
            self.quarantine_encryption_key_file, "quarantine encryption key"
        )
        if len(value) != 32:
            raise ValueError("quarantine encryption key must be 256 bits")
        return value

    @property
    def quarantine_fingerprint_secret(self) -> bytes:
        return self._load_binary_secret(
            self.quarantine_fingerprint_secret_file,
            "quarantine fingerprint secret",
        )

    @property
    def quarantine_reviewer_secret(self) -> bytes:
        return self._load_binary_secret(
            self.quarantine_reviewer_secret_file,
            "quarantine reviewer authorization secret",
        )

    @property
    def enabled_events(self) -> frozenset[str]:
        return frozenset(
            x.strip() for x in self.enabled_event_types.split(",") if x.strip()
        )

    @property
    def ingestion_clients(self) -> frozenset[str]:
        return frozenset(
            x.strip() for x in self.allowed_client_instances.split(",") if x.strip()
        )


settings = Settings()
settings.load_secret_files()
if settings.database_url.startswith("postgresql://"):
    settings.database_url = settings.database_url.replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )
settings.validate_safety()
