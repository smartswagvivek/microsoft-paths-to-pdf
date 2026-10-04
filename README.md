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
  api/gateway.mjs     Vercel server function for automatic private backend access
  vercel.json          Vercel deployment settings
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

The frontend connects automatically through a small Vercel server function.
Visitors do not enter a backend URL or access key. Backend credentials are private
Vercel environment variables; never put them in client-side JavaScript.

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
| Environment variables | `BACKEND_API_KEY` (same value as Render `API_KEY`); optional `BACKEND_URL` |

4. Deploy and copy the stable **production** URL from the project Domains page,
   such as `https://your-project.vercel.app`. Do not use a commit-specific preview
   URL in the backend settings.

Only `frontend/` is deployed. Its HTML/CSS/JavaScript stays static; `api/gateway.mjs`
runs server-side on Vercel using Node built-ins and no third-party packages.
Do not select the repository root or `backend/`. No npm install/build is required.
The default backend URL is `https://microsoft-paths-to-pdf.onrender.com`.
If you deploy elsewhere, set `BACKEND_URL` to its HTTPS origin on Vercel.

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
   of all stored copies. Run only one backend instance; libraries are isolated per
   visitor, with one active export across the service at a time.
7. Click **Deploy Web Service**. Wait for the build and health check to succeed,
   then copy its HTTPS URL, for example `https://your-api.onrender.com`.
8. Open `https://your-api.onrender.com/api/health`. Expect:

```json
{"app":"learnfolio","status":"ok"}
```

### 3. Enable automatic connection (one-time owner setup)

1. On Render, set **API_KEY** to a random secret of at least 32 characters.
2. In Vercel **Project > Settings > Environment Variables**, set
   **BACKEND_API_KEY** to that exact same value. Enable it for Production (and
   Preview only if you intend preview deployments to use this backend).
3. Optionally set **BACKEND_URL** on Vercel. It already defaults to
   `https://microsoft-paths-to-pdf.onrender.com`.
4. Deploy the latest backend on Render, then redeploy the frontend on Vercel so
   the function receives the environment variables.
5. Open the website. It connects automatically and shows **Ready to export**.
   Visitors can paste a Microsoft Learn URL immediately, without setup or login.

The access key never reaches visitors. The Vercel function forwards only allowed
export endpoints, streams downloads, and assigns a signed HttpOnly session cookie
that expires after one hour of inactivity. The backend isolates each visitor's
library by this session, including previews, status, and downloads. Losing the
cookie means losing access to that temporary library; it is still deleted on time.
The existing one-hour export retention and single active worker remain in force.
Anyone can start exports through the public site; monitor hosting usage accordingly.

For local development, `backend/run.bat` still connects directly on localhost,
with no Vercel variables needed. There is no connection form and no access key in
browser storage. The interface retries automatically if Render is waking up.

### Troubleshooting and updates

- **Found app.py but no top-level app:** Vercel is detecting the backend as Flask.
  Set Vercel's Root Directory to `frontend` and Framework Preset to `Other`, then
  redeploy the latest commit. The included `frontend/vercel.json` explicitly
  configures static hosting. The Python backend belongs on Render using Docker.
- **Vercel 404:** confirm Root Directory is `frontend`, Framework is `Other`,
  Output Directory is `.`, and build/install commands are empty.
- **Render COPY/build errors:** keep Root Directory blank, Dockerfile Path
  `backend/Dockerfile`, and Docker Build Context `.`.
- **Service configuration error:** Vercel `BACKEND_API_KEY` must match Render
  `API_KEY`. Redeploy Vercel after changing environment variables. The gateway
  calls Render server-to-server, so visitors do not need direct CORS access.
- **Service updating:** deploy the latest Render commit before the frontend; old
  backends without per-visitor isolation are intentionally refused.
- **Sleeping backend:** open the health URL, wait until it responds; the website reconnects automatically.
  Use an always-on instance for reliable background jobs and timed deletion.
- **Memory errors:** increase the backend instance's memory; Chromium needs more
  than a lightweight API server.
- **PDF font differs on Linux:** Times New Roman and Arial use Liberation Serif
  and Liberation Sans fallbacks if the Microsoft fonts are unavailable.
- **Custom domain or preview URL:** explicitly add its origin to `ALLOWED_ORIGINS`.
- Push future updates to `main`; enable automatic deployments in both providers.
  Avoid redeploying while an export is running.

The local app, gateway, and Docker configuration have been prepared, but successful cloud
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
sign-in-only material remain online. If connection fails, check the backend URL and
private Vercel/Render environment settings.

Oswald is distributed under the SIL Open Font License; see
`frontend/assets/fonts/OFL.txt`. Font source:
https://github.com/google/fonts/tree/main/ofl/oswald
