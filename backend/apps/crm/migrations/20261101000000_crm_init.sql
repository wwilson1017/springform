-- CRM: deals on a pipeline over core's people and organizations (plan §7). Ported from
-- CakeCRM's deals, activity_log, deal_stage_events, deal_ai_touch_evidence, crm_stage_criteria,
-- crm_field_provenance and crm_meta (docs/PROVENANCE.md). Chatter, attachments, custom fields,
-- saved views, reminders and notifications are core's; contacts and companies are core_people
-- and core_organizations. Timestamps are canonical UTC text written by core.clock; dates the
-- user picks are YYYY-MM-DD text; money is integer cents.

CREATE TABLE crm_deals (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    title                   TEXT NOT NULL,
    person_id               INTEGER REFERENCES core_people(id) ON DELETE SET NULL,
    organization_id         INTEGER REFERENCES core_organizations(id) ON DELETE SET NULL,
    owner_user_id           INTEGER REFERENCES core_users(id) ON DELETE SET NULL,
    stage                   TEXT NOT NULL DEFAULT 'lead'
                            CHECK (stage IN ('lead', 'qualified', 'proposal', 'negotiation', 'won', 'lost')),
    -- open | won | lost, derived from stage so the two can never disagree.
    status                  TEXT GENERATED ALWAYS AS (CASE WHEN stage IN ('won', 'lost') THEN stage ELSE 'open' END) VIRTUAL,
    value_cents             INTEGER NOT NULL DEFAULT 0 CHECK (typeof(value_cents) = 'integer'),
    currency                TEXT NOT NULL DEFAULT 'USD',
    probability             INTEGER NOT NULL DEFAULT 0 CHECK (probability BETWEEN 0 AND 100),
    expected_close          TEXT,                       -- YYYY-MM-DD
    closed_on               TEXT,                       -- YYYY-MM-DD, install-local day it was won
    lost_reason             TEXT NOT NULL DEFAULT '',   -- cleared when the deal leaves lost
    deal_temperature        TEXT CHECK (deal_temperature IN ('hot', 'warm', 'cold')),  -- NULL: not triaged
    notes                   TEXT NOT NULL DEFAULT '',
    lead_score              INTEGER CHECK (lead_score BETWEEN 0 AND 100),             -- NULL: never scored
    lead_score_at           TEXT,
    ai_touch_count          INTEGER,                    -- NULL: never counted; 0 is a real count
    ai_touch_count_at       TEXT,                       -- newest evidence the count was built on
    ai_touch_evidence_count INTEGER,
    touch_dirty             INTEGER NOT NULL DEFAULT 0, -- set by the record hook; the touch job drains it
    archived_at             TEXT,                       -- soft archive; NULL is live
    archived_by             INTEGER REFERENCES core_users(id) ON DELETE SET NULL,
    archived_reason         TEXT,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);
CREATE INDEX crm_deals_live_stage ON crm_deals (stage) WHERE archived_at IS NULL;
CREATE INDEX crm_deals_person ON crm_deals (person_id);
CREATE INDEX crm_deals_organization ON crm_deals (organization_id);
CREATE INDEX crm_deals_owner ON crm_deals (owner_user_id);
CREATE INDEX crm_deals_touch_dirty ON crm_deals (id) WHERE touch_dirty = 1;
CREATE INDEX crm_deals_lead_score_at ON crm_deals (lead_score_at);

-- Deal search: unicode61 folds case and accents. The deal's own words; linked names are
-- matched through core_contacts_fts at query time.
CREATE VIRTUAL TABLE crm_deals_fts USING fts5 (body, tokenize = 'unicode61 remove_diacritics 2');
CREATE TRIGGER crm_deals_fts_insert AFTER INSERT ON crm_deals BEGIN
    INSERT INTO crm_deals_fts (rowid, body) VALUES (NEW.id, concat_ws(' ', NEW.title, NEW.notes, NEW.lost_reason));
END;
CREATE TRIGGER crm_deals_fts_update AFTER UPDATE OF title, notes, lost_reason ON crm_deals BEGIN
    DELETE FROM crm_deals_fts WHERE rowid = OLD.id;
    INSERT INTO crm_deals_fts (rowid, body) VALUES (NEW.id, concat_ws(' ', NEW.title, NEW.notes, NEW.lost_reason));
