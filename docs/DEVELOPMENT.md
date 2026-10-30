# Development

## Prerequisites

- Docker Engine 24+ with the Compose v2 plugin (`docker compose`).
- ~8 GB RAM for the stack (GeoServer uses a 1–2 GB heap in development).
- Python 3 on the host only for `create-envfile.py` and the smoke-test scripts
  (`requests` package). Node.js + Playwright only for screenshot scripts.

## First run

```bash
python3 create-envfile.py --noinput --env_type=dev --hostname=localhost --email=admin@example.org
```

```bash
docker compose build
```

```bash
docker compose up -d
```

`create-envfile.py` fills every `{placeholder}` in `.env.example` with a random
value and writes `.env` with mode 0600. Review `.env` afterwards; never commit
it (`.gitignore` excludes `.env` and `.env.*` except `.env.example`).

The Django entrypoint, on each start: waits for the databases, runs
migrations, loads fixtures and sets the admin password **only on first start**
(or when `FORCE_REINIT=true`), collects static files, autoloads thesauri and
runs `python manage.py avdp_setup`.

Watch progress:

```bash
docker compose logs -f django
```

## Live-editing project code

The application image contains a copy of `src/`. To edit templates, CSS or
Python without rebuilding, create an untracked `docker-compose.override.yml`:

```yaml
services:
  django:
    volumes:
      - './src:/usr/src/project'
  celery:
    volumes:
      - './src:/usr/src/project'
```

Then `docker compose up -d`. Template changes apply on the next request when
`DEBUG=True`; static files need:

```bash
docker compose exec django python manage.py collectstatic --noinput
```

Python changes need `docker compose restart django celery`. Remove the override
and rebuild (`docker compose build django && docker compose up -d`) to test the
real image.

### Building behind a TLS-intercepting proxy

If `pip` fails during `docker compose build` with
`CERTIFICATE_VERIFY_FAILED`, supply the proxy's CA bundle as a BuildKit secret
(nothing is stored in the image). Copy the CA file inside the repository (for
example `.local/extra_ca.crt`, git-ignored) and add to your override:

```yaml
services:
  django:
    build:
      secrets:
        - extra_ca
secrets:
  extra_ca:
    file: ./.local/extra_ca.crt
```

## Tests

Unit tests for package extraction/validation and SLD generation (no database
needed):

```bash
docker compose exec -w /usr/src/project django python -m unittest geonode_project.tests.test_demo_package geonode_project.tests.test_smart_mapping -v
```

End-to-end permission and upload-security smoke test against the running
stack (creates and deletes temporary users; needs the demo import to have
run — the test fixture below is enough):

```bash
python3 scripts/security_smoke.py
```

Generate the **test fixture** (same layout as the demo package, 140 random
features, clearly labelled as a fixture, *not* AVDP data):

```bash
docker compose exec django python -m geonode_project.tests.make_test_package /tmp/avdp_test_fixture.zip
```

Screenshots at desktop and mobile widths (Playwright):

```bash
node scripts/screenshots.js /tmp/shots http://localhost
```

## Useful commands

| Purpose | Command |
|---|---|
| Django shell | `docker compose exec django python manage.py shell` |
| SQL console (application DB) | `docker compose exec db psql -U postgres geonode_project` |
| SQL console (vector data) | `docker compose exec db psql -U postgres geonode_project_data` |
| Celery log | `docker compose exec celery tail -f /var/log/celery_worker.log` |
| uWSGI/Django log | `docker compose exec django tail -f /var/log/geonode.log` |
| Re-sync GeoServer security rules | `docker compose exec django python manage.py sync_security_rules` |
| Rebuild thumbnails/links for a dataset | via the dataset page → *Edit* → *Edit info* |

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Sign in` returns 403 "CSRF cookie not set" from a script or a non-localhost HTTP URL | Session/CSRF cookies are `Secure` (production default). Browsers accept them on `http://localhost`. For plain-HTTP testing on another host set `SESSION_COOKIE_SECURE=False` and `CSRF_COOKIE_SECURE=False` in `.env` (development only). |
| WMS/WFS requests from scripts return errors even as admin | GeoServer authenticates map-client requests with the user's OAuth2 `access_token`, not the Django session. See `scripts/security_smoke.py` for how tests obtain one. |
| `django` stays `starting` for several minutes | First start runs ~420 migrations and collects static files. `docker compose logs -f django`. |
| GeoServer unhealthy | Check heap (`GEOSERVER_JAVA_OPTS`) and `docker compose logs geoserver`. It starts after Django is healthy. |
| Upload stuck "running" | Celery must be healthy: `docker compose ps celery`, `docker compose logs celery`. |
| Map thumbnails without basemap | Thumbnails fetch OpenStreetMap tiles server-side; offline servers produce thumbnails without background. |
| `settings.ACCOUNT_AUTHENTICATION_METHOD is deprecated` warnings | Emitted by django-allauth for GeoNode 5.1.1 settings; harmless. |
| Changed `COMPOSE_PROJECT_NAME` and data disappeared | Volume names are prefixed with it; switch it back. |

## Dev container (VS Code)

The upstream `.devcontainer/` configuration is kept unchanged; see
`.devcontainer/README.md`. It was not exercised for this project.
