-- Canonical PostgreSQL 16 DDL for section 4. Alembic revision 0001 must create exactly this.
-- Conventions: UUIDv7 ids, timestamptz in UTC, snake_case, created_at/updated_at on every table (updated_at via trigger).

CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- uuidv7(): time-ordered UUID (PostgreSQL 16 has no builtin; this function is part of the contract)
CREATE OR REPLACE FUNCTION uuidv7() RETURNS uuid AS $$
  SELECT encode(
    set_bit(set_bit(
      overlay(uuid_send(gen_random_uuid()) PLACING substring(int8send(floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint) FROM 3) FROM 1 FOR 6),
      52, 1), 53, 1), 'hex')::uuid;
$$ LANGUAGE sql VOLATILE;

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END; $$ LANGUAGE plpgsql;

-- Every table below gets: id uuid PRIMARY KEY DEFAULT uuidv7(), created_at timestamptz NOT NULL DEFAULT now(),
-- updated_at timestamptz NOT NULL DEFAULT now(), and a BEFORE UPDATE trigger calling set_updated_at().
-- Written out in full for the first table; abbreviated as "-- std" afterwards.

CREATE TABLE jurisdiction (
  id uuid PRIMARY KEY DEFAULT uuidv7(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  code text NOT NULL UNIQUE,                       -- ISO 3166-1 alpha-2, ISO 3166-2, or custom (EU, COE, OECD, UN, INTL)
  name text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('country','subdivision','supranational')),
  parent_id uuid REFERENCES jurisdiction(id),
  region_code text,                                -- UN M49
  geometry_ref text,                               -- feature id in the vendored GeoJSON
  active boolean NOT NULL DEFAULT true
);
CREATE TRIGGER trg_jurisdiction_updated BEFORE UPDATE ON jurisdiction FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE "user" ( -- std
  id uuid PRIMARY KEY DEFAULT uuidv7(), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  email citext NOT NULL UNIQUE,                    -- requires CREATE EXTENSION citext
  display_name text NOT NULL,
  password_hash text,                              -- Argon2id; NULL for SSO-only users
  external_subject text UNIQUE,                    -- OIDC subject
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled','locked')),
  must_change_password boolean NOT NULL DEFAULT false,
  last_login_at timestamptz,
  failed_logins integer NOT NULL DEFAULT 0,
  locked_until timestamptz,
  preferences jsonb NOT NULL DEFAULT '{}'::jsonb    -- validated by the Preferences schema in OpenAPI
);

CREATE TABLE role ( -- std
  id uuid PRIMARY KEY DEFAULT uuidv7(), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  key text NOT NULL UNIQUE, label text NOT NULL, system boolean NOT NULL DEFAULT false
);
CREATE TABLE permission (
  key text PRIMARY KEY, description text NOT NULL, module text NOT NULL
);
CREATE TABLE role_permission (
  role_id uuid NOT NULL REFERENCES role(id) ON DELETE CASCADE,
  permission_key text NOT NULL REFERENCES permission(key) ON DELETE CASCADE,
  PRIMARY KEY (role_id, permission_key)
);
CREATE TABLE user_role (
  user_id uuid NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
  role_id uuid NOT NULL REFERENCES role(id) ON DELETE CASCADE,
  PRIMARY KEY (user_id, role_id)
);

CREATE TABLE session (
  id uuid PRIMARY KEY DEFAULT uuidv7(), created_at timestamptz NOT NULL DEFAULT now(),
  user_id uuid NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
  token_hash text NOT NULL UNIQUE,                 -- sha256 of the cookie value
  expires_at timestamptz NOT NULL,
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  ip inet, user_agent text,
  revoked_at timestamptz
);
CREATE INDEX ix_session_user ON session(user_id) WHERE revoked_at IS NULL;