END;
CREATE TRIGGER crm_deals_fts_delete AFTER DELETE ON crm_deals BEGIN
    DELETE FROM crm_deals_fts WHERE rowid = OLD.id;
END;

-- A person's lead score (core_people is core's, so the CRM's derived number lives here).
CREATE TABLE crm_person_scores (
    person_id     INTEGER PRIMARY KEY REFERENCES core_people(id),
    lead_score    INTEGER NOT NULL CHECK (lead_score BETWEEN 0 AND 100),
    lead_score_at TEXT NOT NULL
);

-- Calls, emails, meetings: things that happened. actor_user_id is who did it (NULL: no human).
CREATE TABLE crm_activity_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    activity      TEXT NOT NULL,
    note          TEXT NOT NULL DEFAULT '',
    deal_id       INTEGER REFERENCES crm_deals(id) ON DELETE SET NULL,
    person_id     INTEGER REFERENCES core_people(id) ON DELETE SET NULL,
    actor_user_id INTEGER REFERENCES core_users(id) ON DELETE SET NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX crm_activity_log_deal ON crm_activity_log (deal_id, created_at);
CREATE INDEX crm_activity_log_person ON crm_activity_log (person_id, created_at);
CREATE INDEX crm_activity_log_actor ON crm_activity_log (actor_user_id, created_at);
CREATE INDEX crm_activity_log_created ON crm_activity_log (created_at);

-- Stage history, written in the same transaction as the move. Append-only.
CREATE TABLE crm_deal_stage_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id    INTEGER NOT NULL REFERENCES crm_deals(id) ON DELETE CASCADE,
    old_stage  TEXT NOT NULL DEFAULT '',
    new_stage  TEXT NOT NULL,
    user_id    INTEGER REFERENCES core_users(id) ON DELETE SET NULL,
    changed_at TEXT NOT NULL
);
CREATE INDEX crm_deal_stage_events_deal ON crm_deal_stage_events (deal_id, changed_at);

-- The per-evidence verdicts behind ai_touch_count: one JSON snapshot per deal, replaced whole.
CREATE TABLE crm_deal_ai_touch_evidence (
    deal_id     INTEGER PRIMARY KEY REFERENCES crm_deals(id) ON DELETE CASCADE,
    verdicts    TEXT NOT NULL,
    computed_at TEXT NOT NULL
);

-- What each stage means: a summary and an exit checklist. seed() writes the defaults.
CREATE TABLE crm_stage_criteria (
    id         INTEGER PRIMARY KEY,
    stage      TEXT NOT NULL,
    summary    TEXT NOT NULL,
    checklist  TEXT NOT NULL,                  -- JSON array of strings
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX crm_stage_criteria_stage ON crm_stage_criteria (stage);

-- Which fields Whisk wrote, so the UI shows an AI badge until a person confirms or edits them.
-- The badge is live while confirmed_at is NULL and value_snapshot equals the current value.
CREATE TABLE crm_field_provenance (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type    TEXT NOT NULL,              -- crm.deal | core.person | core.organization
    entity_id      INTEGER NOT NULL,
    field_name     TEXT NOT NULL,
    value_snapshot TEXT,
    source         TEXT NOT NULL,              -- assistant
    populated_at   TEXT NOT NULL,
    confirmed_at   TEXT,
    confirmed_by   INTEGER REFERENCES core_users(id) ON DELETE SET NULL
);
CREATE UNIQUE INDEX crm_field_provenance_field ON crm_field_provenance (entity_type, entity_id, field_name);

-- First-run state and job bookkeeping: one row, written by seed().
CREATE TABLE crm_meta (
    id                   INTEGER PRIMARY KEY CHECK (id = 1),
    sample_data_loaded   INTEGER NOT NULL DEFAULT 0,
    onboarding_dismissed INTEGER NOT NULL DEFAULT 0,
    scores_refreshed_at  TEXT,
    updated_at           TEXT NOT NULL
);
