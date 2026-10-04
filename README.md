# Learnfolio

Create one PDF from Microsoft Learn learning paths and modules. The interface is
plain HTML, CSS, and JavaScript. The website uses Onest from Google Fonts. PDFs offer Times New Roman (default),
Arial, and Oswald; Oswald is embedded when selected. PDF covers contain only the document title. Every PDF page has a thin, muted
blue-gray border inset 7 mm from the edge, clear of the text and footer.

## Structure

```text
frontend/
  index.html
  assets/             Styles, JavaScript, favicon, Oswald font and its license
backend/
  app.py              HTTP API and local website server
  jobs.py             Export validation and background jobs
  exporter.py         Microsoft Learn extraction and PDF generation
  preview.py          PDF page rendering
  requirements.txt    Required Python dependencies
  Dockerfile          Backend deployment
  run.bat             Windows setup and launcher
README.md
```

The root also contains Git/Docker ignore rules. No build step, frontend packages,
generated documents, test artifacts, or virtual environment are shipped.

## Run on Windows

Install Python 3.10 or later with the Python launcher, then double-click
**backend/run.bat**. On first run it installs the required packages and Chromium.
Open **http://127.0.0.1:8501**. Press Ctrl+C after exports finish to stop.
Use `backend\run.bat 8502` to choose another port.

Dependencies are installed outside the project in
`%LOCALAPPDATA%\Learnfolio\venv`. Exports are created only when requested, under
`%LOCALAPPDATA%\Learnfolio\data\exports`. Deleting the project does not delete
that runtime folder. To update packages after changing `requirements.txt`:

```powershell
& "$env:LOCALAPPDATA\Learnfolio\venv\Scripts\python.exe" -m pip install -r backend/requirements.txt
& "$env:LOCALAPPDATA\Learnfolio\venv\Scripts\python.exe" -m playwright install --no-shell chromium
```

## Run on Linux

From the project root:

```sh
python3 -m venv "$HOME/.local/share/learnfolio/venv"
"$HOME/.local/share/learnfolio/venv/bin/python" -m pip install -r backend/requirements.txt
"$HOME/.local/share/learnfolio/venv/bin/python" -m playwright install --with-deps --no-shell chromium
"$HOME/.local/share/learnfolio/venv/bin/python" -B backend/app.py
```

Exports default to `$XDG_DATA_HOME/learnfolio/data`, or
`~/.local/share/learnfolio/data` when `XDG_DATA_HOME` is unset. Set `DATA_DIR` to
use a different directory. Local mode binds only to 127.0.0.1 and needs no key.

## Deploy: Vercel frontend + Render backend

Repository: https://github.com/smartswagvivek/microsoft-paths-to-pdf

Deploy the frontend first to get the exact origin needed by the backend.
The website initially opens without a backend connection; this is expected.

### 1. Frontend on Vercel

1. Sign in to https://vercel.com and choose **Add New > Project**.
2. Import `smartswagvivek/microsoft-paths-to-pdf` from GitHub. Grant Vercel
   access to this repository if it is not listed.
3. Use these settings:

| Setting | Value |
| --- | --- |
| Production branch | `main` |
| Framework Preset | `Other` |
| Root Directory | `frontend` |
| Build Command | Override with an empty value (no build) |
| Output Directory | `.` |
| Install Command | Override with an empty value (no packages to install) |
| Environment variables | None required |

4. Deploy and copy the stable **production** URL from the project Domains page,
   such as `https://your-project.vercel.app`. Do not use a commit-specific preview
   URL in the backend settings.

Only `frontend/` is published. Do not select the repository root or `backend/`.
There is no npm install or npm build command for this project.

### 2. Backend on Render

1. Generate a private access key locally:

```powershell
py -3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Keep the resulting value private. It is your Learnfolio key, not a Microsoft,
OpenAI, or Render API key.

2. Sign in to https://dashboard.render.com, choose **New > Web Service**, connect
   GitHub, and select this repository.
3. Use these settings:

| Setting | Value |
| --- | --- |
| Name | Any available name, for example `learnfolio-api` |
| Branch | `main` |
| Language / Runtime | `Docker` |
| Root Directory | Leave blank (repository root) |
| Dockerfile Path | `backend/Dockerfile` |
| Docker Build Context | `.` (repository root) |
| Docker Command | Leave blank; use the Dockerfile CMD |
| Health Check Path | `/api/health` |
| Instance count | `1` |

The Docker build needs both `backend/` and `frontend/`, because the PDF renderer
uses the bundled Oswald font. **Do not set Render's Root Directory to `backend`.**
The Dockerfile installs Python dependencies, Chromium, and its Linux libraries.
No separate build or start command is needed.

4. Add these environment variables:

| Variable | Value |
| --- | --- |
| `API_KEY` | The private random key generated above (at least 32 characters) |
| `ALLOWED_ORIGINS` | Your exact Vercel production origin, e.g. `https://your-project.vercel.app` |
| `HOST` | `0.0.0.0` |
| `PORT` | `10000` |
| `DATA_DIR` | `/data` |

`ALLOWED_ORIGINS` must have no path or trailing slash. Separate additional exact
origins with commas. Wildcards such as `https://*.vercel.app` are not supported.
No secret belongs in the frontend or repository.

