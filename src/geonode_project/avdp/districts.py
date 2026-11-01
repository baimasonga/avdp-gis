"""District-level analysis against the official boundaries (avdp/boundaries.py).

* ``locate``: the district each feature of a dataset lies in (a point on
  the feature's surface, so lines and polygons count once).
* ``check_labels``: compare a district *label* stored in the data with the
  district the feature actually lies in.
* ``category_counts``: features per AVDP dataset category per district, for
  the district summary layer and the dashboard.

All spatial work happens in PostGIS (the GeoNode datastore).
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from django.conf import settings
from django.db import connections

from geonode.layers.models import Dataset
from geonode_project.avdp import boundaries as bnd
from geonode_project.avdp.portal_ops import datastore, quote

CATEGORY_THESAURUS = "avdp-categories"
# Summary columns, in homepage order (thesaurus concept -> column)
CATEGORY_COLUMNS = (
    ("crop-production", "crop_production", "Crop production"),
    ("farmer-organizations", "farmer_organizations", "Farmer organizations"),
    ("rural-infrastructure", "rural_infrastructure", "Rural infrastructure"),
    ("water-infrastructure", "water_infrastructure", "Water infrastructure"),
    ("storage-facilities", "storage_facilities", "Storage facilities"),
    ("input-distribution", "input_distribution", "Agricultural input distribution"),
    ("demonstration-extension", "demonstration_extension", "Demonstration and extension"),
)
LABEL_FIELDS = ("district", "dist_label", "district_name", "district_label", "adm2_name", "district_n")
AUDIENCE_GROUPS = {
    "viewers": ("avdp-viewers", "anonymous", "registered-members"),
    "public": ("anonymous",),
}


class DistrictError(Exception):
    pass


def boundary_dataset():
    ds = Dataset.objects.filter(keywords__name=bnd.MARKER).distinct().first()
    if ds is None:
        raise DistrictError("District boundaries are not loaded. Run `python manage.py avdp_load_boundaries` first.")
    return ds


def geometry_column(dataset):
    for attr in dataset.attribute_set.all():
        if (attr.attribute_type or "").startswith("gml:"):
            return attr.attribute
    return None


def _cursor():
    return connections[datastore()].cursor()


def geom_sql(alias, column):
    """SQL for a geometry column with a known SRID.

    CSV uploads are stored with SRID 0 although GeoNode publishes them as
    EPSG:4326 (latitude/longitude); treat an unknown SRID as 4326.
    """
    ref = f"{alias}.{quote(column)}"
    return f"(CASE WHEN ST_SRID({ref}) = 0 THEN ST_SetSRID({ref}, 4326) ELSE {ref} END)"


def locate(dataset, label_field=None):
    """Yield (fid, name, label, district, pcode) for each feature of ``dataset``."""
    bds = boundary_dataset()
    geom, bgeom = geometry_column(dataset), geometry_column(bds)
    if not geom:
        raise DistrictError(f"{dataset.alternate} has no geometry column.")
    fields = {a.attribute.lower(): a.attribute for a in dataset.attribute_set.all()}
    name_field = next((fields[f] for f in ("name", "site_name", "group_name", "site_id") if f in fields), None)
    pk = fields.get("fid") or fields.get("ogc_fid") or fields.get("gid")
    select = [
        f"t.{quote(pk)}::text" if pk else "NULL",
        f"t.{quote(name_field)}::text" if name_field else "NULL",
        f"t.{quote(label_field)}::text" if label_field else "NULL",
        "b.district",
        "b.district_pcode",
    ]
    sql = (
        f"SELECT {', '.join(select)} FROM {quote(dataset.name)} t "
        f"LEFT JOIN {quote(bds.name)} b ON ST_Intersects(b.{quote(bgeom)}, "
        f"ST_Transform(ST_PointOnSurface({geom_sql('t', geom)}), ST_SRID(b.{quote(bgeom)}))) "
        f"WHERE t.{quote(geom)} IS NOT NULL"
    )
    with _cursor() as cursor:
        cursor.execute(sql)
        yield from cursor.fetchall()


def label_field_of(dataset, preferred=None):
    fields = {a.attribute.lower(): a.attribute for a in dataset.attribute_set.all()}
    if preferred:
        return fields.get(preferred.lower())
    return next((fields[f] for f in LABEL_FIELDS if f in fields), None)


@dataclass
class LabelReport:
    dataset: str
    label_field: str
    total: int = 0
    match: int = 0
    mismatch: int = 0
    no_label: int = 0
    unknown_label: int = 0
    outside: int = 0
    rows: list = field(default_factory=list)  # (fid, name, label, actual, result)

    @property
    def checked(self):
        return self.match + self.mismatch


def check_labels(dataset, label_field):
    known = {bnd.district_key(d) for d in district_names()}
    report = LabelReport(dataset.alternate, label_field)
    for fid, name, label, actual, _pcode in locate(dataset, label_field):
        report.total += 1
        if actual is None:
            result = "outside boundaries"
            report.outside += 1
        elif not label:
            result = "no label"
            report.no_label += 1
        elif bnd.district_key(label) not in known:
            result = "label is not a district name"
            report.unknown_label += 1
        elif bnd.district_key(label) == bnd.district_key(actual):
            result = "match"
            report.match += 1
        else:
            result = "mismatch"
            report.mismatch += 1
        report.rows.append((fid, name, label, actual, result))
    return report


def district_names():
    bds = boundary_dataset()
    with _cursor() as cursor:
        cursor.execute(f"SELECT district FROM {quote(bds.name)} ORDER BY district")
        return [r[0] for r in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
def dataset_category(dataset):
    keyword = dataset.tkeywords.filter(thesaurus__identifier=CATEGORY_THESAURUS).first()
    return keyword.alt_label if keyword else None


def visible_to(dataset, audience):
    """True if the audience's groups may view the dataset (so counts reveal nothing private)."""
    if audience == "all":
        return True
    from guardian.shortcuts import get_groups_with_perms

    groups = get_groups_with_perms(dataset.get_self_resource(), attach_perms=True)
    allowed = AUDIENCE_GROUPS[audience]
    return any(g.name in allowed and "view_resourcebase" in perms for g, perms in groups.items())


def candidate_datasets(exclude=()):
    excluded_markers = {bnd.MARKER, *exclude}
    qs = Dataset.objects.filter(subtype__in=("vector", "vector_time")).exclude(keywords__name__in=excluded_markers)
    return list(qs.distinct().order_by("title"))


def category_counts(audience="viewers", exclude=()):
    """Return (counts {pcode: Counter(column)}, used [(dataset, column)], skipped [(dataset, reason)])."""
    columns = {concept: column for concept, column, _label in CATEGORY_COLUMNS}
    counts, used, skipped = defaultdict(Counter), [], []
    for dataset in candidate_datasets(exclude):
        concept = dataset_category(dataset)
        if concept not in columns:
            skipped.append((dataset, "no AVDP dataset category"))
            continue
        if not visible_to(dataset, audience):
            skipped.append((dataset, f"not shared with the '{audience}' audience"))
            continue
        column = columns[concept]
        for _fid, _name, _label, _district, pcode in locate(dataset):
            if pcode:
                counts[pcode][column] += 1
        used.append((dataset, column))
    return counts, used, skipped


def is_synthetic(dataset):
    return dataset.keywords.filter(name=getattr(settings, "AVDP_DEMO_KEYWORD", "avdp-synthetic-demo")).exists()
