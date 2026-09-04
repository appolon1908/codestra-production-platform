-- Klyrow issue #31: exact OIDC service-account-to-tenant authorization.
--
-- Before this migration is executed, the protected operator session MUST set
-- `codestra.cod_web_out_subject` to the exact canonical Keycloak service-account
-- `sub` for client `cod-web-out-email-production`. No subject or credential is
-- stored in Git. The migration is deliberately fail-closed on ambiguity.

BEGIN;

LOCK TABLE oidc_tenant_registry IN SHARE ROW EXCLUSIVE MODE;

DO $cod_web_out$
DECLARE
    canonical_issuer CONSTANT text := 'https://auth.codestra.co/realms/codestra';
    canonical_client_id CONSTANT text := 'cod-web-out-email-production';
    canonical_tenant_key CONSTANT text := 'COD';
    canonical_scopes CONSTANT text[] := ARRAY[
        'email.status',
        'klyrow.read',
        'klyrow.send'
    ]::text[];
    service_subject text := nullif(
        btrim(current_setting('codestra.cod_web_out_subject', true)),
        ''
    );
    conflicting_rows integer;
    updated_rows integer;
    exact_rows integer;
BEGIN
    IF service_subject IS NULL THEN
        RAISE EXCEPTION 'cod_web_out_subject_required';
    END IF;

    -- Keycloak service-account subjects are canonical UUIDs in this realm.
    -- Reject control characters, aliases, usernames and mailbox-derived keys.
    IF length(service_subject) > 36
       OR service_subject !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    THEN
        RAISE EXCEPTION 'cod_web_out_subject_invalid';
    END IF;

    SELECT count(*)
      INTO conflicting_rows
      FROM oidc_tenant_registry
     WHERE (
               client_id = canonical_client_id
           AND (
                   issuer IS DISTINCT FROM canonical_issuer
                OR subject IS DISTINCT FROM service_subject
                OR tenant_key IS DISTINCT FROM canonical_tenant_key
           )
       )
        OR (
               issuer = canonical_issuer
           AND subject = service_subject
           AND (
                   client_id IS DISTINCT FROM canonical_client_id
                OR tenant_key IS DISTINCT FROM canonical_tenant_key
           )
       );

    IF conflicting_rows <> 0 THEN
        RAISE EXCEPTION 'cod_web_out_identity_conflict';
    END IF;

    -- Update in place on the canonical identity key. Never delete/reinsert: the
    -- resolver's existing row identity therefore remains stable on reapply.
    -- The repository does not declare the registry's unique constraints, so do
    -- not make ON CONFLICT depend on an unproven database index.
    UPDATE oidc_tenant_registry
       SET client_id = canonical_client_id,
           tenant_key = canonical_tenant_key,
           status = 'active',
           allowed_scopes = canonical_scopes
     WHERE issuer = canonical_issuer
       AND subject = service_subject;

    GET DIAGNOSTICS updated_rows = ROW_COUNT;

    IF updated_rows > 1 THEN
        RAISE EXCEPTION 'cod_web_out_identity_duplicate';
    END IF;

    IF updated_rows = 0 THEN
        INSERT INTO oidc_tenant_registry (
            issuer,
            subject,
            client_id,
            tenant_key,
            status,
            allowed_scopes
        )
        VALUES (
            canonical_issuer,
            service_subject,
            canonical_client_id,
            canonical_tenant_key,
            'active',
            canonical_scopes
        );
    END IF;

    SELECT count(*)
      INTO exact_rows
      FROM oidc_tenant_registry
     WHERE issuer = canonical_issuer
       AND subject = service_subject
       AND client_id = canonical_client_id
       AND tenant_key = canonical_tenant_key
       AND status = 'active'
       AND allowed_scopes = canonical_scopes;

    IF exact_rows <> 1 THEN
        RAISE EXCEPTION 'cod_web_out_identity_readback_failed';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM oidc_tenant_registry
         WHERE client_id = canonical_client_id
           AND (
                   issuer IS DISTINCT FROM canonical_issuer
                OR subject IS DISTINCT FROM service_subject
                OR tenant_key IS DISTINCT FROM canonical_tenant_key
                OR status IS DISTINCT FROM 'active'
                OR allowed_scopes IS DISTINCT FROM canonical_scopes
           )
    ) THEN
        RAISE EXCEPTION 'cod_web_out_identity_not_unique';
    END IF;
END
$cod_web_out$;

COMMIT;
