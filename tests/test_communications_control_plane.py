import os
import tempfile
import unittest

from control_plane_service.core import ControlPlaneError, Store, normalize_destination, sms_segments, validate_envelope
from control_plane_service.providers import ProviderError, submit, submit_crawler
from control_plane_service.worker import dispatch_messages
from control_plane_service.routing import select_channel


def request(channel="sms", tenant="tenant-a", key="key-1", **extra):
    value={"channel":channel,"tenant_id":tenant,"customer_id":"customer-1","request_id":"request-1","correlation_id":"correlation-1","idempotency_key":key,"sender":"CODESTRA" if channel=="sms" else "sender@example.test","recipient":"+18095550101" if channel=="sms" else "person@example.test","source_application":"n8n","classification":"marketing","content_metadata":{"template_id":"welcome","body":"must-not-persist"},"content":"hello","currency":"USD"}
    value.update(extra); return value


class CommunicationsTests(unittest.TestCase):
    def setUp(self):
        handle,self.path=tempfile.mkstemp(); os.close(handle); self.store=Store(self.path)
        self.store.set_preference("tenant-a","customer-1","sms","subscribed","test")
        self.store.set_preference("tenant-a","customer-1","email","subscribed","test")
    def tearDown(self):
        for suffix in ("","-wal","-shm"):
            try: os.unlink(self.path+suffix)
            except FileNotFoundError: pass

    def test_sms_and_email_ledger_redacts_content(self):
        sms,_=self.store.create_message(request()); email,_=self.store.create_message(request("email",key="email-1"))
        self.assertEqual(sms["provider"],"telnexa"); self.assertEqual(email["provider"],"klyrow")
        self.assertNotIn("body",sms["content_metadata"]); self.assertEqual(len(self.store.message_events(sms["message_id"],"tenant-a")),1)

    def test_idempotency_and_conflict(self):
        first,_=self.store.create_message(request()); second,duplicate=self.store.create_message(request())
        self.assertTrue(duplicate); self.assertEqual(first["message_id"],second["message_id"])
        with self.assertRaisesRegex(ControlPlaneError,"idempotency_conflict"): self.store.create_message(request(recipient="+18095550102"))

    def test_marketing_consent_and_cross_tenant_isolation(self):
        with self.assertRaisesRegex(ControlPlaneError,"consent_required"): self.store.create_message(request(tenant="tenant-b"))
        message,_=self.store.create_message(request())
        with self.assertRaisesRegex(ControlPlaneError,"message_not_found"): self.store.get_message(message["message_id"],"tenant-b")

    def test_transactional_exception_explicit(self):
        message,_=self.store.create_message(request(tenant="tenant-b",classification="transactional"))
        self.assertEqual(message["classification"],"transactional")

    def test_email_suppression(self):
        self.store.suppress("tenant-a","email","person@example.test","complaint","provider complaint","klyrow")
        with self.assertRaisesRegex(ControlPlaneError,"destination_suppressed"): self.store.create_message(request("email"))

    def test_provider_event_dedup_and_suppression(self):
        message,_=self.store.create_message(request("email")); env=validate_envelope({"event_type":"klyrow.email.complained","event_version":"1.0","occurred_at":"2026-08-15T00:00:00Z","tenant_id":"tenant-a","customer_id":"customer-1","idempotency_key":"event-1","payload":{"message_id":message["message_id"],"status":"complained"}},"klyrow","event-1")
        self.assertTrue(self.store.apply_provider_event("klyrow",env)); self.assertFalse(self.store.apply_provider_event("klyrow",env))
        self.assertFalse(self.store.preference_allows("tenant-a","customer-1","email"))

    def test_sms_stop_optout(self):
        message,_=self.store.create_message(request()); env=validate_envelope({"event_type":"telnexa.sms.received","event_version":"1.0","occurred_at":"2026-08-15T00:00:00Z","tenant_id":"tenant-a","customer_id":"customer-1","idempotency_key":"stop-1","payload":{"message_id":message["message_id"],"status":"received","text":"STOP"}},"telnexa","stop-1")
        self.store.apply_provider_event("telnexa",env); self.assertFalse(self.store.preference_allows("tenant-a","customer-1","sms"))

    def test_new_inbound_sms_creates_one_ledger_record(self):
        env=validate_envelope({"event_type":"telnexa.sms.received","event_version":"1.0","occurred_at":"2026-08-15T00:00:00Z","tenant_id":"tenant-a","customer_id":"customer-1","idempotency_key":"inbound-new","payload":{"from":"+18095550123","to":"+18095550100","text":"HELP"}},"telnexa","inbound-new")
        first,duplicate=self.store.create_inbound_sms(env); second,replayed=self.store.create_inbound_sms(env)
        self.assertFalse(duplicate); self.assertTrue(replayed); self.assertEqual(first["message_id"],second["message_id"]); self.assertEqual(first["direction"],"inbound")

    def test_cancel_retry_and_timeline(self):
        message,_=self.store.create_message(request()); self.store.cancel_message(message["message_id"],"tenant-a")
        with self.assertRaisesRegex(ControlPlaneError,"not_retryable"): self.store.retry_message(message["message_id"],"tenant-a")
        failed,_=self.store.create_message(request(key="failed")); self.store.transition_message(failed["message_id"],"tenant-a","failed","simulated")
        self.assertEqual(self.store.retry_message(failed["message_id"],"tenant-a")["status"],"queued")

    def test_normalization_segments_and_usage_integer_money(self):
        self.assertEqual(normalize_destination("email","USER@Example.Test"),"user@example.test")
        self.assertEqual(sms_segments("x"*161),2)
        with self.assertRaisesRegex(ControlPlaneError,"invalid_e164"): normalize_destination("sms","8095550101")
        self.store.create_message(request(estimated_cost_minor=7,content="x"*161))
        with self.store.connect() as db: row=db.execute("SELECT units,estimated_cost_minor FROM usage_meter").fetchone()
        self.assertEqual(tuple(row),(2,7))

    def test_simulator_and_safe_mode_never_need_real_credentials(self):
        old_t=os.environ.get("TELNEXA_MODE"); old_k=os.environ.get("KLYROW_MODE")
        try:
            os.environ["TELNEXA_MODE"]="simulator"; os.environ["KLYROW_MODE"]="test"
            sms,_=self.store.create_message(request()); email,_=self.store.create_message(request("email",key="email"))
            self.assertTrue(submit(sms).provider_message_id.startswith("sim-")); self.assertTrue(submit(email).provider_message_id.startswith("test-"))
            os.environ["TELNEXA_MODE"]="production"
            with self.assertRaisesRegex(ProviderError,"not_authorized"): submit(sms)
        finally:
            if old_t is None: os.environ.pop("TELNEXA_MODE",None)
            else: os.environ["TELNEXA_MODE"]=old_t
            if old_k is None: os.environ.pop("KLYROW_MODE",None)
            else: os.environ["KLYROW_MODE"]=old_k

    def test_worker_dispatches_only_when_enabled(self):
        message,_=self.store.create_message(request()); old_db=os.environ.get("CONTROL_PLANE_DB"); old_enabled=os.environ.get("CONTROL_PLANE_OUTBOUND_ENABLED")
        try:
            os.environ["CONTROL_PLANE_DB"]=self.path; os.environ["CONTROL_PLANE_OUTBOUND_ENABLED"]="false"; self.assertEqual(dispatch_messages(),0)
            os.environ["CONTROL_PLANE_OUTBOUND_ENABLED"]="true"; os.environ["TELNEXA_MODE"]="simulator"; self.assertEqual(dispatch_messages(),1)
            self.assertEqual(self.store.get_message(message["message_id"],"tenant-a")["status"],"accepted")
        finally:
            if old_db is None: os.environ.pop("CONTROL_PLANE_DB",None)
            else: os.environ["CONTROL_PLANE_DB"]=old_db
            if old_enabled is None: os.environ.pop("CONTROL_PLANE_OUTBOUND_ENABLED",None)
            else: os.environ["CONTROL_PLANE_OUTBOUND_ENABLED"]=old_enabled

    def test_explicit_routing_policy_and_circuit_breaker(self):
        self.assertEqual(select_channel(self.store,"tenant-a","customer-1",{"preferred_channel":"email","classification":"marketing"}),"email")
        self.store.set_preference("tenant-a","customer-1","email","unsubscribed","test")
        self.assertEqual(select_channel(self.store,"tenant-a","customer-1",{"preferred_channel":"email","fallback_channel":"sms","fallback_enabled":True,"classification":"marketing"}),"sms")
        with self.assertRaisesRegex(ControlPlaneError,"no_permitted_channel"): select_channel(self.store,"tenant-a","customer-1",{"preferred_channel":"email","classification":"marketing"})
        self.store.circuit_result("telnexa",False,2); self.assertTrue(self.store.circuit_allows("telnexa")); self.store.circuit_result("telnexa",False,2); self.assertFalse(self.store.circuit_allows("telnexa"))

    def test_contact_identity_is_tenant_scoped(self):
        self.store.upsert_contact("tenant-a","customer-1","odoo-42",["+18095550101"],["person@example.test"],{"telnexa":"sms-1","klyrow":"email-1"})
        with self.store.connect() as db: row=db.execute("SELECT odoo_partner_id FROM contacts WHERE tenant_id=? AND customer_id=?",("tenant-a","customer-1")).fetchone()
        self.assertEqual(row["odoo_partner_id"],"odoo-42")

    def test_safe_crawler_job_idempotency_and_target_policy(self):
        value={"tenant_id":"tenant-a","correlation_id":"crawl-correlation","idempotency_key":"crawl-1","target_url":"https://example.test/audit"}
        first,duplicate=self.store.create_crawler_job(value); second,replayed=self.store.create_crawler_job(value)
        self.assertFalse(duplicate); self.assertTrue(replayed); self.assertEqual(first["job_id"],second["job_id"])
        result=submit_crawler(first); accepted=self.store.accept_crawler_job(first["job_id"],"tenant-a",result.provider_message_id)
        self.assertEqual(accepted["status"],"accepted"); self.assertTrue(accepted["provider_job_id"].startswith("test-job-"))
        with self.assertRaisesRegex(ControlPlaneError,"unsafe_crawler_target"):
            self.store.create_crawler_job(dict(value,idempotency_key="crawl-2",target_url="https://www.google.com/"))

    def test_operations_summary_and_metrics_cover_both_channels(self):
        self.store.create_message(request()); self.store.create_message(request("email",key="email-metric"))
        summary=self.store.summary("tenant-a"); self.assertEqual(summary["channel_throughput"],{"email":1,"sms":1})
        metrics=self.store.metrics(); self.assertIn('codestra_communications_messages_total{channel="sms",status="queued"} 1',metrics); self.assertIn('codestra_communications_usage_units{channel="email"} 1',metrics)


if __name__=="__main__": unittest.main()
