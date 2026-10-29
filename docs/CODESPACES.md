# Temporary demos in GitHub Codespaces

A codespace can run the complete portal for a few hours, for example to show
stakeholders the system. It is **not** a hosting option: codespaces stop when
idle, are billed per hour, and are tied to one GitHub account.

## Requirements

- A GitHub account with Codespaces access to this repository.
- The **4-core / 16 GB RAM / 32 GB disk** machine type (the configuration asks
  for it; smaller machines run out of memory). Personal accounts include a
  monthly free allowance of core-hours; a 4-core machine uses it four times
  as fast as a 1-core one. Organisation-owned codespaces are billed to the
  organisation if it allows them.

## Start a demo

1. On GitHub: **Code → Codespaces → … → New with options**.
2. Branch: the one to demonstrate. Dev container configuration:
   **AVDP GIS Portal demo**. Machine type: **4-core, 16 GB**.
3. Create. The first start builds the images and starts the stack, which
   takes roughly 10–20 minutes; progress is shown in the creation log
   (`scripts/codespace-demo.sh all`).
4. When it finishes, the terminal prints the portal URL, e.g.
   `https://<codespace-name>-80.app.github.dev/`, and the **Ports** panel shows
   port 80 as *AVDP GIS Portal*.
5. Sign in as `admin`. The password is generated for this codespace; read it
   in the codespace terminal:

   ```bash
   grep '^ADMIN_PASSWORD=' .env
   ```

To see the URL and sign-in hint again:

```bash
bash scripts/codespace-demo.sh info
```

## Demo data

If `data/demo/AVDP_Synthetic_GIS_Sample_Package.zip` exists in the codespace,
it is imported. Because that folder is git-ignored, upload the zip into
`data/demo/` (drag it into the VS Code explorer) and run:

```bash
rm -f .local/demo-seeded && bash scripts/codespace-demo.sh seed
```

Without the package, the generated **test fixture** is loaded instead (seven
layers, 140 random features, all labelled synthetic). It shows how the portal
works; it is not AVDP data.

## Showing it to other people

Port 80 is **private** by default: only you (signed in to GitHub) can open it.
To let others view the demo, right-click port 80 in the **Ports** panel →
**Port Visibility → Public**. Anyone with the URL can then reach the portal
(GeoNode's own permissions still apply: demo layers are private unless
imported with `--public`, and visitors must sign in to see them). Set it back
to Private afterwards. Create accounts for viewers in the admin pages rather
than sharing the admin password.

Do not load real, sensitive data into a demo codespace.

## Stop, resume, delete

- The codespace stops after its idle timeout (30 minutes by default, set in
  your GitHub Codespaces settings). Data in the codespace is kept.
- Re-opening it runs `docker compose up -d`; the portal is back after a few
  minutes.
- Delete the codespace when the demo is over to stop storage charges.

## Verification status

This configuration has **not yet been run in an actual GitHub Codespace**. It
was rehearsed end-to-end with an equivalent local setup: a fresh checkout and
fresh volumes, `scripts/codespace-demo.sh all` with a Codespaces-style host
name, and an HTTPS-terminating proxy in front of nginx that forwards plain HTTP
(as GitHub does). In that rehearsal the stack built and became healthy, demo
data loaded (140 features), sign-in, the homepage and the map (WMS tiles,
legend) worked over HTTPS with no mixed-content requests, the 61-check
security suite passed, a stop/start resumed without re-seeding, and re-running
`setup` for a new host name kept the existing secrets. The first real
codespace run should be watched once.

## How it works

- `.devcontainer/demo/devcontainer.json` uses Docker-in-Docker, so the
  repository's normal `docker-compose.yml` runs unchanged inside the codespace.
- `scripts/codespace-demo.sh setup` writes `.env` with random secrets and
  `SITEURL=https://<codespace>-80.<domain>/`. GitHub terminates HTTPS and
  forwards plain HTTP to nginx on port 80. `PublicSchemeMiddleware`
  (`src/geonode_project/middleware.py`) makes Django build `https://` URLs
  when `SITEURL` is HTTPS, and the settings trust the public HTTPS origin for
  Django's CSRF check.
- `DEBUG=False`, so error pages do not reveal internals.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Creation log stops at "Waiting for all services…" for a long time | Normal on first start (~10 min). If it times out: `docker compose ps` and `docker compose logs django geoserver`. |
| Out-of-memory / containers restarting | The codespace is not on the 16 GB machine type. Change it under **Codespaces → Change machine type**. |
| Sign-in shows "Forbidden (403) CSRF" | `.env` was created for a different URL (e.g. the codespace was renamed). Run `bash scripts/codespace-demo.sh setup && docker compose up -d`. |
| Port 80 not listed | Run `docker compose up -d`, then **Ports → Forward a port → 80**. |
