-- The AI tool behind a todo made over an MCP link ("via ChatGPT"): its self-reported name, for
-- display only. NULL for todos made in the app, by Whisk or by another app.
ALTER TABLE todos_items ADD COLUMN source_client TEXT;
