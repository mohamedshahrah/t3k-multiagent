// Talks to the sidecar. Inside the Wails window it goes through the Go proxy bindings
// (window.go.main.App); in a plain browser (vite dev) it falls back to direct fetch so
// the UI can be developed without launching the desktop shell.

const hasWails = typeof window !== "undefined" && window.go && window.go.main;
export const SIDECAR_BASE = "http://127.0.0.1:8756";
const BASE = SIDECAR_BASE;

// Direct URL to the original file (served inline) — used for the preview pane and
// works both in the Wails webview and a plain browser.
export function fileUrl(id) {
  return `${SIDECAR_BASE}/documents/${id}/file`;
}

// Is the app running inside the Wails desktop shell?
export function inWails() {
  return hasWails;
}

// Ask the Go shell to (re)start the Docker stack (retry button on the error screen).
export async function startStack() {
  if (hasWails && window.go.main.App.StartStack) {
    return window.go.main.App.StartStack();
  }
  return null;
}

export async function api(method, path, body) {
  if (hasWails) {
    const raw = await window.go.main.App.Api(method, path, body ? JSON.stringify(body) : "");
    return raw ? JSON.parse(raw) : null;
  }
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  return res.json();
}

// Pick a file via the native dialog and upload it. Returns { ok, result }.
export async function pickAndUpload() {
  if (hasWails) {
    const path = await window.go.main.App.OpenFileDialog();
    if (!path) return { ok: false, cancelled: true };
    const raw = await window.go.main.App.UploadFile(path);
    const result = JSON.parse(raw);
    return { ok: !result.error, result };
  }
  // Browser dev: use a hidden input.
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".pdf,.png,.jpg,.jpeg";
    input.onchange = async () => {
      const file = input.files[0];
      if (!file) return resolve({ ok: false, cancelled: true });
      resolve(uploadBlob(file, file.name));
    };
    input.click();
  });
}

// Upload a File/Blob (drag & drop path in the browser).
export async function uploadBlob(file, name) {
  const fd = new FormData();
  fd.append("file", file, name);
  const res = await fetch(`${BASE}/documents`, { method: "POST", body: fd });
  const result = await res.json();
  return { ok: res.status < 400, result };
}

// Subscribe to sidecar progress events (Wails runtime events or a raw EventSource).
export function onSidecarEvent(handler) {
  if (hasWails && window.runtime) {
    const names = [
      "document_ingested", "status", "agent_start", "tool_step", "agent_done", "error",
    ];
    names.forEach((n) =>
      window.runtime.EventsOn(`sidecar:${n}`, (data) => handler(n, safeParse(data))),
    );
    return () => names.forEach((n) => window.runtime.EventsOff(`sidecar:${n}`));
  }
  const es = new EventSource(`${BASE}/events`);
  const types = ["document_ingested", "status", "agent_start", "tool_step", "agent_done", "error"];
  types.forEach((t) => es.addEventListener(t, (e) => handler(t, safeParse(e.data))));
  return () => es.close();
}

function safeParse(s) {
  try {
    return typeof s === "string" ? JSON.parse(s) : s;
  } catch {
    return s;
  }
}
