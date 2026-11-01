"""Automatic data checks for vector datasets.

Run after every upload (avdp/signals.py) and by ``manage.py avdp_quality_check``.
Each check yields an issue with a level:

* problem  - features that cannot be mapped or lie outside Sierra Leone
* warning  - likely data errors: invalid shapes, exact duplicates, district
             labels that disagree with the location, fields mostly empty
* info     - worth knowing, not necessarily wrong

The result is stored in QualityReport and shown on the dataset's map page.
"""

from django.db import connections

from geonode_project.avdp import boundaries as bnd
from geonode_project.avdp import districts
from geonode_project.avdp.feature_info import label_for
from geonode_project.avdp.portal_ops import datastore, quote

EXAMPLES = 5
MOSTLY_EMPTY = 0.5  # share of empty values that makes a field worth a warning
OPTIONAL_FIELDS = ("photo_url", "photo", "image_url", "image", "picture", "remarks", "notes", "comments")


def _cursor():
    return connections[datastore()].cursor()


def _name_field(dataset):
    fields = {a.attribute.lower(): a.attribute for a in dataset.attribute_set.all()}
    return next((fields[f] for f in ("name", "site_name", "group_name", "site_id", "id") if f in fields), None)


def _examples(sql, params=()):
    with _cursor() as cursor:
        cursor.execute(sql + f" LIMIT {EXAMPLES}", params)
        return [str(r[0]) for r in cursor.fetchall() if r[0] is not None]