CREATE TABLE facet ( -- std
  id uuid PRIMARY KEY DEFAULT uuidv7(), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  key text NOT NULL UNIQUE CHECK (key ~ '^[a-z][a-z0-9_]{1,40}$'),
  label text NOT NULL,
  value_type text NOT NULL CHECK (value_type IN ('term','text','number','date','boolean')),
  multi boolean NOT NULL DEFAULT true,
  required boolean NOT NULL DEFAULT false,
  show_in_view_selector boolean NOT NULL DEFAULT false,
  show_in_filters boolean NOT NULL DEFAULT true,
  sort_order integer NOT NULL DEFAULT 100,
  system boolean NOT NULL DEFAULT false,
  hidden boolean NOT NULL DEFAULT false
);
CREATE TABLE term ( -- std
  id uuid PRIMARY KEY DEFAULT uuidv7(), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  facet_id uuid NOT NULL REFERENCES facet(id) ON DELETE CASCADE,
  key text NOT NULL CHECK (key ~ '^[a-z0-9][a-z0-9_-]{0,60}$'),
  label text NOT NULL,
  parent_id uuid REFERENCES term(id),
  synonyms text[] NOT NULL DEFAULT '{}',
  match_rules jsonb NOT NULL DEFAULT '{}'::jsonb,  -- {keywords:[], regex:[], languages:[], min_hits:1, weight:1.0}
  color_token text,
  active boolean NOT NULL DEFAULT true,
  UNIQUE (facet_id, key)
);

CREATE TABLE source ( -- std
  id uuid PRIMARY KEY DEFAULT uuidv7(), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  name text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('rss','web_page','web_crawl','search_query','api_feed','manual')),
  url text,
  config jsonb NOT NULL DEFAULT '{}'::jsonb,       -- validated by docs/contracts/connectors.yaml
  default_jurisdiction_ids uuid[] NOT NULL DEFAULT '{}',
  default_term_ids uuid[] NOT NULL DEFAULT '{}',
  credibility text NOT NULL DEFAULT 'official' CHECK (credibility IN ('official','secondary','news')),
  robots_policy text NOT NULL DEFAULT 'respect' CHECK (robots_policy IN ('respect','override')),
  override_reason text,
  terms_url text,
  language text,                                   -- BCP 47 hint, NULL = detect
  enabled boolean NOT NULL DEFAULT true,
  owner_user_id uuid REFERENCES "user"(id),
  health text NOT NULL DEFAULT 'unknown' CHECK (health IN ('unknown','healthy','degraded','unhealthy')),
  consecutive_failures integer NOT NULL DEFAULT 0,
  catalogue_key text UNIQUE,                       -- CP-25 (migration 0008): key in seed/catalogue.yaml; NULL = added by an admin
  summary text,                                    -- CP-25: one line on what the source covers
  CHECK (robots_policy = 'respect' OR override_reason IS NOT NULL)
);

CREATE TABLE source_follower ( -- CP-25 (migration 0008): captured while its job is enabled and the source is enabled, or catalogue and followed
  source_id uuid NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source_id, user_id)
);
CREATE INDEX source_follower_user_idx ON source_follower (user_id);

CREATE TABLE feed_request ( -- std; CP-26 (migration 0009): a user's request for a feed not in the catalogue
  id uuid PRIMARY KEY DEFAULT uuidv7(), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  requested_by uuid NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
  url text NOT NULL,                               -- https; never fetched for the request itself
  reason text NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','declined','withdrawn')),
  decided_by uuid REFERENCES "user"(id),
  decided_at timestamptz,
  decision_note text,
  source_id uuid REFERENCES source(id),            -- the source an editor created for it
  CHECK (status <> 'approved' OR source_id IS NOT NULL)
);
CREATE INDEX feed_request_requester_idx ON feed_request (requested_by, status);
CREATE INDEX feed_request_status_idx ON feed_request (status, created_at);

