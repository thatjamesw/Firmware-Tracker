# Firmware Tracker

Static firmware-tracking site that deploys on GitHub Pages and syncs from official vendor sources.

## How it works

- Source of truth: `data/devices.json`
- Schema: `data/devices.schema.json` (validated before sync)
- Official sync: `scripts/fetch_firmware_details.py`
  - DJI: downloads pages and release-notes PDFs
  - Sony: official `support.d-imaging.sony.co.jp` firmware pages (model-code based)
  - Godox: official firmware listing pages
  - Apple: official support pages for iOS/macOS/watchOS/AirPods
  - Atomos: official product-support firmware sections (device article based)
  - Bambu: official wiki release-history pages
  - TP-Link: official support/download firmware pages
  - Static/manual entries for devices without stable public firmware feeds
- Generator: `scripts/generate_index.py`
- Generated browser assets:
  - `docs/devices/categories.js`
  - `docs/devices/index.js`
  - `docs/devices/config.js`
  - `docs/FIRMWARE_SUMMARY.md` (repo-friendly markdown snapshot)
- Frontend: `docs/index.html`

## Local usage

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -p 'test_*.py' -v
python scripts/smoke_test_frontend.py
node --test tests/frontend.test.js
python scripts/fetch_firmware_details.py
python scripts/generate_index.py
```

Then open `docs/index.html` in a browser.

Optional workflow linting:

```bash
.venv/bin/python -m pip install actionlint-py
.venv/bin/actionlint .github/workflows/update-and-deploy.yml
```

## Using the tracker

Search devices by name or category, select a category, or enable **Unseen releases
only**. Sort with the column buttons on desktop or **Sort by** on any screen.
Filters and sort order stay in place when releases are marked as seen.

**Unseen** means the latest release differs from the version last acknowledged in
this browser. It does not compare with firmware installed on your physical device.
The first visit establishes a baseline. **Mark all as seen** acknowledges the full
watchlist; **Mark as seen** in release history acknowledges one device.

**Sources checked** shows the vendor scan time, independently of the site's build
time. Devices without a successful check in more than three days show **Check
overdue**; devices with no recorded success show **Not checked yet**. A failed
source check is identified on its row even when a global issue banner is hidden.
Release history includes the exact last successful check and official download
link, with older releases collapsed below the latest release.

The history dialog supports keyboard navigation and Escape. On closing, focus
returns to the device's history button, or search if the row was filtered out.
Seen status is browser-local; clearing site storage resets it.

Browser regression checks (development only; the deployed site has no npm runtime):

```bash
npm ci
npx playwright install chromium
npm run test:browser
```

These check desktop and mobile filtering, sorting, source freshness, seen status,
keyboard focus, and overflow against a local static server. CI runs the same suite.

## Manage devices without editing JSON

Use **Manage devices on GitHub** in the site header, or open the repository's
[Manage Devices workflow](https://github.com/thatjamesw/Firmware-Tracker/actions/workflows/manage-devices.yml)
and choose **Run workflow**. The workflow must first be merged into `main` to appear.
You need repository access to run it.

For a typical DJI device, fill in just:

- **Action:** add
- **Name:** the official model name, e.g. `Osmo Pocket 4P`
- **Category:** `Cameras` or `Drones`
- **Source URL:** the official product download page, e.g. `https://www.dji.com/global/downloads/products/osmo-pocket-4p`

Leave **Source** on `auto`. The ID is generated from the name. Pocket 4P is already
included in this repository; use `update` and ID `osmo_pocket_4p` for future changes.

The workflow checks the source, previews detected releases in its run summary,
validates the updated data, regenerates the site, and opens a pull request.
Review and merge that PR to publish the change. **Preview only** runs the same
checks without opening a PR. No GitHub credentials are stored in the website.
A failed source check leaves repository data unchanged and explains the failure
in the workflow log. Empty results require an explicit **allow** policy for new devices.

