CREATE TABLE IF NOT EXISTS spans (
  id         TEXT PRIMARY KEY,
  run_id     TEXT NOT NULL,
  parent_id  TEXT,
  started_ms INTEGER NOT NULL,
  payload    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS spans_run ON spans (run_id, started_ms);