def run(dataset):
    """Return {"status", "summary", "total", "issues": [...]} for one vector dataset."""
    geom = districts.geometry_column(dataset)
    if not geom:
        return {"status": "ok", "summary": "Not a map layer; nothing to check.", "total": 0, "issues": []}
    table, g = quote(dataset.name), quote(geom)
    name = _name_field(dataset)
    label_expr = f"t.{quote(name)}::text" if name else "NULL"
    issues = []

    def add(level, check, message, count, examples=()):
        issues.append({"level": level, "check": check, "message": message, "count": count, "examples": list(examples)})

    with _cursor() as cursor:
        cursor.execute(f"SELECT count(*), count(*) FILTER (WHERE {g} IS NULL OR ST_IsEmpty({g})), "
                       f"count(*) FILTER (WHERE {g} IS NOT NULL AND NOT ST_IsValid({g})) FROM {table}")
        total, empty, invalid = cursor.fetchone()
    if empty:
        add("problem", "no-location", f"{empty} feature(s) have no location and cannot be mapped.", empty)
    if invalid:
        add("warning", "invalid-shape",
            f"{invalid} shape(s) are invalid (for example self-crossing outlines); areas and counts may be wrong.",
            invalid, _examples(f"SELECT {label_expr} FROM {table} t WHERE NOT ST_IsValid(t.{g})"))

    point = f"ST_PointOnSurface(ST_MakeValid({districts.geom_sql('t', geom)}))"
    try:
        bds = districts.boundary_dataset()
    except districts.DistrictError:
        bds = None
    if bds is not None:
        bg = quote(districts.geometry_column(bds))
        outside_where = (f"t.{g} IS NOT NULL AND NOT ST_IsEmpty(t.{g}) AND NOT EXISTS (SELECT 1 FROM {quote(bds.name)} b "
                         f"WHERE ST_Intersects(b.{bg}, ST_Transform({point}, ST_SRID(b.{bg}))))")
        where_text = "outside Sierra Leone's districts (abroad or at sea)"
    else:
        x0, y0, x1, y1 = bnd.SLE_ENVELOPE
        outside_where = (f"t.{g} IS NOT NULL AND NOT ST_IsEmpty(t.{g}) AND NOT ST_Intersects("
                         f"ST_Transform({point}, 4326), ST_MakeEnvelope({x0}, {y0}, {x1}, {y1}, 4326))")
        where_text = "outside Sierra Leone"
    with _cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {table} t WHERE {outside_where}")
        outside = cursor.fetchone()[0]
    if outside:
        swapped = ""
        with _cursor() as cursor:
            cursor.execute(
                f"SELECT count(*) FROM {table} t WHERE {outside_where} AND ST_Intersects("
                f"ST_FlipCoordinates(ST_Transform({point}, 4326)), ST_MakeEnvelope(-13.6, 6.7, -10.0, 10.2, 4326))"
            )
            if cursor.fetchone()[0]:
                swapped = " Some fall inside Sierra Leone if latitude and longitude are swapped."
        add("problem", "outside", f"{outside} feature(s) lie {where_text}.{swapped}", outside,
            _examples(f"SELECT {label_expr} FROM {table} t WHERE {outside_where}"))

    with _cursor() as cursor:
        cursor.execute(f"SELECT count(*) - count(DISTINCT ST_AsEWKB({g})) FROM {table} WHERE {g} IS NOT NULL")
        duplicates = cursor.fetchone()[0] or 0
    if duplicates:
        add("warning", "duplicate-location",
            f"{duplicates} feature(s) repeat the exact location of another feature (possible double entries).",
            duplicates,
            _examples(f"SELECT {label_expr} FROM {table} t WHERE ST_AsEWKB(t.{g}) IN (SELECT ST_AsEWKB({g}) "
                      f"FROM {table} GROUP BY 1 HAVING count(*) > 1)"))

    if total:
        for attr in dataset.attribute_set.all():
            if (attr.attribute_type or "").startswith("gml:") or attr.attribute.lower() in ("fid", "ogc_fid", "gid"):
                continue
            col = quote(attr.attribute)
            with _cursor() as cursor:
                cursor.execute(f"SELECT count(*) FROM {table} WHERE {col} IS NULL OR {col}::text = ''")
                missing = cursor.fetchone()[0]
            if attr.attribute.lower() in OPTIONAL_FIELDS:
                if missing:
                    add("info", "empty-field",
                        f"'{label_for(attr.attribute)}' (optional) is empty for {missing} of {total} features.", missing)
            elif missing == total:
                add("warning", "empty-field", f"'{label_for(attr.attribute)}' is empty for every feature.", missing)
            elif missing / total >= MOSTLY_EMPTY:
                add("warning", "empty-field",
                    f"'{label_for(attr.attribute)}' is empty for {missing} of {total} features.", missing)
            elif missing:
                add("info", "empty-field",
                    f"'{label_for(attr.attribute)}' is empty for {missing} of {total} features.", missing)

    label_field = districts.label_field_of(dataset)
    if bds is not None and label_field:
        report = districts.check_labels(dataset, label_field)
        if report.mismatch:
            add("warning", "district-label",
                f"{report.mismatch} of {report.checked} district labels ('{label_field}') name a different district "
                f"from the one the feature lies in.",
                report.mismatch,
                [f"{r[1] or r[0]}: '{r[2]}' but in {r[3]}" for r in report.rows if r[4] == "mismatch"][:EXAMPLES])
        if report.unknown_label:
            add("info", "district-label",
                f"{report.unknown_label} label(s) in '{label_field}' are not district names, so they cannot be checked.",
                report.unknown_label)

    levels = {i["level"] for i in issues}
    status = "problems" if "problem" in levels else ("warnings" if "warning" in levels else "ok")
    counts = {lvl: sum(1 for i in issues if i["level"] == lvl) for lvl in ("problem", "warning", "info")}
    if status == "ok":
        summary = f"No issues found in {total} features."
    else:
        parts = []
        if counts["problem"]:
            parts.append(f"{counts['problem']} problem" + ("s" if counts["problem"] > 1 else ""))
        if counts["warning"]:
            parts.append(f"{counts['warning']} warning" + ("s" if counts["warning"] > 1 else ""))
        summary = ", ".join(parts) + f" in {total} features."
    return {"status": status, "summary": summary, "total": total, "issues": issues}


def run_and_save(dataset):
    from geonode_project.models import QualityReport

    result = run(dataset)
    QualityReport.objects.update_or_create(
        resource=dataset.get_self_resource(),
        defaults={"status": result["status"], "summary": result["summary"], "report": result},
    )
    return result
