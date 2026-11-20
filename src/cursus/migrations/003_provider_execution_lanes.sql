-- Preserve logical workflow jobs while giving each provider an independent lane.
ALTER TABLE jobs DROP CONSTRAINT jobs_slot_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_slot_check CHECK
    (slot IN ('worker','verifier','frontier','repository','claude','codex','agy'));
-- Active grants are immutable. Setup refuses upgrade with unresolved attempts;
-- queued invocation migration is deterministic and never changes the provider.
UPDATE jobs SET slot=CASE WHEN payload->'invocation'->'role'->>'cli'='pi'
                         THEN 'worker' ELSE payload->'invocation'->'role'->>'cli' END
WHERE state='queued' AND payload ? 'invocation';
UPDATE jobs SET payload=jsonb_set(payload,'{slot}',to_jsonb(slot))
WHERE state='queued' AND payload ? 'invocation';
