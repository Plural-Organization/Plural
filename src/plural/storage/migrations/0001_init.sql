CREATE TABLE IF NOT EXISTS events (
  seq      INTEGER PRIMARY KEY,
  id       TEXT NOT NULL UNIQUE,
  ts       TEXT NOT NULL,
  actor_id TEXT,
  type     TEXT NOT NULL,
  payload  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
  seq   INTEGER PRIMARY KEY,
  state TEXT NOT NULL
);
