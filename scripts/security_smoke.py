#!/usr/bin/env python3
"""Permission and upload-security smoke test for a running AVDP GIS Portal.

Creates temporary users (random passwords, never printed) for each role,
probes the portal over HTTP exactly as a client would, then deletes the
users and anything they uploaded. Run from the repository root while the
stack is up and the demo import has been run:

    python3 scripts/security_smoke.py [--base http://localhost]

Exit code is non-zero if any check fails.
"""

import argparse
import io
import json
import secrets
import subprocess
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from portal_client import PortalClient  # noqa: E402

ROLES = {
    # role: groups to join (besides the defaults GeoNode assigns)
    "outsider": [],
    "viewer": ["avdp-viewers"],
    "editor": ["avdp-editors"],
}
PREFIX = "avdp_smoke_"

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  -- ' + detail) if detail and not ok else ''}")


def manage_shell(code):
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "django", "python", "manage.py", "shell", "-c", code],
        capture_output=True, text=True, check=True,
    ).stdout
    return out.strip().splitlines()[-1] if out.strip() else ""


def create_users():
    creds = {role: secrets.token_urlsafe(18) for role in ROLES}
    code = f"""
from django.contrib.auth import get_user_model
from geonode.groups.models import GroupProfile
U = get_user_model()
creds = {json.dumps(creds)}
roles = {json.dumps(ROLES)}
for role, pw in creds.items():
    u, _ = U.objects.get_or_create(username='{PREFIX}' + role, defaults={{'email': role + '@example.invalid'}})
    u.set_password(pw); u.is_active = True; u.save()
    for slug in roles[role]:
        GroupProfile.objects.get(slug=slug).join(u)
# OAuth2 token the map client would use for GeoServer requests (test users only).
from geonode.base.auth import get_or_create_token
import json as _json
print(_json.dumps({{role: get_or_create_token(U.objects.get(username='{PREFIX}' + role)).token for role in creds}}))
"""
    tokens = json.loads(manage_shell(code))
    return creds, tokens


def delete_users():
    manage_shell(f"""
from django.contrib.auth import get_user_model
from geonode.base.models import ResourceBase
from geonode.resource.registry import resource_manager_registry as r
for res in ResourceBase.objects.filter(owner__username__startswith='{PREFIX}'):
    res = res.get_real_instance(); r.get_for_instance(res).delete(res.uuid, instance=res)
get_user_model().objects.filter(username__startswith='{PREFIX}').delete()
print('ok')
""")


def wfs_count(client, typename):
    r = client.ogc(f"/geoserver/ows?service=WFS&version=2.0.0&request=GetFeature&typeNames={typename}&resultType=hits")
    if r.status_code != 200 or "numberMatched" not in r.text:
        return None
    return int(r.text.split('numberMatched="')[1].split('"')[0])


def wms_ok(client, typename):
    r = client.ogc(
        "/geoserver/ows?service=WMS&version=1.1.1&request=GetMap&layers=" + typename
        + "&styles=&bbox=-13.5,6.8,-10.2,10.1&width=64&height=64&srs=EPSG:4326&format=image/png"
    )
    return r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image/")


def gfi_ok(client, typename):
    r = client.ogc(
        "/geoserver/ows?service=WMS&version=1.1.1&request=GetFeatureInfo&layers=" + typename
        + "&query_layers=" + typename
        + "&styles=&bbox=-13.5,6.8,-10.2,10.1&width=101&height=101&srs=EPSG:4326&x=50&y=50"
        + "&info_format=application/json&feature_count=5"
    )
    return r.status_code == 200 and r.text.lstrip().startswith("{") and '"features"' in r.text


def can_download(client, pk, typename):
    asset = client.get(f"/api/v2/assets/{pk}/download", allow_redirects=False)
    shp = client.ogc(
        f"/geoserver/ows?service=WFS&version=1.0.0&request=GetFeature&typename={typename}&outputFormat=SHAPE-ZIP"
    )
    shp_ok = shp.status_code == 200 and shp.content[:2] == b"PK"
    return asset.status_code == 200 or shp_ok


def upload(client, filename, content, extra=None):
    files = {"base_file": (filename, content)}
    data = {"action": "upload", **(extra or {})}
    return client.request("POST", "/api/v2/uploads/upload", files=files, data=data)


