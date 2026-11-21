-- Whisk chat uploads whose bytes are kept (photos, CSV, XLSX), agent.md §5 "Uploads". The bytes are
-- ordinary content-addressed blobs; a row here holds its blob like a core_files row does
-- (files.service.BLOB_HOLDERS), so the sweep keeps it and the backup manifest lists it. PDF and
-- DOCX keep only their extracted text, in the message content.
CREATE TABLE core_agent_uploads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES core_agent_conversations(id) ON DELETE CASCADE,
    message_id      INTEGER NOT NULL REFERENCES core_agent_messages(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES core_users(id),
    filename        TEXT NOT NULL,
    mime_type       TEXT NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('image', 'table')),
    byte_size       INTEGER NOT NULL,
    sha256          TEXT NOT NULL REFERENCES core_file_blobs(sha256),
    created_at      TEXT NOT NULL
);
CREATE INDEX core_agent_uploads_message ON core_agent_uploads (message_id);
CREATE INDEX core_agent_uploads_conversation ON core_agent_uploads (conversation_id);
CREATE INDEX core_agent_uploads_sha ON core_agent_uploads (sha256);
