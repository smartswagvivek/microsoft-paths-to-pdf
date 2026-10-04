"use strict";
const $ = id => document.getElementById(id);
const sample = "https://learn.microsoft.com/en-us/training/paths/microsoft-azure-fundamentals-describe-cloud-concepts/";
let selectedJob = null, pollTimer = null, stateTimer = null, activeJob = null;
let previewJob = null, previewPage = 1, previewPages = 0;
let libraryHistory = [], expiryTimer = null, selectedExpiry = null, serverOffset = 0;
function serverNow() { return Date.now() + serverOffset; }

function stored(area, key, value) {
  try {
    if (value === undefined) return window[area].getItem(key);
    if (value === null) window[area].removeItem(key);
    else window[area].setItem(key, value);
  } catch { /* The app still works when browser storage is unavailable. */ }
  return null;
}
const localHost = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
const apiBase = location.origin;
let connected = false;
let previewObject = null, previewRequest = 0;
const fileObjects = new Map();
function historyKey() { return `learnfolio-job:${apiBase}`; }
// Remove selection IDs left by older versions; lesson content is never stored here.
try {
  for (const key of Object.keys(localStorage)) {
    if (key.startsWith("learnfolio-job:") || key === "learn-pdf-job" || key === "learnfolio-backend") localStorage.removeItem(key);
  }
  for (const key of Object.keys(sessionStorage)) {
    if (key.startsWith("learnfolio-key:")) sessionStorage.removeItem(key);
  }
} catch { /* Storage can be disabled. */ }
function clearSelection() {
  clearTimeout(pollTimer);
  selectedJob = null; selectedExpiry = null;
  stored("sessionStorage", historyKey(), null);
  resetPreview();
  $("job-panel").hidden = true;
  for (const id of ["job-message", "execution-log", "job-error", "metrics", "downloads", "warnings"]) $(id).replaceChildren();
}
function expireLibrary() {
  clearTimeout(expiryTimer);
  const now = serverNow();
  libraryHistory = libraryHistory.filter(job => !job.expires_at || Date.parse(job.expires_at) > now);
  if (selectedExpiry && Date.parse(selectedExpiry) <= now) {
    clearSelection();
    showError("This export was automatically deleted after 1 hour. Create a new export to continue.");
  }
  renderHistory(libraryHistory);
  const deadlines = libraryHistory.filter(job => job.expires_at).map(job => Date.parse(job.expires_at));
  if (selectedExpiry) deadlines.push(Date.parse(selectedExpiry));
  if (deadlines.length) expiryTimer = setTimeout(expireLibrary, Math.max(1, Math.min(30000, Math.min(...deadlines) - now)));
}
function assertAvailable(id) {
  if (id !== selectedJob || (selectedExpiry && Date.parse(selectedExpiry) <= serverNow())) {
    expireLibrary();
    throw new Error("This export expired or is no longer selected.");
  }
}
async function request(path, options = {}) {
  let response;
  try {
    const url = localHost ? path : `/api/gateway?path=${encodeURIComponent(path)}`;
    response = await fetch(url, {
      ...options, signal: AbortSignal.timeout(45000),
      headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers }
    });
  } catch {
    throw new Error("The export service is waking up or temporarily unavailable. Retrying shortly.");
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const error = new Error(data.error || `Export request failed (${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return response;
}
async function api(path, options = {}) {
  const response = await request(path, options);
  if (!response.headers.get("Content-Type")?.includes("application/json")) {
    throw new Error("The export service is temporarily unavailable.");
  }
  return response.json();
}
async function fileUrl(id, type) {
  assertAvailable(id);
  const cacheKey = `${id}/${type}`;
  if (!fileObjects.has(cacheKey)) {
    const response = await request(`/files/${id}/${type}`);
    const blob = await response.blob();
    assertAvailable(id);
    fileObjects.set(cacheKey, URL.createObjectURL(blob));
  }
  return fileObjects.get(cacheKey);
}
async function downloadFile(event, id, type) {
  event.preventDefault();
  const link = event.currentTarget;
  if (link.getAttribute("aria-busy") === "true") return;
  link.setAttribute("aria-busy", "true");
  try {
    const url = await fileUrl(id, type);
    const download = document.createElement("a");
    download.href = url;
    download.download = {pdf:"combined_lessons.pdf", html:"combined_lessons.html", report:"extraction_report.json"}[type];
    document.body.append(download); download.click(); download.remove();
  } catch (error) { showError(error.message); }
  finally { link.removeAttribute("aria-busy"); }
}
$("open-pdf").addEventListener("click", async event => {
  event.preventDefault();
  const job = previewJob;
  if (!job) return;
  const viewer = window.open("about:blank", "_blank");
  if (viewer) viewer.opener = null;
  try {
    const url = await fileUrl(job, "pdf");
    if (viewer) viewer.location.replace(url);
    else showError("Allow pop-ups to open the PDF, or use Download combined PDF.");
  } catch (error) { if (viewer) viewer.close(); showError(error.message); }
});
function showError(message) { $("form-error").textContent = message; $("form-error").hidden = !message; }
function setBusy(busy) {
  $("form-fields").disabled = busy;
  $("create-button").disabled = busy;
  $("create-button").firstElementChild.textContent = busy ? "Creating your study copy…" : "Create my PDF";
}
function updatePreview() {
  const title = $("title").value.trim();
  $("preview-title").style.fontFamily = $("font").value;
  $("preview-title").textContent = title || "Your document title";
  $("paper-preview").classList.toggle("letter", $("paper").value === "Letter");
  if (!$("paper-preview").hidden) $("preview-settings").textContent = `${$("paper").value} · ${$("font").value} · ${$("font-size").value} pt`;
}
function resetPreview() {
  previewJob = null; previewPages = 0; previewPage = 1; previewRequest++;
  if (previewObject) URL.revokeObjectURL(previewObject);
  previewObject = null;
  $("pdf-page").removeAttribute("src");
  for (const url of fileObjects.values()) URL.revokeObjectURL(url);
  fileObjects.clear();
  $("pdf-preview").hidden = true;
  $("pdf-page").hidden = true;
  $("paper-preview").hidden = false;
  $("preview-stage").classList.remove("has-pdf");
  $("preview-heading").textContent = "A look inside";
  $("preview-tag").textContent = "COVER PREVIEW";
  $("preview-footer-note").textContent = "Made for reading";
  updatePreview();
}
async function showPreviewPage(number) {
  previewPage = Math.max(1, Math.min(previewPages, number));
  const current = ++previewRequest;
  $("previous-page").disabled = previewPage <= 1;
  $("next-page").disabled = previewPage >= previewPages;
  $("page-counter").textContent = `Page ${previewPage} of ${previewPages}`;
  $("pdf-page").alt = `Generated PDF, page ${previewPage} of ${previewPages}`;
  $("pdf-page").hidden = true;
  $("preview-error").hidden = true;
  try {
    const response = await request(`/preview/${previewJob}/${previewPage}`);
    const blob = await response.blob();
    if (current !== previewRequest) return;
    if (previewObject) URL.revokeObjectURL(previewObject);
    previewObject = URL.createObjectURL(blob);
    $("pdf-page").src = previewObject;
    $("pdf-page").hidden = false;
  } catch (error) {
    if (current !== previewRequest) return;
    $("preview-error").textContent = error.message;
    $("preview-error").hidden = false;
  }
}
async function loadPreview(job) {
  if (previewJob === job.id) return;
  previewJob = job.id;
  $("page-counter").textContent = "Loading preview…";
  $("previous-page").disabled = true; $("next-page").disabled = true;
  $("preview-error").hidden = true;
  $("open-pdf").href = "#";
  try {
    const info = await api(`/preview/${job.id}/info`);
    if (previewJob !== job.id) return;
    previewPages = info.pages; showPreviewPage(1);
  } catch (error) {
    if (previewJob !== job.id) return;
    $("preview-error").textContent = "Preview unavailable. You can still open or download the PDF.";
    $("preview-error").hidden = false;
  }
}
$("previous-page").addEventListener("click", () => showPreviewPage(previewPage - 1));
$("next-page").addEventListener("click", () => showPreviewPage(previewPage + 1));
$("pdf-page").addEventListener("error", () => {
  $("pdf-page").hidden = true; $("preview-error").hidden = false;
  $("preview-error").textContent = "This page could not be displayed. Open the PDF to continue reading.";
});
$("pdf-page").addEventListener("load", () => { $("preview-error").hidden = true; });
function statusLabel(status) {
  return ({running:"In progress", failed:"Needs attention", partial:"Partial PDF", captured_with_warnings:"Ready · with notes", captured:"Ready"})[status] || status;
}
function renderHistory(history) {
  $("history").replaceChildren();
  if (!history.length) {
    const empty = document.createElement("p"); empty.className = "empty-history";
    empty.textContent = "A clean slate. Your completed exports will appear here.";
    $("history").append(empty); return;
  }
  for (const job of history) {
    const button = document.createElement("button"); button.type = "button"; button.className = "history-item";
    const icon = document.createElement("span"); icon.className = "history-icon"; icon.textContent = "PDF";
    const content = document.createElement("span"); content.className = "history-content";
    const title = document.createElement("strong"); title.textContent = job.title;
    const meta = document.createElement("small");
    const date = new Date(job.created_at).toLocaleString(undefined, {month:"short",day:"numeric",hour:"numeric",minute:"2-digit"});
    meta.textContent = date + (job.summary?.exported_units != null ? ` · ${job.summary.exported_units} lessons` : "");
    if (job.expires_at) {
      meta.textContent += ` · Auto-deletes in ${Math.max(1, Math.ceil((Date.parse(job.expires_at) - serverNow()) / 60000))} min`;
      meta.title = `Deletes at ${new Date(job.expires_at).toLocaleString()}`;
    }
    const status = document.createElement("span"); status.textContent = statusLabel(job.status) + " ↗";
    content.append(title, meta); button.append(icon, content, status);
    button.addEventListener("click", () => selectJob(job.id, true)); $("history").append(button);
  }
}
async function refreshState() {
  clearTimeout(stateTimer);
  const data = await api("/api/state");
  if (data.server_time) serverOffset = Date.parse(data.server_time) - Date.now();
  activeJob = data.active;
  setBusy(!!activeJob || data.busy);
  if (data.busy && !activeJob) $("create-button").firstElementChild.textContent = "Another export is running. Please wait...";
  libraryHistory = data.history;
  expireLibrary();
  queueStateRefresh(activeJob && activeJob !== selectedJob ? 2000 : 30000);
  return data;
}
function queueStateRefresh(delay) {
  clearTimeout(stateTimer);
  stateTimer = setTimeout(() => refreshState().catch(() => {
    queueStateRefresh(30000);
  }), delay);
}
function renderJob(job) {
  selectedExpiry = job.expires_at || null;
  stored("sessionStorage", historyKey(), JSON.stringify({ id: job.id, expires_at: selectedExpiry }));
  expireLibrary();
  if (selectedJob !== job.id) return;
  const running = job.status === "running", failed = job.status === "failed";
  $("job-panel").hidden = false;
  $("job-heading").textContent = running ? "Collecting your lessons" : failed ? "Let’s try that again" : job.status === "partial" ? "Your partial study copy is ready" : "Your study copy is ready";
  $("job-eyebrow").textContent = running ? "PUTTING IT ALL TOGETHER" : failed ? "EXPORT INTERRUPTED" : "A LEARNING PATH, NOW A KEEPER";
  $("job-status").textContent = statusLabel(job.status);
  $("job-status").className = "status-pill" + (running ? "" : failed ? " failed" : " success");
  $("job-message").textContent = running ? job.message : job.title;
  $("job-progress").value = job.progress;
  $("job-error").hidden = !job.error; $("job-error").textContent = job.error;
  $("execution-log").textContent = job.logs.join("\n");
  $("metrics").replaceChildren(); $("metrics").hidden = !Object.keys(job.summary).length;
  for (const [key, label] of [["modules", "Modules"], ["discovered_units", "Lessons found"], ["exported_units", "Lessons captured"]]) {
    if (job.summary[key] == null) continue;
    const metric = document.createElement("div"); metric.className = "metric";
    const value = document.createElement("strong"); value.textContent = job.summary[key];
    const caption = document.createElement("span"); caption.textContent = label;
    metric.append(value, caption); $("metrics").append(metric);
  }
  $("downloads").replaceChildren();
  const labels = {pdf:"Download combined PDF ↓", html:"Readable HTML ↗", report:"Extraction report ↓"};
  for (const type of job.downloads) {
    const link = document.createElement("a"); link.href = "#";
    link.addEventListener("click", event => downloadFile(event, job.id, type));
    link.className = type === "pdf" ? "primary-button" : "secondary-button";
    link.textContent = labels[type]; link.setAttribute("download", ""); $("downloads").append(link);
  }
  const notes = [...job.errors, ...job.warnings];
  $("warning-panel").hidden = !notes.length;
  $("warning-heading").textContent = `${notes.length} export note${notes.length === 1 ? "" : "s"} — review before reading`;
  $("warnings").replaceChildren();
  for (const note of notes) {
    const item = document.createElement("li"); item.textContent = note.message;
    if (note.url && note.url.startsWith("https://learn.microsoft.com/")) {
      const link = document.createElement("a"); link.href = note.url; link.textContent = "View source lesson ↗";
      link.target = "_blank"; link.rel = "noopener noreferrer"; item.append(link);
    }
    $("warnings").append(item);
  }
  if (!running && notes.length) $("warning-panel").open = true;
  if (job.downloads.includes("pdf")) {
    loadPreview(job);
    $("pdf-preview").hidden = false; $("paper-preview").hidden = true;
    $("preview-stage").classList.add("has-pdf");
    $("preview-heading").textContent = "Your document"; $("preview-tag").textContent = "LIVE PDF PREVIEW";
    $("preview-settings").textContent = `${job.summary.modules} modules · ${job.summary.exported_units} lessons`;
    $("preview-footer-note").textContent = "Download before the 1-hour expiry";
  }
}
async function selectJob(id, scroll = false) {
  clearTimeout(pollTimer); selectedJob = id; selectedExpiry = null; resetPreview();
  if (scroll) { $("job-panel").hidden = false; $("job-panel").scrollIntoView({behavior:"smooth",block:"start"}); }
  await pollJob(id);
}
async function pollJob(id) {
  try {
    const job = await api(`/api/jobs/${id}`);
    if (selectedJob !== id) return;
    renderJob(job);
    if (selectedJob !== id) return;
    showError("");
    if (job.status === "running") pollTimer = setTimeout(() => pollJob(id), 1200);
    else await refreshState();
  } catch (error) {
    if (selectedJob !== id) return;
    if (error.status === 404) {
      clearSelection();
      libraryHistory = libraryHistory.filter(job => job.id !== id);
      expireLibrary();
      showError("This export expired or is no longer available. Create a new export to continue.");
      return;
    }
    showError(`Unable to update this export: ${error.message}`);
    if ([401, 403, 404].includes(error.status)) return;
    pollTimer = setTimeout(() => pollJob(id), 3500);
  }
}
$("sample-button").addEventListener("click", () => { $("urls").value = sample; $("urls").focus(); showError(""); });
$("menu-button").addEventListener("click", () => {
  const open = $("menu-button").getAttribute("aria-expanded") !== "true";
  $("menu-button").setAttribute("aria-expanded", String(open));
  $("menu-button").setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
  $("main-nav").classList.toggle("is-open", open);
});
for (const link of $("main-nav").querySelectorAll("a")) link.addEventListener("click", () => {
  $("menu-button").setAttribute("aria-expanded", "false");
  $("menu-button").setAttribute("aria-label", "Open navigation");
  $("main-nav").classList.remove("is-open");
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && $("menu-button").getAttribute("aria-expanded") === "true") {
    $("menu-button").click();
    $("menu-button").focus();
  }
});
for (const id of ["title", "paper", "font", "font-size"]) $(id).addEventListener("input", updatePreview);
$("export-form").addEventListener("submit", async event => {
  event.preventDefault(); showError(""); setBusy(true);
  const config = {urls:$("urls").value.trim(), title:$("title").value.trim(), paper:$("paper").value,
    font:$("font").value, font_size:Number($("font-size").value), line_height:Number($("line-height").value),
    images:$("images").checked, unit_break:$("unit-break").checked, allow_partial:$("allow-partial").checked,
    delay:Number($("delay").value), selector:$("selector").value.trim()};
  try {
    const result = await api("/api/jobs", {method:"POST", body:JSON.stringify(config)});
    activeJob = result.id; await selectJob(result.id, true); $("job-heading").focus({preventScroll:true});
  } catch (error) { showError(error.message); setBusy(!!activeJob); }
});
async function initialize() {
  try {
    const state = await refreshState();
    if (!state) return false;
    connected = true;
    $("connection-badge").textContent = "Ready to export";
    showError("");
    let saved = null;
    try { saved = JSON.parse(stored("sessionStorage", historyKey()) || "null"); } catch { /* Ignore old selections. */ }
    const id = state.active || (state.history.some(j => j.id === saved?.id) ? saved.id : null);
    if (!id) stored("sessionStorage", historyKey(), null);
    if (id) await selectJob(id);
    return true;
  } catch (error) {
    setBusy(true);
    connected = false;
    $("create-button").firstElementChild.textContent = "Connecting to export service...";
    $("connection-badge").textContent = "Reconnecting...";
    showError(error.message);
    clearTimeout(stateTimer);
    stateTimer = setTimeout(initialize, 10000);
    return false;
  }
}
updatePreview();
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    expireLibrary();
    if (connected) refreshState().catch(() => {});
  }
});
initialize();