CREATE TABLE capture_job ( -- std
  id uuid PRIMARY KEY DEFAULT uuidv7(), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  source_id uuid NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  cron text,                                       -- 5-field cron, or NULL when interval_seconds is used
  interval_seconds integer CHECK (interval_seconds IS NULL OR interval_seconds >= 900),
  timezone text NOT NULL DEFAULT 'UTC',
  max_items_per_run integer NOT NULL DEFAULT 200,
  rate_limit_per_minute integer NOT NULL DEFAULT 30,
  render_js boolean NOT NULL DEFAULT false,
  extraction_rules jsonb NOT NULL DEFAULT '{}'::jsonb,  -- validated by connectors.yaml
  change_threshold_pct numeric(5,2) NOT NULL DEFAULT 5,
  enabled boolean NOT NULL DEFAULT true,
  next_run_at timestamptz,
  last_run_at timestamptz,
  CHECK ((cron IS NULL) <> (interval_seconds IS NULL))
);
CREATE INDEX ix_capture_job_due ON capture_job(next_run_at) WHERE enabled;

CREATE TABLE capture_run (
  id uuid PRIMARY KEY DEFAULT uuidv7(), created_at timestamptz NOT NULL DEFAULT now(),
  job_id uuid NOT NULL REFERENCES capture_job(id) ON DELETE CASCADE,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  status text NOT NULL DEFAULT 'running' CHECK (status IN ('running','success','partial','failed','skipped')),
  items_new integer NOT NULL DEFAULT 0, items_changed integer NOT NULL DEFAULT 0, items_unchanged integer NOT NULL DEFAULT 0,
  http_status integer, bytes_fetched bigint NOT NULL DEFAULT 0,
  error_class text, error_message text,            -- error_message truncated to 500 chars, never page content
  robots_decision text,
  triggered_by uuid REFERENCES "user"(id)          -- NULL = scheduler
);
CREATE INDEX ix_capture_run_job ON capture_run(job_id, started_at DESC);
-- CP-11 (ADR-0006 amendment 1): one job per source, at most one unfinished run per job, and an
-- index for the scheduler's sweep and hand-over of unfinished runs.
ALTER TABLE capture_job ADD CONSTRAINT uq_capture_job_source UNIQUE (source_id);
CREATE UNIQUE INDEX uq_capture_run_unfinished ON capture_run(job_id) WHERE finished_at IS NULL;
CREATE INDEX ix_capture_run_open ON capture_run(created_at) WHERE finished_at IS NULL;
-- CP-14: where an incremental job got to (api_feed: the newest publication date stored), so a
-- truncated run continues; written by the worker only, and cleared when the source's settings change.
-- CP-16: web_page keeps its change-detection state here too: the last content hash and the object
-- store key of the text it was computed from ({"content_hash", "text_ref"}; listing mode: a key of
-- a per-URL manifest), so an unchanged page is counted and never handed to M4.
ALTER TABLE capture_job ADD COLUMN cursor jsonb;

