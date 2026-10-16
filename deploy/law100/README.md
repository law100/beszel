# Law100 business overview — first version

Based on Beszel v0.21.0. The original upstream license and monitoring remain
unchanged. The added `/business` page uses the native React cards, theme, icons
and responsive navigation. Its first version is Chinese.

## Boundaries and provenance

- Read-only: no task controls, downloads, cloud scans, refresh-token operations,
  file mutations, or service-management endpoints.
- `/api/law100/overview` is GET-only and owner-only behind the existing Auth
  bridge. The loopback `/business` endpoint independently checks the same owner.
  Browser-supplied identity and bearer headers cannot grant access.
- Collection is offline and uses SQLite `mode=ro` + `query_only`; fields are
  explicitly projected. Provider credentials, share tokens, signed URLs and
  internal cloud file IDs are never included in the response.
- Capacity is the existing configured **2 TiB per Unicom account**, not a newly
  queried official provider allowance. Used space comes from Drive's latest
  successful inventory cache; its timestamp and stale/scanning state are shown.
- Library totals deduplicate physical target identifiers from confirmed import
  and share records. Subsequent direct cloud deletion is not live-reconciled.
- Task speed uses snapshot deltas only for fresh active tasks. No estimate is
  shown without enough data. Historical averages include pauses and waiting.
- Missing sections remain `null` and generate a warning, never fake zeroes.
- Backup is local only; this feature does not add off-server backups or alerts.

## Deployment

Existing prerequisites: official Hub on loopback 8090, Auth verifier 8091,
owner bridge configuration in `/etc/law100-dashboard/gate.json`, and HTTPS
Nginx site `law100-dashboard-https`. No credentials belong in this repository.

1. Back up the existing site, verifier and unit files with the existing private
   dashboard backup service. Record service PIDs/start times before deployment.
2. Build `internal/site` locally using the lockfile (`npm ci`, `npm run build`).
   Do not commit generated translation catalog line-reference changes. After
   catalogs are generated, `npm exec -- tsc -b` and `npm exec -- vite build`
   rebuild without repeating extraction. Archive the *contents* of `dist` as
   `/opt/law100-dashboard/business-ui.tar.gz` on the server.
3. Install `business_collect.py`, `auth_gate.py`, `backup.py`, `install_ui.py`
   under `/opt/law100-dashboard`. Install the business service/timer under
   `/etc/systemd/system`. Create `/var/lib/law100-dashboard-business` with
   owner `root:law100-beszel` and mode 0750; snapshots use 0640.
4. Reload systemd and run the collector once. It has no network namespace access,
   a 192 MiB ceiling, a 20-second deadline, and can write only its private state
   directory. Validate output and collection cost before enabling the timer.
5. Run `install_ui.py`. Public assets go under a versioned
   `/var/www/law100-dashboard/releases` directory, never the private deployment
   directory. Nginx serves only known SPA routes and protected hashed assets;
   native API/static routes still proxy to the unchanged official Hub.
6. The installer reloads Nginx, restarts **only the dashboard verifier**, and
   enables the 15-second timer. It does not restart Hub, Agent or business apps.
7. Verify owner access, anonymous 401, other-owner 403, POST 405, mobile/theme
   layout, all existing probes and unchanged business PIDs. Run the private
   backup again: it includes the custom UI and new collector/unit source files.

`install_ui.py` fills the native `BESZEL` frontend configuration. The root
`BASE_PATH` must be `/`, not an empty string: PocketBase otherwise resolves
requests relative to the current SPA route. The UI's upstream version must stay
aligned with the official Hub version. Rebase and test before upgrading either.

## Tests

Run `python -B -m unittest discover -s deploy/law100 -v`, plus frontend typecheck
and build. Tests use isolated temporary databases and do not contact production.

## Unified login/logout repair

The customized build sets `AUTH_MODE: "law100"`; other Beszel installations keep
their native authentication behavior. `UnifiedLogin` performs the trusted-header
auth refresh and provides an explicit Auth entry if bootstrap fails. It never
offers a separate local password form.

The explicit logout menu obtains the existing app-session CSRF token, POSTs to
`/_auth/logout`, waits for confirmed revocation, clears local Beszel auth, and
opens `/_auth/signed-out`. The landing page does not automatically sign back in.
Dashboard logout removes only that app session; central SSO, Drive and other app
sessions remain valid. Other clients keep their previous logout semantics.

Auth's form-action CSP is generated from the already registered app hosts. This
includes Dashboard without wildcard origins or changes to role/owner checks.
The internal login redirect URL-encodes and allowlists the requested Beszel page,
preserving deep links without redirecting back into auth/API/resource paths.

`deploy_auth_flow.py` applies the narrow Auth/Nginx/verifier changes with a private
pre-change SQLite/code backup. It restarts only Auth and the Dashboard verifier,
then reloads Nginx; business workers, Hub and Agent remain untouched. Upload the
audited `auth_gate.py` as `auth_gate.next.py` and `dashboard-flow.mjs` as
`dashboard-flow.next.mjs` under `/opt/law100-dashboard` before running it. Deploy
the new frontend via `install_ui.py` afterwards. The Auth helper is also required
when restoring the modified Auth server source; do not restore just one file.

Additional offline tests: `node --experimental-strip-types --test
deploy/law100/unified_auth.test.mjs` (Node 24). No production credentials needed.

## Rollback and recovery

For immediate UI rollback, restore the previous Nginx site and verifier from the
private predeployment backup, validate Nginx, reload it and restart only the
verifier. Disable the business timer. Hub and business services stay untouched.
For later UI-only updates, switch `current` to a known-good versioned release.
Keep `/opt/law100-dashboard/ui-current` pointing to the same release for backups.
Private backups contain `ui/`, deployment scripts, unit files and configuration;
restore UI files into a versioned public directory before restoring its symlink.
Never extract a backup archive directly over a running Hub or publish the archive.
