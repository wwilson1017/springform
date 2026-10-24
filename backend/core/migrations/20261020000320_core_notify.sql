-- Notifications (in-app rows, external delivery intents, web push subscriptions) and reminders.
-- VAPID keys live in core_settings (notifications.vapid_public_key, notifications.vapid_private_key
-- encrypted), generated on first use.

-- One row per recipient. Listing and reading re-check the recipient's read access to the record
-- and hide the row (suppressed_at) when it is gone. Never deleted, so an id is never reused: the
-- push payload carries it for the service worker to drop a duplicate.
CREATE TABLE core_notifications (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES core_users(id),
    title         TEXT NOT NULL,
    message       TEXT NOT NULL DEFAULT '',
    entity_type   TEXT,
    entity_id     INTEGER,
    link          TEXT,                                -- in-app path
    created_at    TEXT NOT NULL,
    read_at       TEXT,
    suppressed_at TEXT,
    CHECK ((entity_type IS NULL) = (entity_id IS NULL))
);
CREATE INDEX core_notifications_user ON core_notifications (user_id, created_at) WHERE suppressed_at IS NULL;
CREATE INDEX core_notifications_entity ON core_notifications (entity_type, entity_id);

-- One delivery intent per external channel, written with the notification; the
-- core.notifications_flush job sends queued rows (at-least-once).
CREATE TABLE core_notification_deliveries (
    id              INTEGER PRIMARY KEY,
    notification_id INTEGER NOT NULL REFERENCES core_notifications(id) ON DELETE CASCADE,
    channel         TEXT NOT NULL,                     -- 'push' or a register_channel name
    status          TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'sent', 'failed', 'dropped')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    sent_at         TEXT,
    UNIQUE (notification_id, channel)
);
CREATE INDEX core_notification_deliveries_queued ON core_notification_deliveries (id) WHERE status = 'queued';

-- A browser. Re-subscribing re-stamps the endpoint to whoever is signed in on it.
CREATE TABLE core_push_subscriptions (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES core_users(id) ON DELETE CASCADE,
    endpoint   TEXT NOT NULL UNIQUE,
    p256dh     TEXT NOT NULL,
    auth       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    failed_at  TEXT                                    -- the push service answered 404/410
);
CREATE INDEX core_push_subscriptions_user ON core_push_subscriptions (user_id);

CREATE TABLE core_reminders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id INTEGER NOT NULL REFERENCES core_users(id),
    entity_type   TEXT,
    entity_id     INTEGER,
    title         TEXT NOT NULL,
    note          TEXT NOT NULL DEFAULT '',
    due_at        TEXT NOT NULL,
    repeat        TEXT,                                -- JSON {freq, anchor, time, tz}; NULL = once
    series_id     INTEGER,                             -- the first occurrence's id, shared by the series
    status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'voided', 'snoozed')),
    void_reason   TEXT,
    fired_at      TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    CHECK ((entity_type IS NULL) = (entity_id IS NULL))
);
CREATE INDEX core_reminders_due ON core_reminders (due_at) WHERE fired_at IS NULL AND status IN ('open', 'snoozed');
CREATE INDEX core_reminders_owner ON core_reminders (owner_user_id, due_at);
CREATE INDEX core_reminders_entity ON core_reminders (entity_type, entity_id);
CREATE INDEX core_reminders_series ON core_reminders (series_id);
