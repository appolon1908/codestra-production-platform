BEGIN;

ALTER TABLE public.messages
  ADD COLUMN IF NOT EXISTS provider_attempt integer NOT NULL DEFAULT 0;

COMMIT;