For **update** or **remove**, enter the existing device ID shown in the device's
**Release history** details. Blank update fields keep their current values. Changing the
source URL replaces its old fallback URLs; advanced fallback configuration remains
available in JSON. Updating retains release history and rejects detected downgrades.
Removing a device removes its tracking configuration, history, and source-health entry.
Category titles can be existing titles or a new title. Empty categories may remain.
Rerun the form if a pending PR needs refreshing after another device PR merges.

Some vendors need a model or variant to avoid matching the wrong hardware:

| Vendor | Source URL | Model field | Variant field |
| --- | --- | --- | --- |
| DJI | Product downloads page | Optional exact source model name | — |
| Sony | Official support page | Model code, e.g. `ILCE-1M2` (or `mdl` in URL) | — |
| Godox | Firmware listing page | Exact listing title/model, e.g. `V860IIS Firmware` | — |
| Apple | Support article | AirPods model, if applicable | `ios`, `macos`, `watchos`, or `airpods` |
| Atomos | Product support page | — | Article ID, e.g. `NinjaVArticle` |
| Bambu | Wiki release-history page | — | Series, e.g. `P1` |
| TP-Link | Download page | Model, e.g. `Deco BE65` | Hardware version, e.g. `V2` |
| Manual | Official support page; select `static` | — | — |

Manual entries use **Manual version** (a version or `App-managed`) and optional
**Manual note**. Unsupported vendors require a new parser or a manual entry;
auto detection does not guess a firmware feed from an arbitrary product name.

The workflow reuses `FW_BOT_TOKEN` from the daily-sync setup below. Using that token
lets the generated PR trigger CI. If it falls back to `GITHUB_TOKEN`, GitHub may
suppress those follow-up workflows; use the bot token for the complete PR/CI flow.
Device PRs require review/merge and do not enable auto-merge themselves.

For local use, put those same fields in a JSON file and run:

```bash
python scripts/manage_devices.py --form-json device-form.json --dry-run
python scripts/manage_devices.py --form-json device-form.json
python scripts/generate_index.py
```

`data/devices.json` remains the source of truth. Advanced source fields include
`fallback_source`, `fallback_sources`, `allow_empty`, `treat_404_as_empty`, and
`allow_regression`. The schema validates required vendor fields, including fallback
sources. Use `allow_regression` only for an intentional correction.

## Scan performance and parser checks

```bash
python scripts/fetch_firmware_details.py --dry-run --metrics-file /tmp/scan-metrics.json
node --test tests/frontend.test.js
```

Python 3.12+ and Node 22+ are used for checks. Each scan shares downloads by URL,
including in-flight requests, and allows two requests per host. Cache data lives
only for the current process/scan; there is no persistent HTTP cache.
The fetcher retries temporary HTTP errors (408, 429, 500, 502, 503, 504) and network
failures, honors `Retry-After`, and uses jittered backoff. Permanent errors such as
403/404 are not retried. The workflow no longer reruns every healthy source after
one failure.

`--device-budget` defaults to 120 seconds across network waits, retries, and
fallbacks for a device. `--timeout` is the individual socket timeout. The network
budget is cooperative, not a hard cancellation of PDF parsing or an in-progress
socket read. Responses are limited to 32 MiB. Scan metrics include request count,
bytes, shared-cache hits, total elapsed time, and per-device fetch/parse time.
Network seconds are summed across concurrent requests and can exceed wall time.
The scheduled workflow uploads `scan-metrics.json` as a run artifact.

DJI, Apple, and Atomos use structural HTML parsing. DJI also recognizes release-note
filenames if layout classes change, resolves relative PDF links, tries another
PDF after extraction failures, and preserves wrapped release-note bullets.
The real Pocket 4P PDF fixture checks actual pypdf extraction offline.
Atomos upload-month paths are no longer presented as exact release dates. An
explicit unknown date stays unknown when historical metadata is merged.

## GitHub Pages setup

1. Push this repo to GitHub.
2. In GitHub repository settings:
   - Pages -> Source: `GitHub Actions`
3. Run workflow `Update and Deploy Firmware Tracker` once (manual dispatch).
4. The site deploys from the generated `docs/` artifact.
5. The sync workflow tries early daily slots at 05:07, 06:17, and 07:27 Europe/Helsinki. A gate job allows only one successful scheduled sync per Finland calendar day, while manual dispatch always runs.
6. CI runs parser/schema tests and a frontend smoke test before generated changes are merged.