CREATE TABLE item ( -- std
  id uuid PRIMARY KEY DEFAULT uuidv7(), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  source_id uuid NOT NULL REFERENCES source(id),
  canonical_url text NOT NULL,
  url_hash text NOT NULL UNIQUE,                   -- sha256 of the canonical URL
  external_id text,
  title text NOT NULL,
  title_en text,                                   -- translated title when translation ran
  summary text,
  summary_en text,
  language text,                                   -- BCP 47
  published_at timestamptz,
  discovered_at timestamptz NOT NULL DEFAULT now(),
  last_changed_at timestamptz NOT NULL DEFAULT now(),
  content_hash text NOT NULL,
  status text NOT NULL DEFAULT 'new' CHECK (status IN ('new','updated','unchanged','archived')),
  needs_review boolean NOT NULL DEFAULT false,
  translation_pending boolean NOT NULL DEFAULT false,
  current_version_no integer NOT NULL DEFAULT 1,
  regulation_id uuid,                              -- FK added after regulation table
  attributes jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {facet_key: value | [term_keys]} validated by M2
  search_vector tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(title_en,'')), 'A') ||
    setweight(to_tsvector('simple', coalesce(summary,'') || ' ' || coalesce(summary_en,'')), 'B')) STORED,
  fetched_host text,                               -- CP-19 (migration 0005): host the content was fetched from; NULL = never fetched (a feed summary)
  search_vector_stemmed tsvector GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, COALESCE(title, ''::text) || ' '::text || COALESCE(summary, ''::text)) || CASE WHEN language ~~ 'en%'::text THEN to_tsvector('english'::regconfig, COALESCE(title, ''::text) || ' '::text || COALESCE(summary, ''::text)) WHEN language ~~ 'de%'::text THEN to_tsvector('german'::regconfig, COALESCE(title, ''::text) || ' '::text || COALESCE(summary, ''::text)) WHEN language ~~ 'fr%'::text THEN to_tsvector('french'::regconfig, COALESCE(title, ''::text) || ' '::text || COALESCE(summary, ''::text)) WHEN language ~~ 'es%'::text THEN to_tsvector('spanish'::regconfig, COALESCE(title, ''::text) || ' '::text || COALESCE(summary, ''::text)) WHEN language ~~ 'pt%'::text THEN to_tsvector('portuguese'::regconfig, COALESCE(title, ''::text) || ' '::text || COALESCE(summary, ''::text)) ELSE ''::tsvector END) STORED -- CP-21 (migration 0007): the item's own language
  -- Language-specific configurations are applied in a per-language expression index by M5; 'simple' is the baseline.
);
CREATE INDEX ix_item_attributes ON item USING gin (attributes jsonb_path_ops);
CREATE INDEX ix_item_search ON item USING gin (search_vector);
CREATE INDEX ix_item_last_changed ON item(last_changed_at DESC);
CREATE INDEX ix_item_published ON item(published_at DESC);
CREATE INDEX ix_item_title_trgm ON item USING gin (title gin_trgm_ops);
CREATE INDEX ix_item_source_content ON item(source_id, content_hash); -- CP-20 (migration 0006)
CREATE INDEX ix_item_search_stemmed ON item USING gin (search_vector_stemmed); -- CP-21 (migration 0007)

CREATE TABLE item_version (
  id uuid PRIMARY KEY DEFAULT uuidv7(), created_at timestamptz NOT NULL DEFAULT now(),
  item_id uuid NOT NULL REFERENCES item(id) ON DELETE CASCADE,
  run_id uuid REFERENCES capture_run(id),
  version_no integer NOT NULL,
  content_text text NOT NULL,                      -- sanitized plain text
  content_html_ref text,                           -- object store key of sanitized HTML snapshot
  content_hash text NOT NULL,
  diff_from_previous text,                         -- unified diff, truncated to 64 KB
  changed_pct numeric(5,2),
  translations jsonb NOT NULL DEFAULT '{}'::jsonb, -- {"en": {"title":..., "summary":..., "text_ref":..., "provider":..., "at":...}}
  UNIQUE (item_id, version_no)
);

CREATE TABLE regulation ( -- std
  id uuid PRIMARY KEY DEFAULT uuidv7(), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  title text NOT NULL, short_name text,
  instrument_type text NOT NULL CHECK (instrument_type IN ('act','regulation','directive','bill','guidance','standard','decision','enforcement_action','consultation')),
  status text NOT NULL CHECK (status IN ('proposed','adopted','in_force','amended','repealed')),
  adopted_at date, in_force_at date, official_url text,
  attributes jsonb NOT NULL DEFAULT '{}'::jsonb
);
ALTER TABLE item ADD CONSTRAINT fk_item_regulation FOREIGN KEY (regulation_id) REFERENCES regulation(id);
CREATE TABLE regulation_jurisdiction (
  regulation_id uuid NOT NULL REFERENCES regulation(id) ON DELETE CASCADE,
  jurisdiction_id uuid NOT NULL REFERENCES jurisdiction(id) ON DELETE CASCADE,
  PRIMARY KEY (regulation_id, jurisdiction_id)
);