5. Choose an **always-on paid instance** if the one-hour cleanup must run on
   schedule. Free services sleep after idle periods: background cleanup cannot
   run while sleeping, and opening the app can require a cold start. This service
   launches Chromium; if Render reports out-of-memory exits, increase its memory.
6. A persistent disk is **not required** for this temporary library. The default
   ephemeral `/data` directory loses exports on restart/redeploy (possibly before
   their one-hour expiry). Avoid provider backups if you require strict deletion
   of all stored copies. Run only one backend instance; there is one shared library
   and one active export at a time.
7. Click **Deploy Web Service**. Wait for the build and health check to succeed,
   then copy its HTTPS URL, for example `https://your-api.onrender.com`.
8. Open `https://your-api.onrender.com/api/health`. Expect:

```json
{"app":"learnfolio","status":"ok"}
```

### 3. Connect the two deployments

1. Open the Vercel website and expand **Connection settings**.
2. Enter the Render HTTPS URL (origin only) in **Backend URL**.
3. Enter the same `API_KEY` you configured on Render in **Access key**.
4. Click **Connect**. You should see **Connected** and an enabled export button.
5. Export a Microsoft Learn module, verify the preview and PDF download, and check
   the library's automatic-deletion countdown.

The backend URL is saved in local storage. The key stays in session storage for
that browser tab and is sent in an Authorization header. Disconnect clears it.
Everyone who has this shared key can access the same temporary library.

To prefill the backend URL for visitors, edit `frontend/assets/config.js`:

```javascript
window.LEARNFOLIO_CONFIG = { apiBase: "https://your-api.onrender.com" };
```

Commit and push that change; Vercel redeploys it. **Never put the access key in this
file.** Vercel environment variables do not automatically populate this plain
static JavaScript file. Existing saved connection settings override its default.

### Troubleshooting and updates

- **Found app.py but no top-level app:** Vercel is detecting the backend as Flask.
  Set Vercel's Root Directory to `frontend` and Framework Preset to `Other`, then
  redeploy the latest commit. The included `frontend/vercel.json` explicitly
  configures static hosting. The Python backend belongs on Render using Docker.
- **Vercel 404:** confirm Root Directory is `frontend`, Framework is `Other`,
  Output Directory is `.`, and build/install commands are empty.
- **Render COPY/build errors:** keep Root Directory blank, Dockerfile Path
  `backend/Dockerfile`, and Docker Build Context `.`.
- **Cannot connect / CORS:** match `ALLOWED_ORIGINS` to the browser's exact origin,
  including HTTPS. Save Render environment changes and let the service redeploy.
- **401:** the browser's access key must match Render's `API_KEY`.
- **Sleeping backend:** open the health URL, wait until it responds, then reconnect.
  Use an always-on instance for reliable background jobs and timed deletion.
- **Memory errors:** increase the backend instance's memory; Chromium needs more
  than a lightweight API server.
- **PDF font differs on Linux:** Times New Roman and Arial use Liberation Serif
  and Liberation Sans fallbacks if the Microsoft fonts are unavailable.
- **Custom domain or preview URL:** explicitly add its origin to `ALLOWED_ORIGINS`.
- Push future updates to `main`; enable automatic deployments in both providers.
  Avoid redeploying while an export is running.

The local app and Docker configuration have been prepared, but successful cloud
builds and a live export must still be verified after your deployments complete.

Provider documentation: [Vercel static build configuration](https://vercel.com/docs/builds/configure-a-build),
[Render Docker services](https://render.com/docs/docker),
[Render free-service limitations](https://render.com/docs/free).

## One-hour library retention

Completed and failed exports expire **one hour after the job finishes**. Opening,
previewing, downloading, or restarting the server does not extend that deadline.
The entire export folder is deleted: PDF, HTML, report, settings, logs, thumbnails,
and saved job state. The library entry and in-memory data are removed too. The
website shows the remaining time and clears expired previews and cached file URLs.
No lesson content is stored in local storage.

A background cleanup worker runs even with no website open. Expired API requests
are denied immediately; locked files are retried automatically. On startup, old
exports and abandoned export folders are cleaned up. Legacy/interrupted jobs use
their original timestamps, without starting a fresh one-hour period. Active
exports finish before their retention period begins.

The backend must be running to physically delete files. If it is stopped or the
machine is asleep, overdue files are removed when it starts/resumes. Files you
have downloaded or opened in a separate PDF viewer are outside the library and
cannot be remotely erased. Hosting-provider backups are outside this cleanup.

## Using Learnfolio

Paste public learning-path or module URLs. Choose a title, paper size, text size,
spacing, typeface, and image settings. PDF lesson paragraphs and list text are
justified, with left-aligned final lines. Headings, tables, source links, and code
keep their appropriate alignment. The website interface uses Onest; this does not affect PDF fonts.
On Linux hosts without Times New Roman or Arial, the renderer uses Liberation
Serif or Liberation Sans as compatible fallbacks.
Progress, refresh recovery, page previews, and PDF/HTML/report downloads are
available through the backend. Closing the tab does not cancel an export.

Failed lessons prevent PDF creation unless partial export is explicitly enabled.
Source links and export notes are retained. Interactive labs, videos, and
sign-in-only material remain online. If connection fails, check the backend URL,
access key, and exact allowed website origin.

Oswald is distributed under the SIL Open Font License; see
`frontend/assets/fonts/OFL.txt`. Font source:
https://github.com/google/fonts/tree/main/ofl/oswald