def wait_execution(client, exec_id, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/v2/executionrequest/{exec_id}")
        if r.status_code == 200:
            req = r.json().get("request", {})
            if req.get("status") in ("finished", "failed"):
                return req
        time.sleep(2)
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost")
    args = ap.parse_args()
    env = dict(line.strip().split("=", 1) for line in open(".env") if "=" in line and not line.startswith("#"))

    admin = PortalClient(args.base)
    assert admin.login(env["ADMIN_USERNAME"], env["ADMIN_PASSWORD"]), "admin login failed"
    ds = admin.get("/api/v2/datasets?filter{name}=avdp_demo_farm_plots").json()["datasets"]
    if not ds:
        sys.exit("Demo datasets not found: run avdp_import_demo first.")
    pk, typename = ds[0]["pk"], ds[0]["alternate"]
    maps = admin.get("/api/v2/resources?filter{resource_type}=map&search=Synthetic").json()["resources"]
    map_pk = maps[0]["pk"] if maps else None
    public = admin.get(f"/api/v2/resources/{pk}/permissions").json()
    is_public = any(g.get("name") == "anonymous" and g.get("permissions") != "none" for g in public.get("groups", []))
    print(f"Testing dataset {typename} (pk {pk}), map pk {map_pk}, public={is_public}\n")

    creds, tokens = create_users()
    try:
        clients = {"anonymous": PortalClient(args.base)}
        clients["anonymous"].get("/")
        for role, pw in creds.items():
            c = PortalClient(args.base)
            check(f"{role}: can sign in", c.login(PREFIX + role, pw))
            c._ogc_token = tokens[role]
            clients[role] = c
        # The admin's own OAuth token is not handled here; admin map rendering is
        # verified in the browser. Admin is still checked on the REST endpoints.
        admin._ogc_token = None
        clients["admin"] = admin

        # expected read access to the private demo dataset
        expect_read = {"anonymous": is_public, "outsider": is_public, "viewer": True, "editor": True, "admin": True}
        expect_download = {"anonymous": False, "outsider": False, "viewer": True, "editor": True, "admin": True}
        for role, c in clients.items():
            exp = expect_read[role]
            ogc_checked = role != "admin"
            r = c.get(f"/api/v2/datasets/{pk}")
            check(f"{role}: dataset API {'allowed' if exp else 'denied'}", (r.status_code == 200) == exp, str(r.status_code))
            listed = c.get("/api/v2/resources?search=SYNTHETIC&page_size=50").json().get("total", 0)
            check(f"{role}: catalogue lists demo resources = {exp}", (listed > 0) == exp, f"total={listed}")
            if ogc_checked:
                check(f"{role}: WMS GetMap {'allowed' if exp else 'denied'}", wms_ok(c, typename) == exp)
                check(f"{role}: WMS GetFeatureInfo {'allowed' if exp else 'denied'}", gfi_ok(c, typename) == exp)
                # GeoNode treats WFS feature access as "download", not "view".
                n = wfs_count(c, typename)
                exp_wfs = expect_download[role]
                check(f"{role}: WFS features {'visible' if exp_wfs else 'hidden'}", (n == 50) if exp_wfs else (not n),
                      f"hits={n}")
            dl = can_download(c, pk, typename)
            check(f"{role}: download {'allowed' if expect_download[role] else 'denied'}",
                  dl == expect_download[role], str(dl))
            if map_pk:
                r = c.get(f"/api/v2/maps/{map_pk}")
                check(f"{role}: map API {'allowed' if exp else 'denied'}", (r.status_code == 200) == exp, str(r.status_code))
            r = c.get(f"/showmetadata/xsl/{pk}")
            check(f"{role}: metadata XSL page {'allowed' if exp else 'denied'}",
                  (r.status_code == 200 and "avdp_demo" in r.text) == exp, str(r.status_code))

        # GeoServer administration is not open to the public
        r = clients["anonymous"].get("/geoserver/rest/workspaces.json")
        check("anonymous: GeoServer REST denied", r.status_code in (401, 403), str(r.status_code))
        r = clients["viewer"].get("/geoserver/rest/workspaces.json")
        check("viewer: GeoServer REST denied", r.status_code in (401, 403), str(r.status_code))
        r = clients["editor"].get("/admin/", allow_redirects=False)
        check("editor: Django admin denied", r.status_code in (302, 403), str(r.status_code))

        # Upload rights
        geojson = json.dumps({"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"name": "smoke"}, "geometry": {"type": "Point", "coordinates": [-11.5, 8.5]}}
        ]}).encode()
        r = upload(clients["anonymous"], "smoke.geojson", geojson)
        check("anonymous: upload denied", r.status_code in (401, 403), str(r.status_code))
        r = upload(clients["outsider"], "smoke.geojson", geojson)
        check("outsider (no editor role): upload denied", r.status_code == 403, str(r.status_code))
        r = upload(clients["viewer"], "smoke.geojson", geojson)
        check("viewer: upload denied", r.status_code == 403, str(r.status_code))

        r = upload(clients["editor"], "avdp_smoke_points.geojson", geojson)
        check("editor: valid GeoJSON upload accepted", r.status_code == 201, f"{r.status_code} {r.text[:200]}")
        new_pk = None
        if r.status_code == 201:
            req = wait_execution(clients["editor"], r.json()["execution_id"])
            check("editor: import finished", req.get("status") == "finished", json.dumps(req)[:300])
            mine = clients["editor"].get("/api/v2/datasets?filter{owner.username}=" + PREFIX + "editor").json()
            if mine.get("datasets"):
                new_pk = mine["datasets"][0]["pk"]
                alt = mine["datasets"][0]["alternate"]
                check("new upload: private to anonymous (API)", clients["anonymous"].get(f"/api/v2/datasets/{new_pk}").status_code in (401, 403, 404))
                check("new upload: private to anonymous (WMS)", not wms_ok(clients["anonymous"], alt))
                check("new upload: private to anonymous (WFS)", not wfs_count(clients["anonymous"], alt))
                check("new upload: not visible to other users (viewer)", clients["viewer"].get(f"/api/v2/datasets/{new_pk}").status_code in (403, 404))
                check("new upload: visible to its owner", clients["editor"].get(f"/api/v2/datasets/{new_pk}").status_code == 200)

        # Hostile / malformed uploads (rejected by GeoNode's upload validation)
        def zip_bytes(entries):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for name, data in entries:
                    z.writestr(name, data)
            return buf.getvalue()

        hostile = {
            "zip with path traversal": ("evil.zip", zip_bytes([("../../evil.geojson", geojson)])),
            "zip bomb (compression ratio)": ("bomb.zip", zip_bytes([("a.geojson", b"0" * (30 * 1024 * 1024))])),
            "executable disguised as GeoJSON": ("tool.geojson", b"MZ\x90\x00" + b"\x00" * 200),
            "unsupported extension (.exe)": ("tool.exe", b"MZ\x90\x00" + b"\x00" * 200),
            "malformed GeoJSON": ("broken.geojson", b'{"type": "FeatureCollection", "features": [ {'),
            "shapefile without companions": ("lonely.shp", b"\x00\x00\x27\x0a" + b"\x00" * 96),
        }
        for label, (name, content) in hostile.items():
            r = upload(clients["editor"], name, content)
            if r.status_code == 201:
                req = wait_execution(clients["editor"], r.json()["execution_id"], timeout=120)
                rejected = req.get("status") == "failed"
                detail = f"accepted by API, import status={req.get('status')}"
            else:
                rejected, detail = r.status_code in (400, 403, 413, 500), f"{r.status_code} {r.text[:120]}"
            check(f"upload rejected: {label}", rejected, detail)

        # Unsafe filename is not used as a filesystem path
        r = upload(clients["editor"], "../../../tmp/avdp_smoke_traversal.geojson", geojson)
        if r.status_code == 201:
            wait_execution(clients["editor"], r.json()["execution_id"])
        out = subprocess.run(["docker", "compose", "exec", "-T", "django", "sh", "-c",
                              "ls /tmp/avdp_smoke_traversal.geojson 2>/dev/null; ls /avdp_smoke_traversal.geojson 2>/dev/null"],
                             capture_output=True, text=True).stdout
        check("unsafe upload filename did not escape the upload directory", "avdp_smoke_traversal" not in out, out)

        limits = admin.get("/api/v2/upload-size-limits").json()
        sizes = {x["slug"]: x["max_size"] for x in limits.get("upload-size-limits", [])}
        check("upload size limits are configured", bool(sizes), json.dumps(sizes))
        print("Upload size limits (bytes):", json.dumps(sizes))
    finally:
        delete_users()

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