CREATE TABLE item_term (
  item_id uuid NOT NULL REFERENCES item(id) ON DELETE CASCADE,
  term_id uuid NOT NULL REFERENCES term(id) ON DELETE CASCADE,
  confidence numeric(4,3) NOT NULL DEFAULT 1 CHECK (confidence BETWEEN 0 AND 1),
  assigned_by text NOT NULL CHECK (assigned_by IN ('rule','model','user','source_default')),
  assigned_user_id uuid REFERENCES "user"(id),
  evidence text,
  feedback text CHECK (feedback IN ('correct','incorrect')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (item_id, term_id)
);
CREATE INDEX ix_item_term_term ON item_term(term_id, item_id);

CREATE TABLE item_jurisdiction (
  item_id uuid NOT NULL REFERENCES item(id) ON DELETE CASCADE,
  jurisdiction_id uuid NOT NULL REFERENCES jurisdiction(id) ON DELETE CASCADE,
  confidence numeric(4,3) NOT NULL DEFAULT 1 CHECK (confidence BETWEEN 0 AND 1),
  assigned_by text NOT NULL CHECK (assigned_by IN ('rule','model','user','source_default')),
  assigned_user_id uuid REFERENCES "user"(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (item_id, jurisdiction_id)
);
CREATE INDEX ix_item_jurisdiction_j ON item_jurisdiction(jurisdiction_id, item_id);

CREATE TABLE change_event (
  id uuid PRIMARY KEY DEFAULT uuidv7(), created_at timestamptz NOT NULL DEFAULT now(),
  item_id uuid NOT NULL REFERENCES item(id) ON DELETE CASCADE,
  jurisdiction_id uuid NOT NULL REFERENCES jurisdiction(id),
  kind text NOT NULL CHECK (kind IN ('new_item','content_changed','status_changed','effective_date_reached')),
  occurred_at timestamptz NOT NULL DEFAULT now(),
  severity text NOT NULL DEFAULT 'info' CHECK (severity IN ('info','notable','major')),
  summary text,
  acknowledged_by uuid REFERENCES "user"(id),
  acknowledged_at timestamptz
);
CREATE INDEX ix_change_event_j_time ON change_event(jurisdiction_id, occurred_at DESC);
CREATE INDEX ix_change_event_time ON change_event(occurred_at DESC);
CREATE INDEX ix_change_event_item ON change_event(item_id, severity); -- CP-20 (migration 0006)

CREATE TABLE saved_view ( -- std
  id uuid PRIMARY KEY DEFAULT uuidv7(), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  user_id uuid REFERENCES "user"(id) ON DELETE CASCADE, -- NULL = shared view owned by admins
  name text NOT NULL,
  view_by text NOT NULL DEFAULT 'country',           -- 'country' | 'region' | 'regulation' | facet key
  filters jsonb NOT NULL DEFAULT '{}'::jsonb,         -- Query.filters from OpenAPI
  period_days integer NOT NULL DEFAULT 30,
  color_scheme text NOT NULL DEFAULT 'recency' CHECK (color_scheme IN ('recency','count','severity')),
  is_default boolean NOT NULL DEFAULT false,
  shared boolean NOT NULL DEFAULT false
);

CREATE TABLE report_template ( -- std
  id uuid PRIMARY KEY DEFAULT uuidv7(), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  key text NOT NULL UNIQUE, label text NOT NULL, description text,
  layout jsonb NOT NULL,                             -- Puck data
  query jsonb NOT NULL DEFAULT '{}'::jsonb,
  version integer NOT NULL DEFAULT 1
);
CREATE TABLE report_layout ( -- std
  id uuid PRIMARY KEY DEFAULT uuidv7(), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  user_id uuid NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
  name text NOT NULL,
  based_on_template_key text REFERENCES report_template(key),
  layout jsonb NOT NULL,
  query jsonb NOT NULL DEFAULT '{}'::jsonb,
  page_size text NOT NULL DEFAULT 'A4' CHECK (page_size IN ('A4','Letter')),
  orientation text NOT NULL DEFAULT 'portrait' CHECK (orientation IN ('portrait','landscape')),
  shared boolean NOT NULL DEFAULT false,
  version integer NOT NULL DEFAULT 1
);

CREATE TABLE printer ( -- std
  id uuid PRIMARY KEY DEFAULT uuidv7(), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  name text NOT NULL UNIQUE, ipp_url text NOT NULL, default_media text NOT NULL DEFAULT 'iso_a4_210x297mm', enabled boolean NOT NULL DEFAULT true
);

CREATE TABLE output_job ( -- std
  id uuid PRIMARY KEY DEFAULT uuidv7(), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  requested_by uuid NOT NULL REFERENCES "user"(id),
  kind text NOT NULL CHECK (kind IN ('pdf','email','print','csv')),
  report_layout_id uuid REFERENCES report_layout(id),
  report_template_key text REFERENCES report_template(key),
  saved_view_id uuid REFERENCES saved_view(id),
  query jsonb,
  destination jsonb NOT NULL DEFAULT '{}'::jsonb,    -- {emails:[], printer_id, copies}
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','rendering','sent','failed','cancelled')),
  artifact_ref text, artifact_bytes bigint, error_class text, error_message text,
  scheduled_cron text, schedule_timezone text, next_run_at timestamptz, parent_job_id uuid REFERENCES output_job(id),
  layout_version integer,
  attempts integer NOT NULL DEFAULT 0,
  finished_at timestamptz,
  CHECK (num_nonnulls(report_layout_id, report_template_key, saved_view_id, query) = 1)
);
CREATE INDEX ix_output_job_user ON output_job(requested_by, created_at DESC);
CREATE INDEX ix_output_job_due ON output_job(next_run_at) WHERE scheduled_cron IS NOT NULL AND status <> 'cancelled';

CREATE TABLE setting (
  key text PRIMARY KEY, value jsonb NOT NULL, updated_by uuid REFERENCES "user"(id), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE feature_flag (
  key text PRIMARY KEY, enabled boolean NOT NULL DEFAULT false, description text NOT NULL, updated_by uuid REFERENCES "user"(id), updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_log (
  id uuid PRIMARY KEY DEFAULT uuidv7(),
  occurred_at timestamptz NOT NULL DEFAULT now(),
  actor_user_id uuid REFERENCES "user"(id),
  action text NOT NULL,                               -- e.g. user.create, role.update, output.email, source.override_robots
  entity_type text NOT NULL, entity_id text,
  before jsonb, after jsonb,
  ip inet, request_id text
);
CREATE INDEX ix_audit_time ON audit_log(occurred_at DESC);
CREATE INDEX ix_audit_entity ON audit_log(entity_type, entity_id);
-- The application role gets INSERT and SELECT on audit_log only:
--   REVOKE UPDATE, DELETE ON audit_log FROM regwatch_app;

-- Materialized rollup for the map (M5 owns refresh)
CREATE MATERIALIZED VIEW jurisdiction_activity AS
  SELECT jurisdiction_id, date_trunc('day', occurred_at) AS day, count(*) AS events,
         max(occurred_at) AS last_changed_at,
         max(CASE severity WHEN 'major' THEN 3 WHEN 'notable' THEN 2 ELSE 1 END) AS max_severity
  FROM change_event GROUP BY 1, 2;
CREATE UNIQUE INDEX ix_jurisdiction_activity ON jurisdiction_activity(jurisdiction_id, day);
