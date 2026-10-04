import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";

// Runs on Vercel, never in the browser. No third-party packages are required.
export default async function handler(req, res) {
  res.setHeader("Cache-Control", "private, no-store");
  res.setHeader("X-Content-Type-Options", "nosniff");
  const fail = (status, error) => res.status(status).json({ error });
  const path = new URL(req.url, "https://local.invalid").searchParams.get("path") || "";
  const allowed = /^\/api\/(state|health|jobs(?:\/[a-f0-9]{32})?)$|^\/files\/[a-f0-9]{32}\/(pdf|html|report)$|^\/preview\/[a-f0-9]{32}\/(info|[0-9]{1,4})$/;
  if (!allowed.test(path)) return fail(404, "Not found.");
  if (!["GET", "POST"].includes(req.method) || (req.method === "POST" && path !== "/api/jobs")) {
    return fail(405, "Method not allowed.");
  }
  if (req.method === "POST") {
    try {
      if (new URL(req.headers.origin).host !== req.headers.host) return fail(403, "Invalid request origin.");
    } catch { return fail(403, "Invalid request origin."); }
  }
  const key = process.env.BACKEND_API_KEY;
  if (!key || key.length < 32) return fail(503, "The export service is awaiting its server configuration. Please try again later.");
  const sign = value => createHmac("sha256", key).update(value).digest("hex");
  const cookie = (req.headers.cookie || "").split(";").map(part => part.trim()).find(part => part.startsWith("learnfolio_session="))?.slice("learnfolio_session=".length);
  let workspace;
  if (cookie && /^[a-f0-9]{32}\.[a-f0-9]{64}$/.test(cookie)) {
    const [id, signature] = cookie.split(".");
    if (timingSafeEqual(Buffer.from(signature, "hex"), Buffer.from(sign(id), "hex"))) workspace = id;
  }
  workspace ||= randomBytes(16).toString("hex");
  res.setHeader("Set-Cookie", `learnfolio_session=${workspace}.${sign(workspace)}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=3600`);
  try {
    const backend = new URL(process.env.BACKEND_URL || "https://microsoft-paths-to-pdf.onrender.com");
    if (backend.protocol !== "https:" || backend.username || backend.password || backend.pathname !== "/" || backend.search || backend.hash) {
      return fail(503, "The export service configuration needs attention.");
    }
    let body;
    if (req.method === "POST") {
      body = typeof req.body === "string" ? req.body : JSON.stringify(req.body ?? {});
      if (Buffer.byteLength(body) > 32768) return fail(413, "Request is too large.");
    }
    const upstream = await fetch(new URL(path, backend), {
      method: req.method,
      headers: { Authorization: `Bearer ${key}`, "X-Workspace-ID": workspace,
        ...(body ? { "Content-Type": "application/json" } : {}) },
      body, redirect: "error", signal: AbortSignal.timeout(40000),
    });
    if (upstream.status === 401 || upstream.status === 403) return fail(503, "The export service configuration needs attention. Please try again later.");
    if (upstream.headers.get("X-Learnfolio-Isolation") !== "workspace-v1") {
      return fail(503, "The export service is updating. Please try again shortly.");
    }
    res.statusCode = upstream.status;
    for (const name of ["content-type", "content-disposition", "content-security-policy"]) {
      if (upstream.headers.has(name)) res.setHeader(name, upstream.headers.get(name));
    }
    // Stream large PDFs instead of buffering the complete response in a function.
    if (upstream.body) await pipeline(Readable.fromWeb(upstream.body), res);
    else res.end();
  } catch {
    if (!res.headersSent) return fail(503, "The export service is waking up or temporarily unavailable. Retrying shortly.");
    res.destroy();
  }
}
