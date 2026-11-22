import { enqueue, flushQueue, MIN_INTERVAL_MS, shouldRecord, toPoint, trackerStore, type TrackPoint } from "../services/trackerEngine";

const pt = (i: number, acc: number | null = 10): TrackPoint => ({
  lat: -11.66 + i * 0.001, lon: 27.47, speed_kmh: 50, heading: null, accuracy_m: acc, recorded_at: new Date(1_700_000_000_000 + i * 15_000).toISOString(),
});
const resp = (status: number, body: object = {}) => Promise.resolve(new Response(JSON.stringify(body), { status }));

beforeEach(() => localStorage.clear());

describe("échantillonnage", () => {
  it("espace les points d'au moins 15 s et ignore les points imprécis", () => {
    expect(shouldRecord(null, 1000, 10)).toBe(true);
    expect(shouldRecord(1000, 1000 + MIN_INTERVAL_MS - 1, 10)).toBe(false);
    expect(shouldRecord(1000, 1000 + MIN_INTERVAL_MS, 10)).toBe(true);
    expect(shouldRecord(null, 1000, 900)).toBe(false);
  });
  it("convertit m/s en km/h et horodate en ISO", () => {
    const p = toPoint({ coords: { latitude: -11, longitude: 27, speed: 10, heading: 90, accuracy: 12 }, timestamp: 1_700_000_000_000 });
    expect(p.speed_kmh).toBe(36);
    expect(p.recorded_at).toBe("2023-11-14T22:13:20.000Z");
  });
});

describe("file locale et envoi", () => {
  it("garde les points tant que le serveur n'a pas confirmé (réseau coupé)", async () => {
    for (let i = 0; i < 3; i++) enqueue(7, pt(i), i ? 0 : null, 1e12 + i * 20_000);
    expect(trackerStore.load(7)).toHaveLength(3);
    const r = await flushQueue(7, "tok", (() => Promise.reject(new TypeError("offline"))) as any);
    expect(r).toEqual({ status: "offline", remaining: 3 });
    expect(trackerStore.load(7)).toHaveLength(3);
  });

  it("vide la file après confirmation et envoie le jeton en en-tête", async () => {
    trackerStore.save(7, [pt(0), pt(1)]);
    const fetchFn = vi.fn(() => resp(200, { accepted: 2 }));
    const r = await flushQueue(7, "secret-token", fetchFn as any);
    expect(r).toEqual({ status: "sent", sent: 2, remaining: 0 });
    expect(trackerStore.load(7)).toEqual([]);
    const [url, init] = fetchFn.mock.calls[0] as any;
    expect(url).toBe("/api/v1/tracking/ingest/");
    expect(init.headers["X-Tracking-Token"]).toBe("secret-token");
    expect(JSON.parse(init.body).points).toHaveLength(2);
  });

  it("découpe les gros retards en plusieurs lots de 100", async () => {
    trackerStore.save(7, Array.from({ length: 250 }, (_, i) => pt(i)));
    const sizes: number[] = [];
    const fetchFn = vi.fn((_u: string, init: any) => { sizes.push(JSON.parse(init.body).points.length); return resp(200); });
    const r = await flushQueue(7, "t", fetchFn as any);
    expect(sizes).toEqual([100, 100, 50]);
    expect(r).toEqual({ status: "sent", sent: 250, remaining: 0 });
  });

  it("conserve la suite de la file si le réseau tombe au milieu", async () => {
    trackerStore.save(7, Array.from({ length: 150 }, (_, i) => pt(i)));
    let n = 0;
    const fetchFn = vi.fn(() => (++n === 1 ? resp(200) : Promise.reject(new TypeError("offline"))));
    const r = await flushQueue(7, "t", fetchFn as any);
    expect(r).toEqual({ status: "offline", remaining: 50 });
    expect(trackerStore.load(7)).toHaveLength(50);
  });

  it("ne perd pas les points ajoutés pendant l'envoi", async () => {
    trackerStore.save(7, [pt(0), pt(1)]);
    let calls = 0;
    const fetchFn = vi.fn(async () => { if (++calls === 1) trackerStore.save(7, [...trackerStore.load(7), pt(2)]); return new Response("{}", { status: 200 }); });
    const r = await flushQueue(7, "t", fetchFn as any);
    expect(r).toEqual({ status: "sent", sent: 3, remaining: 0 }); // le point arrivé pendant l'envoi part au lot suivant
    expect(trackerStore.load(7)).toEqual([]);
  });

  it("arrête sur 410 (suivi terminé) et 401 (jeton refusé) sans vider la file", async () => {
    trackerStore.save(7, [pt(0)]);
    expect(await flushQueue(7, "t", (() => resp(410, { detail: "Le voyage est terminé." })) as any)).toEqual({ status: "ended", reason: "Le voyage est terminé." });
    expect(await flushQueue(7, "t", (() => resp(401)) as any)).toEqual({ status: "invalid_token" });
  });

  it("réessaie plus tard sur erreur serveur ou limitation de débit", async () => {
    trackerStore.save(7, [pt(0)]);
    for (const code of [500, 502, 429]) expect(await flushQueue(7, "t", (() => resp(code)) as any)).toEqual({ status: "offline", remaining: 1 });
    expect(trackerStore.load(7)).toHaveLength(1);
  });

  it("écarte un lot invalide (400) pour ne pas bloquer la file", async () => {
    trackerStore.save(7, [pt(0), pt(1)]);
    const r = await flushQueue(7, "t", (() => resp(400)) as any);
    expect(r).toEqual({ status: "empty" });
    expect(trackerStore.load(7)).toEqual([]);
  });
});
