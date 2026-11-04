// Client HTTP : JWT en mémoire + localStorage, renouvellement automatique, erreurs normalisées.
const BASE = "/api/v1";
const ACCESS = "transit.access";
const REFRESH = "transit.refresh";

export class ApiError extends Error {
  status: number;
  code?: string;
  fields: Record<string, string>;
  constructor(status: number, message: string, code?: string, fields: Record<string, string> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.fields = fields;
  }
}

export const tokens = {
  get access() { return localStorage.getItem(ACCESS); },
  get refresh() { return localStorage.getItem(REFRESH); },
  set(access: string, refresh?: string) {
    localStorage.setItem(ACCESS, access);
    if (refresh) localStorage.setItem(REFRESH, refresh);
  },
  clear() { localStorage.removeItem(ACCESS); localStorage.removeItem(REFRESH); },
};

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) { onUnauthorized = fn; }

let refreshing: Promise<boolean> | null = null;
async function tryRefresh(): Promise<boolean> {
  if (!tokens.refresh) return false;
  refreshing ??= fetch(`${BASE}/auth/refresh/`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh: tokens.refresh }),
  })
    .then(async (r) => {
      if (!r.ok) return false;
      const d = await r.json();
      tokens.set(d.access, d.refresh);
      return true;
    })
    .catch(() => false)
    .finally(() => { refreshing = null; });
  return refreshing;
}

function toApiError(status: number, data: any): ApiError {
  if (data && typeof data === "object") {
    const fields: Record<string, string> = {};
    let detail: string | undefined = typeof data.detail === "string" ? data.detail : undefined;
    for (const [k, v] of Object.entries(data)) {
      if (k === "detail" || k === "code") continue;
      const msg = Array.isArray(v) ? v.join(" ") : typeof v === "string" ? v : undefined;
      if (msg) fields[k] = msg;
    }
    if (!detail) detail = Object.values(fields)[0];
    return new ApiError(status, detail ?? "Une erreur est survenue.", data.code, fields);
  }
  return new ApiError(status, status >= 500 ? "Erreur serveur. Réessayez dans un instant." : "Requête refusée.");
}

async function raw(path: string, init: RequestInit = {}, retry = true): Promise<Response> {
  const headers = new Headers(init.headers);
  if (tokens.access) headers.set("Authorization", `Bearer ${tokens.access}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Connexion au serveur impossible. Vérifiez votre accès Internet.", "network");
  }
  if (res.status === 401 && retry && !path.startsWith("/auth/login")) {
    if (await tryRefresh()) return raw(path, init, false);
    tokens.clear();
    onUnauthorized();
  }
  return res;
}

export async function api<T = any>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = init;
  const res = await raw(path, { ...rest, body: json !== undefined ? JSON.stringify(json) : rest.body });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw toApiError(res.status, data);
  return data as T;
}

export const get = <T = any>(path: string, params?: Record<string, string | number | undefined | null>) => {
  const q = params ? "?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => [k, String(v)])).toString() : "";
  return api<T>(path + (q === "?" ? "" : q));
};
export const post = <T = any>(path: string, json?: unknown) => api<T>(path, { method: "POST", json: json ?? {} });
export const patch = <T = any>(path: string, json: unknown) => api<T>(path, { method: "PATCH", json });
export const del = <T = any>(path: string) => api<T>(path, { method: "DELETE" });

/** Ouvre un PDF protégé (nécessite le jeton) dans un nouvel onglet. */
export async function openPdf(path: string) {
  const win = window.open("", "_blank");
  const res = await raw(path);
  if (!res.ok) {
    win?.close();
    throw toApiError(res.status, await res.json().catch(() => null));
  }
  const url = URL.createObjectURL(await res.blob());
  if (win) win.location.href = url; else window.location.href = url;
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] };
