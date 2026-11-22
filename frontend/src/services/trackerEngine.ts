// Moteur de suivi du téléphone chauffeur : échantillonnage, file locale persistante, envoi par lots.
// Aucune dépendance à React : testable seul. Les positions sont gardées en mémoire locale tant que
// le serveur ne les a pas confirmées, pour survivre aux zones sans réseau et aux rechargements de page.

export interface TrackPoint {
  lat: number;
  lon: number;
  speed_kmh: number | null;
  heading: number | null;
  accuracy_m: number | null;
  recorded_at: string; // ISO UTC, heure d'origine sur le téléphone
}

export const MIN_INTERVAL_MS = 15_000;   // un point toutes les 15 s au plus
export const FLUSH_EVERY_MS = 15_000;    // tentative d'envoi toutes les 15 s
export const MAX_BATCH = 100;            // < limite serveur (200)
export const MAX_BATCHES_PER_FLUSH = 50; // plafond de sécurité : un envoi ne monopolise jamais le téléphone
export const MAX_QUEUE = 5_000;          // ~21 h à 1 point / 15 s ; au-delà on perd les plus anciens
const MAX_ACCURACY_M = 500;              // points trop imprécis ignorés

const tokenKey = (trip: number) => `transit.track.token.${trip}`;
const queueKey = (trip: number) => `transit.track.queue.${trip}`;

export const trackerStore = {
  getToken: (trip: number) => safe(() => localStorage.getItem(tokenKey(trip))),
  setToken: (trip: number, token: string) => safe(() => localStorage.setItem(tokenKey(trip), token)),
  clear: (trip: number) => safe(() => { localStorage.removeItem(tokenKey(trip)); localStorage.removeItem(queueKey(trip)); }),
  load(trip: number): TrackPoint[] {
    try { const raw = localStorage.getItem(queueKey(trip)); return raw ? (JSON.parse(raw) as TrackPoint[]) : []; } catch { return []; }
  },
  save(trip: number, q: TrackPoint[]) { safe(() => localStorage.setItem(queueKey(trip), JSON.stringify(q.slice(-MAX_QUEUE)))); },
};

function safe<T>(fn: () => T): T | null { try { return fn(); } catch { return null; } }

/** Décide si une nouvelle lecture GPS doit être enregistrée. */
export function shouldRecord(lastRecordedAt: number | null, now: number, accuracy: number | null): boolean {
  if (accuracy != null && accuracy > MAX_ACCURACY_M) return false;
  return lastRecordedAt == null || now - lastRecordedAt >= MIN_INTERVAL_MS;
}

export function toPoint(pos: { coords: { latitude: number; longitude: number; speed: number | null; heading: number | null; accuracy: number }; timestamp: number }): TrackPoint {
  const kmh = pos.coords.speed != null && Number.isFinite(pos.coords.speed) ? Math.round(pos.coords.speed * 3.6 * 10) / 10 : null;
  const heading = pos.coords.heading != null && Number.isFinite(pos.coords.heading) ? pos.coords.heading : null;
  return {
    lat: pos.coords.latitude, lon: pos.coords.longitude, speed_kmh: kmh, heading,
    accuracy_m: Number.isFinite(pos.coords.accuracy) ? pos.coords.accuracy : null,
    recorded_at: new Date(pos.timestamp).toISOString(),
  };
}

export type FlushResult =
  | { status: "sent"; sent: number; remaining: number }
  | { status: "empty" }
  | { status: "offline"; remaining: number }          // réseau ou serveur indisponible : on réessaiera
  | { status: "ended"; reason: string }                // session terminée côté serveur (410) : arrêter
  | { status: "invalid_token" };                       // jeton refusé (401) : arrêter

/** Envoie la file par lots. Ne retire de la file que les points confirmés par le serveur. */
export async function flushQueue(trip: number, token: string, fetchFn: typeof fetch = fetch): Promise<FlushResult> {
  let sentTotal = 0;
  for (let i = 0; ; i++) {
    const queue = trackerStore.load(trip);
    if (!queue.length) return sentTotal ? { status: "sent", sent: sentTotal, remaining: 0 } : { status: "empty" };
    if (i >= MAX_BATCHES_PER_FLUSH) return { status: "sent", sent: sentTotal, remaining: queue.length };
    const batch = queue.slice(0, MAX_BATCH);
    let res: Response;
    try {
      res = await fetchFn("/api/v1/tracking/ingest/", {
        method: "POST", headers: { "Content-Type": "application/json", "X-Tracking-Token": token }, body: JSON.stringify({ points: batch }),
      });
    } catch {
      return { status: "offline", remaining: queue.length };
    }
    if (res.status === 401) return { status: "invalid_token" };
    if (res.status === 410) return { status: "ended", reason: (await res.json().catch(() => ({})))?.detail ?? "Suivi terminé." };
    if (res.status === 400) {
      // Lot refusé en entier (ex. données invalides) : on l'écarte pour ne pas bloquer la file indéfiniment.
      trackerStore.save(trip, queue.slice(batch.length));
      continue;
    }
    if (!res.ok) return { status: "offline", remaining: queue.length }; // 5xx, 429… : réessayer plus tard
    // Les points ajoutés pendant l'envoi sont conservés : on retire uniquement ceux du lot confirmé.
    const current = trackerStore.load(trip);
    trackerStore.save(trip, current.slice(batch.length));
    sentTotal += batch.length;
  }
}

/** Ajoute un point à la file (en respectant l'espacement minimum). Retourne true si enregistré. */
export function enqueue(trip: number, point: TrackPoint, lastRecordedAt: number | null, now = Date.now()): boolean {
  if (!shouldRecord(lastRecordedAt, now, point.accuracy_m)) return false;
  const q = trackerStore.load(trip);
  q.push(point);
  trackerStore.save(trip, q);
  return true;
}