## Automated Testing (No Local Setup)

- `CI` workflow (`.github/workflows/ci.yml`) runs on every pull request and push to `main`:
  - installs dependencies
  - runs unit/parser/schema tests
  - runs `scripts/generate_index.py` as a build smoke test
  - runs `scripts/smoke_test_frontend.py` to verify generated browser assets and script wiring
- `Update and Deploy Firmware Tracker` workflow (`.github/workflows/update-and-deploy.yml`) runs daily + manual:
  - checks whether a scheduled sync is already active or has already succeeded today in Europe/Helsinki
  - re-runs tests
  - fetches official firmware data with regression guardrails enabled
  - regenerates browser assets + markdown summary
  - deploys generated `docs/` as a Pages artifact (no push back to protected `main`)
  - opens/updates an automation PR for generated file changes and enables auto-merge
  - on pushes to `main`, validates and deploys the merged data without another vendor scan or automation PR

### Automated Sync PR Setup (One-time)

To run fully hands-off daily:

1. Add these actions to your repository Actions allowlist:
   - `peter-evans/create-pull-request@v8`
   - `peter-evans/enable-pull-request-automerge@v3`
2. Add repository secret `FW_BOT_TOKEN` (fine-grained PAT):
   - Repository permissions: `Contents: Read and write`, `Pull requests: Read and write`
3. Branch protection for `main`:
   - Keep PR required and status checks required.
   - Set required approvals to `0` for full automation.

Recommended GitHub branch protection:

- Require pull request before merging to `main`
- Require status check: `CI / test`
- Disable direct pushes to `main` (except admins if you want an emergency path)

## Notes

- Includes DJI drones, Sony cameras, lighting devices, Apple software platforms, Atomos recorders, Bambu printers, and TP-Link network devices by default.
- DJI Mini 5 Pro currently uses:
  - primary: `https://www.dji.com/fi/mini-5-pro/downloads`
  - fallbacks: regional/product download pages listed in `data/devices.json`
- `Godox V860II (Sony)` is mapped to `V860IIS` firmware feed.
- `Amaran 300c` is set as app-managed (`Sidus Link`) via static/manual entry.
- `Dell U4025QW` remains static/manual due anti-bot protections on official support pages.
- Sync runs in parallel with retry/backoff and records source health each run.
  - Default: app continues to serve last known good data even if a source fails.
  - Transient network failures (for example temporary DNS outages in CI) are tracked separately and do not raise persistent UI source-issue banners.
  - Per-device `allow_empty: true` can be used for feeds where no firmware is currently published; this avoids false-positive source alerts.
  - DJI stale `404` release-note PDF links are tolerated as empty results (last known good data is retained).
  - Release guardrail prevents replacing current data with an older "latest" release date unless `allow_regression: true` is set on that source.
  - Version-aware guardrails prioritize new firmware versions over stale vendor dates, reject apparent downgrades, and preserve previous release metadata when a parser can only see the latest row.
  - Parsers now extract ranked release candidates from official evidence (tables, visible text, links, filenames, and PDFs) before a shared resolver chooses the best firmware value.
  - Vendor HTML parsers use shared text/date/link helpers and tolerate common markup changes in Apple, Sony, Godox, Atomos, Bambu, and TP-Link pages.
  - Per-device and per-vendor health is tracked (`consecutive_failures`, `last_success_utc`, `last_error_type`) for better diagnostics.
  - Strict mode: `python scripts/fetch_firmware_details.py --fail-on-regression` is used by the scheduled deploy workflow.
- UI is single-table for all devices and includes:
  - A firmware status summary that changes when unseen firmware is detected
  - Last generated timestamp
  - Source issue banner when a vendor feed is failing (for example DJI parsing errors)
  - New-firmware status and row highlights based on what your browser has previously seen (`Mark as Seen` to clear)
  - `Release history` details include an `Open official download page` link (landing page, not direct binary URL)
- Devices without configured sources are skipped.
