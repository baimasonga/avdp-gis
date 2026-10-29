"""Feature-information (identify) templates for AVDP layers.

The templates use MapStore's ``${properties.<field>}`` syntax and are stored on
the dataset (``featureinfo_custom_template``) so the same formatted popup is
used in the dataset viewer and in maps. Styling lives in ``static/avdp/css``.
"""

from xml.sax.saxutils import escape

FIELD_LABELS = {
    "site_id": "Site ID",
    "id": "ID",
    "name": "Name",
    "crop": "Crop",
    "crop_type": "Crop",
    "main_crop": "Main crop",
    "status": "Status",
    "condition": "Condition",
    "surface": "Surface",
    "group_type": "Group type",
    "type": "Type",
    "input_type": "Input type",
    "technology": "Technology",
    "practice": "Practice",
    "dist_label": "District (label, unverified)",
    "district": "District (label, unverified)",
    "chiefdom": "Chiefdom (label, unverified)",
    "benefic": "Beneficiaries (this layer only)",
    "beneficiaries": "Beneficiaries (this layer only)",
    "members": "Members",
    "area_ha": "Area (ha)",
    "length_km": "Length (km)",
    "capacity_t": "Capacity (t)",
    "year": "Year",
    "synthetic": "Synthetic record",
}
HIDDEN = {"fid", "ogc_fid", "geom", "the_geom", "geometry", "wkb_geometry"}
TITLE_FIELDS = ("name", "site_name", "group_name", "title", "site_id")


def label_for(field):
    return FIELD_LABELS.get(field.lower(), field.replace("_", " ").strip().capitalize())


def build_template(layer_title, fields, synthetic=False):
    fields = [f for f in fields if f.lower() not in HIDDEN]
    lower = {f.lower(): f for f in fields}
    title_field = next((lower[f] for f in TITLE_FIELDS if f in lower), None)
    rows = "".join(
        f"<tr><th>{escape(label_for(f))}</th><td>${{properties.{f}}}</td></tr>" for f in fields if f != title_field
    )
    title = f"${{properties.{title_field}}}" if title_field else escape(layer_title)
    badge = '<span class="avdp-fi-badge">Synthetic demo</span>' if synthetic else ""
    note = (
        '<p class="avdp-fi-note">Invented demonstration data. District names are labels, not verified locations.</p>'
        if synthetic
        else ""
    )
    return (
        f'<div class="avdp-fi"><div class="avdp-fi-head"><span class="avdp-fi-layer">{escape(layer_title)}</span>'
        f'{badge}</div><div class="avdp-fi-title">{title}</div>'
        f'<table class="avdp-fi-table">{rows}</table>{note}</div>'
    )
