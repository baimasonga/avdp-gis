"""Change history for vector datasets (a PostGIS trigger per dataset table).

Every insert, update and delete on a tracked table is written to
``avdp_change_log`` in the datastore with the time, the old and new values
(geometry as WKT) and where the change came from:

* "map editor"   - edits made in the browser (GeoServer's JDBC connection)
* "form sync"    - avdp_sync_form (sets avdp.source for its transaction)
* "upload or script" - anything else

All browser edits reach the database through GeoServer's single account, so
the log cannot say which person made an edit; GeoNode's own resource history
and the editors group limit who can edit at all.
"""

import json

from django.db import connections

from geonode_project.avdp import districts
from geonode_project.avdp.portal_ops import datastore, quote

LOG_TABLE = "avdp_change_log"
FUNCTION = "avdp_log_change"

SETUP_SQL = f"""
CREATE TABLE IF NOT EXISTS {LOG_TABLE} (
    id bigserial PRIMARY KEY,
    table_name text NOT NULL,
    feature_id text,
    operation text NOT NULL,
    source text NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT now(),
    old_values jsonb,
    new_values jsonb
);
CREATE INDEX IF NOT EXISTS {LOG_TABLE}_table_time ON {LOG_TABLE} (table_name, changed_at DESC);

CREATE OR REPLACE FUNCTION {FUNCTION}() RETURNS trigger AS $$
DECLARE
    geom_col text := TG_ARGV[0];
    id_col text := TG_ARGV[1];
    src text;
    old_j jsonb;
    new_j jsonb;
    wkt text;
BEGIN
    src := coalesce(nullif(current_setting('avdp.source', true), ''),
                    CASE WHEN current_setting('application_name', true) LIKE '%JDBC%' THEN 'map editor'
                         ELSE 'upload or script' END);
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        old_j := to_jsonb(OLD) - geom_col;
        EXECUTE format('SELECT ST_AsText($1.%I)', geom_col) USING OLD INTO wkt;
        old_j := old_j || jsonb_build_object('location', wkt);
    END IF;
    IF TG_OP IN ('UPDATE', 'INSERT') THEN
        new_j := to_jsonb(NEW) - geom_col;
        EXECUTE format('SELECT ST_AsText($1.%I)', geom_col) USING NEW INTO wkt;
        new_j := new_j || jsonb_build_object('location', wkt);
    END IF;
    IF TG_OP = 'UPDATE' AND old_j = new_j THEN
        RETURN NEW;
    END IF;
    INSERT INTO {LOG_TABLE} (table_name, feature_id, operation, source, old_values, new_values)
    VALUES (TG_TABLE_NAME, coalesce(new_j ->> id_col, old_j ->> id_col), lower(TG_OP), src, old_j, new_j);
    RETURN coalesce(NEW, OLD);
END;
$$ LANGUAGE plpgsql;
"""


def _trigger(table):
    return f"{table}_avdp_history"[:63]


def enable(dataset):
    geom = districts.geometry_column(dataset)
    if not geom:
        raise ValueError(f"{dataset.alternate} has no geometry column")
    fields = {a.attribute.lower(): a.attribute for a in dataset.attribute_set.all()}
    id_col = fields.get("fid") or fields.get("ogc_fid") or fields.get("gid") or "fid"
    with connections[datastore()].cursor() as cursor:
        cursor.execute(SETUP_SQL)
        cursor.execute(f"DROP TRIGGER IF EXISTS {quote(_trigger(dataset.name))} ON {quote(dataset.name)}")
        literal = lambda v: "'" + v.replace("'", "''") + "'"  # noqa: E731 - trigger arguments are string literals
        cursor.execute(
            f"CREATE TRIGGER {quote(_trigger(dataset.name))} AFTER INSERT OR UPDATE OR DELETE ON {quote(dataset.name)} "
            f"FOR EACH ROW EXECUTE FUNCTION {FUNCTION}({literal(geom)}, {literal(id_col)})"
        )


def disable(dataset):
    with connections[datastore()].cursor() as cursor:
        cursor.execute(f"DROP TRIGGER IF EXISTS {quote(_trigger(dataset.name))} ON {quote(dataset.name)}")


def is_enabled(dataset):
    with connections[datastore()].cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_trigger WHERE tgname = %s AND tgrelid = to_regclass(%s)",
            [_trigger(dataset.name), quote(dataset.name)],
        )
        return cursor.fetchone() is not None


def entries(dataset, limit=200):
    with connections[datastore()].cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", [LOG_TABLE])
        if cursor.fetchone()[0] is None:
            return []
        cursor.execute(
            f"SELECT changed_at, operation, source, feature_id, old_values, new_values FROM {LOG_TABLE} "
            "WHERE table_name = %s ORDER BY changed_at DESC, id DESC LIMIT %s",
            [dataset.name, limit],
        )
        rows = cursor.fetchall()
    out = []
    for changed_at, op, source, fid, old, new in rows:
        # Django's raw cursor may return jsonb as text
        old = json.loads(old) if isinstance(old, str) else (old or {})
        new = json.loads(new) if isinstance(new, str) else (new or {})
        keys = sorted(set(old) | set(new))
        changes = [(k, old.get(k), new.get(k)) for k in keys if old.get(k) != new.get(k)] if op == "update" else []
        label = (new or old).get("name") or (new or old).get("site_name") or fid
        out.append({"when": changed_at, "operation": op, "source": source, "feature": label, "changes": changes})
    return out
