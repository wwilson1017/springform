-- Files: the sweep stamps a blob whose bytes are gone from disk; cleared when they come back.
ALTER TABLE core_file_blobs ADD COLUMN missing_at TEXT;
