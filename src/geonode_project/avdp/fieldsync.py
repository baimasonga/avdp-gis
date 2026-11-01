"""Pull field-survey submissions from KoboToolbox or ODK Central.

KoboToolbox: ``GET {server}/api/v2/assets/{form}/data/?format=json`` with
``Authorization: Token <API token>``; geopoints are "lat lon alt accuracy"
strings and ``_geolocation`` is [lat, lon].

ODK Central: ``GET {server}/v1/projects/{project}/forms/{form}.svc/Submissions``
(OData) with a bearer token or e-mail/password; geopoints are GeoJSON
points ``{"type": "Point", "coordinates": [lon, lat, alt]}``.

Submissions are flattened to one row per submission: group prefixes are
dropped from question names, system fields are left out except the
submission id and time, and questions whose names suggest personal data are
excluded unless asked for.
"""

import re
from dataclasses import dataclass, field

import requests

PAGE = 1000
PERSONAL_HINTS = (
    "phone", "mobile", "tel", "email", "national_id", "nin", "id_number", "passport",
    "respondent_name", "farmer_name", "full_name", "first_name", "last_name", "surname", "household_head",
    "signature", "photo_of_person",
)
KEEP_SYSTEM = {"_id": "submission_id", "__id": "submission_id", "_submission_time": "submitted", "submissionDate": "submitted"}


class SyncError(Exception):
    pass


@dataclass
class Rows:
    features: list = field(default_factory=list)
    skipped_no_location: int = 0
    excluded: set = field(default_factory=set)


def _get(url, headers=None, auth=None, params=None):
    try:
        response = requests.get(url, headers=headers or {}, auth=auth, params=params, timeout=60)
    except requests.RequestException as exc:
        raise SyncError(f"Cannot reach {url}: {exc}") from exc
    if response.status_code in (401, 403):
        raise SyncError("The server refused the credentials (check the token or account and form access).")
    if response.status_code == 404:
        raise SyncError("Form not found: check the server address and form id.")
    if not response.ok:
        raise SyncError(f"{url} answered {response.status_code}: {response.text[:200]}")
    return response.json()


def fetch_kobo(server, form, token):
    url = f"{server.rstrip('/')}/api/v2/assets/{form}/data/"
    headers = {"Authorization": f"Token {token}", "Accept": "application/json"}
    results, start = [], 0
    while True:
        page = _get(url, headers, params={"format": "json", "limit": PAGE, "start": start})
        batch = page.get("results", [])
        results.extend(batch)
        start += len(batch)
        if not batch or not page.get("next"):
            return results


def fetch_odk(server, project, form, token=None, user=None, password=None):
    url = f"{server.rstrip('/')}/v1/projects/{project}/forms/{form}.svc/Submissions"
    headers = {"Accept": "application/json"}
    auth = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif user and password:
        auth = (user, password)
    else:
        raise SyncError("ODK Central needs a token or an e-mail and password.")
    results, skip = [], 0
    while True:
        page = _get(url, headers, auth, params={"$top": PAGE, "$skip": skip})
        batch = page.get("value", [])
        results.extend(batch)
        skip += len(batch)
        if len(batch) < PAGE:
            return results


def _column(name):
    name = name.split("/")[-1]
    name = re.sub(r"[^0-9a-zA-Z_]+", "_", name).strip("_").lower()
    if not name or name[0].isdigit():
        name = f"q_{name}"
    return name[:60]


def _flatten(obj, prefix=""):
    """Nested ODK groups -> {"question": value}; Kobo already uses "group/question" keys."""
    out = {}
    for key, value in obj.items():
        path = f"{prefix}/{key}" if prefix else key
        if isinstance(value, dict) and value.get("type") != "Point" and key != "__system":
            out.update(_flatten(value, path))
        else:
            out[path] = value
    return out


def _kobo_point(value):
    parts = str(value).split()
    if len(parts) >= 2:
        try:
            lat, lon = float(parts[0]), float(parts[1])
            return lon, lat
        except ValueError:
            return None
    return None


def to_rows(submissions, source, keep_personal=(), exclude=()):
    """Turn submissions into GeoJSON features (points). Returns Rows."""
    rows = Rows()
    keep_personal = {k.lower() for k in keep_personal}
    exclude = {e.lower() for e in exclude}
    for sub in submissions:
        flat = _flatten(sub)
        point, props = None, {}
        for key, value in flat.items():
            base = key.split("/")[-1]
            if key in KEEP_SYSTEM or base in KEEP_SYSTEM:
                props[KEEP_SYSTEM.get(key, KEEP_SYSTEM.get(base))] = value
                continue
            if key == "__system" and isinstance(value, dict):
                props["submitted"] = value.get("submissionDate")
                continue
            if base.startswith("_") or key.startswith(("formhub", "meta/", "__")) or base in ("instanceID", "deprecatedID"):
                if key == "_geolocation" and point is None and isinstance(value, list) and len(value) == 2 and None not in value:
                    point = (float(value[1]), float(value[0]))
                continue
            if isinstance(value, dict) and value.get("type") == "Point":
                if point is None and value.get("coordinates"):
                    point = tuple(float(c) for c in value["coordinates"][:2])
                continue
            if source == "kobo" and isinstance(value, str) and point is None and re.fullmatch(r"-?\d+(\.\d+)? -?\d+(\.\d+)?( .*)?", value):
                point = _kobo_point(value)
                continue
            col = _column(key)
            if col in exclude or (any(h in col for h in PERSONAL_HINTS) and col not in keep_personal):
                rows.excluded.add(col)
                continue
            if isinstance(value, (list, dict)):
                value = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
            props[col] = value
        if point is None:
            rows.skipped_no_location += 1
            continue
        rows.features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": list(point)}, "properties": props})
    # Same columns on every feature (missing -> None), so the table schema is stable.
    columns = sorted({k for f in rows.features for k in f["properties"]})
    for f in rows.features:
        f["properties"] = {c: f["properties"].get(c) for c in columns}
    return rows
