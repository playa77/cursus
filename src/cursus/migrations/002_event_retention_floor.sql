-- WP-19 retention must advance this watermark in the deletion transaction.
ALTER TABLE coordination ADD COLUMN event_floor bigint NOT NULL DEFAULT 0
 CHECK(event_floor >= 0 AND event_floor <= cursor);
