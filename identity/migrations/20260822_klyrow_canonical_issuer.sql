BEGIN;

DO $$
DECLARE
    legacy_count integer;
    canonical_count integer;
BEGIN
    SELECT count(*) INTO legacy_count
      FROM service_credential_tenant_registry
     WHERE service = 'klyrow'
       AND issuer = 'https://auth.codestra.agency/realms/codestra';

    SELECT count(*) INTO canonical_count
      FROM service_credential_tenant_registry
     WHERE service = 'klyrow'
       AND issuer = 'https://auth.codestra.co/realms/codestra';

    IF legacy_count > 0 AND canonical_count > 0 THEN
        RAISE EXCEPTION
            'Klyrow issuer migration collision: legacy=%, canonical=%',
            legacy_count, canonical_count;
    END IF;
END $$;

UPDATE service_credential_tenant_registry
   SET issuer = 'https://auth.codestra.co/realms/codestra'
 WHERE service = 'klyrow'
   AND issuer = 'https://auth.codestra.agency/realms/codestra';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM service_credential_tenant_registry
         WHERE service = 'klyrow'
           AND issuer <> 'https://auth.codestra.co/realms/codestra'
    ) THEN
        RAISE EXCEPTION 'Klyrow credential registry contains a non-canonical issuer';
    END IF;
END $$;

COMMIT;
