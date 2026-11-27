import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Box, Button, Chip, Paper, Stack, Typography } from "@mui/material";
import DirectionsBusIcon from "@mui/icons-material/DirectionsBus";
import NavigationIcon from "@mui/icons-material/Navigation";
import GpsFixedIcon from "@mui/icons-material/GpsFixed";
import { ApiError, get, post } from "../../services/api";
import { ago, ConfirmDialog, ErrorBox, fmtDateTime, Loading, useLoad } from "../../components/common";
import { useAuth } from "../../services/auth";
import MapView from "../../components/MapView";
import { enqueue, flushQueue, FLUSH_EVERY_MS, toPoint, trackerStore } from "../../services/trackerEngine";

interface MyTrip { id: number; reference: string; route: string; departure_at: string; status: string; bus: string; tracking_active: boolean }
type Gps = "idle" | "waiting" | "ok" | "denied" | "unavailable" | "insecure";

export default function DriverTrackingPage() {
  const { me } = useAuth();
  const trips = useLoad(() => get<MyTrip[]>("/tracking/my-trips/"), []);
  const [tripId, setTripId] = useState<number | "">("");
  const [running, setRunning] = useState<number | null>(null);   // voyage actuellement suivi par CE téléphone
  const [gps, setGps] = useState<Gps>("idle");
  const [online, setOnline] = useState(navigator.onLine);
  const [lastFix, setLastFix] = useState<string | null>(null);
  const [lastSent, setLastSent] = useState<string | null>(null);
  const [queued, setQueued] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [hiddenWarning, setHiddenWarning] = useState(false);
  const [confirmStop, setConfirmStop] = useState(false);
  const [busy, setBusy] = useState(false);
  const [, tick] = useState(0);
  const [speed, setSpeed] = useState<number | null>(null);
  const [accuracy, setAccuracy] = useState<number | null>(null);
  const [heading, setHeading] = useState<number | null>(null);
  const [path, setPath] = useState<[number, number][]>([]);
  const [sentTotal, setSentTotal] = useState(0);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [log, setLog] = useState<{ t: string; text: string; kind: "ok" | "warn" | "err" }[]>([]);
  const pushLog = useCallback((text: string, kind: "ok" | "warn" | "err" = "ok") => setLog((l) => [{ t: new Date().toISOString(), text, kind }, ...l].slice(0, 6)), []);
  const lastRecorded = useRef<number | null>(null);
  const watchId = useRef<number | null>(null);
  const wakeLock = useRef<any>(null);

  useEffect(() => {
    const on = () => { setOnline(true); pushLog("Réseau retrouvé : envoi des positions en attente"); }, off = () => { setOnline(false); pushLog("Réseau perdu : positions gardées sur le téléphone", "warn"); };
    window.addEventListener("online", on); window.addEventListener("offline", off);
    const t = setInterval(() => tick((n) => n + 1), 10_000);   // rafraîchit « il y a X min »
    return () => { window.removeEventListener("online", on); window.removeEventListener("offline", off); clearInterval(t); };
  }, [pushLog]);

  const releaseWake = () => { try { wakeLock.current?.release(); } catch { /* ignoré */ } wakeLock.current = null; };
  const acquireWake = useCallback(async () => {
    try { if ("wakeLock" in navigator && !wakeLock.current) wakeLock.current = await (navigator as any).wakeLock.request("screen"); } catch { /* non supporté */ }
  }, []);

  const stopLocal = useCallback((trip: number | null, clearData: boolean) => {
    if (watchId.current != null) navigator.geolocation.clearWatch(watchId.current);
    watchId.current = null; releaseWake(); setRunning(null); setGps("idle");
    if (clearData && trip != null) trackerStore.clear(trip);
  }, []);

  const startWatching = useCallback((trip: number) => {
    if (!window.isSecureContext) { setGps("insecure"); return; }
    if (!("geolocation" in navigator)) { setGps("unavailable"); return; }
    setRunning(trip); setGps("waiting"); setStartedAt((t) => t ?? Date.now()); setQueued(trackerStore.load(trip).length);
    lastRecorded.current = null;
    acquireWake();
    watchId.current = navigator.geolocation.watchPosition(
      (pos) => {
        setGps("ok"); setLastFix(new Date(pos.timestamp).toISOString());
        setSpeed(pos.coords.speed != null ? Math.round(pos.coords.speed * 3.6) : null); setAccuracy(Math.round(pos.coords.accuracy)); setHeading(pos.coords.heading);
        if (enqueue(trip, toPoint(pos), lastRecorded.current)) {
          lastRecorded.current = Date.now(); setQueued(trackerStore.load(trip).length);
          setPath((p) => [...p, [pos.coords.latitude, pos.coords.longitude] as [number, number]].slice(-120));
        }
      },
      (err) => setGps(err.code === err.PERMISSION_DENIED ? "denied" : "unavailable"),
      { enableHighAccuracy: true, maximumAge: 5_000, timeout: 30_000 },
    );
  }, [acquireWake]);

  // Envoi périodique de la file (et immédiat au retour du réseau).
  useEffect(() => {
    if (running == null) return;
    let alive = true;
    const send = async () => {
      const token = trackerStore.getToken(running);
      if (!token) return;
      const r = await flushQueue(running, token);
      if (!alive) return;
      setQueued(trackerStore.load(running).length);
      if (r.status === "sent") { setLastSent(new Date().toISOString()); setError(null); setSentTotal((n) => n + r.sent); pushLog(`${r.sent} position(s) envoyée(s)`); }
      if (r.status === "offline") pushLog(`Envoi impossible : ${r.remaining} position(s) en attente`, "warn");
      if (r.status === "ended") { pushLog("Suivi terminé par le serveur", "warn"); setNotice(r.reason); stopLocal(running, true); trips.reload(); }
      if (r.status === "invalid_token") { setError("Ce téléphone n'est plus autorisé à suivre ce voyage (remplacé par un autre appareil ?). Redémarrez le suivi."); stopLocal(running, true); trips.reload(); }
    };
    const id = setInterval(send, FLUSH_EVERY_MS);
    const onOnline = () => send();
    window.addEventListener("online", onOnline);
    send();
    return () => { alive = false; clearInterval(id); window.removeEventListener("online", onOnline); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  // Écran verrouillé / autre application : le navigateur coupe le GPS. On prévient et on reprend au retour.
  useEffect(() => {
    const onVis = () => {
      if (document.hidden) { if (running != null) setHiddenWarning(true); }
      else if (running != null) acquireWake();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [running, acquireWake]);

  // Reprise après rechargement de la page si ce téléphone suivait déjà un voyage.
  useEffect(() => {
    if (running != null || !trips.data) return;
    const mine = trips.data.find((t) => t.tracking_active && trackerStore.getToken(t.id));
    if (mine) { setTripId(mine.id); startWatching(mine.id); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trips.data]);

  useEffect(() => () => { if (watchId.current != null) navigator.geolocation.clearWatch(watchId.current); releaseWake(); }, []);

  const start = async () => {
    if (tripId === "") return;
    setBusy(true); setError(null); setNotice(null); setHiddenWarning(false);
    try {
      const r = await post<{ token: string }>(`/trips/${tripId}/tracking/start/`, { device_label: navigator.userAgent.slice(0, 70) });
      trackerStore.clear(tripId);
      trackerStore.setToken(tripId, r.token);
      startWatching(tripId);
      trips.reload();
    } catch (e) { setError(e instanceof ApiError ? e.message : "Impossible de démarrer le suivi."); }
    finally { setBusy(false); }
  };

  const stop = async () => {
    if (running == null) return;
    const trip = running;
    // On tente d'envoyer ce qui reste avant d'arrêter.
    const token = trackerStore.getToken(trip);
    if (token) await flushQueue(trip, token);
    try { await post(`/trips/${trip}/tracking/stop/`); } catch { /* le serveur arrêtera à la fin du voyage */ }
    stopLocal(trip, true); setConfirmStop(false); setNotice("Suivi arrêté."); setStartedAt(null); setPath([]); setSentTotal(0); setLog([]); trips.reload();
  };

  if (trips.loading && !trips.data) return <Loading />;
  if (trips.error) return <ErrorBox message={trips.error} onRetry={trips.reload} />;
  const list = trips.data ?? [];
  const current = list.find((t) => t.id === running);
  const gpsInfo: Record<Gps, { text: string; color: "default" | "success" | "warning" | "error" }> = {
    idle: { text: "Arrêté", color: "default" }, waiting: { text: "Recherche du signal GPS…", color: "warning" },
    ok: { text: "GPS actif", color: "success" }, denied: { text: "Localisation refusée", color: "error" },
    unavailable: { text: "GPS indisponible", color: "error" }, insecure: { text: "Connexion non sécurisée", color: "error" },
  };

  return (
    <Box sx={{ maxWidth: 560, mx: "auto" }}>
      <Typography variant="h5" fontWeight={800} sx={{ mb: 0.5 }}>Suivi du bus</Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>{me?.full_name || me?.email} · ce téléphone envoie la position du bus</Typography>
      {notice && <Alert severity="info" sx={{ mb: 1.5 }} onClose={() => setNotice(null)}>{notice}</Alert>}
      {error && <Alert severity="error" sx={{ mb: 1.5 }}>{error}</Alert>}

      {running == null ? (
        <Paper sx={{ p: 2.5 }}>
          {!list.length ? <Alert severity="info">Aucun voyage à suivre pour le moment. Un voyage doit être ouvert, en embarquement ou clôturé (en route), et vous devez y être affecté.</Alert> : (
            <Stack spacing={2}>
              <Typography fontWeight={700}>Choisissez le voyage à suivre</Typography>
              {list.map((t) => (
                <Paper key={t.id} variant="outlined" onClick={() => setTripId(t.id)} role="button" aria-pressed={tripId === t.id}
                  sx={{ p: 1.5, cursor: "pointer", borderWidth: 2, borderColor: tripId === t.id ? "primary.main" : "divider", bgcolor: tripId === t.id ? "action.selected" : "background.paper" }}>
                  <Stack direction="row" spacing={1.5} alignItems="center">
                    <DirectionsBusIcon color={tripId === t.id ? "primary" : "action"} />
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      <Typography fontWeight={700}>{t.route}</Typography>
                      <Typography variant="body2" color="text.secondary">{t.reference} · bus {t.bus} · {fmtDateTime(t.departure_at, me?.tenant?.timezone)}</Typography>
                    </Box>
                    {t.tracking_active && <Chip size="small" color="warning" label="Suivi actif" />}
                  </Stack>
                </Paper>
              ))}
              <Alert severity="warning" icon={<GpsFixedIcon />}>
                Branchez le téléphone, <b>gardez cet écran allumé</b> et cette page ouverte pendant tout le trajet. Si vous verrouillez le téléphone ou ouvrez une autre application, la localisation s'interrompt : pour un suivi fiable écran verrouillé, utilisez l'application Android « Transit Suivi ».
              </Alert>
              <Alert severity="info">Votre position est partagée avec votre compagnie uniquement pendant ce voyage, jusqu'à l'arrêt du suivi ou la fin du voyage.</Alert>
              <Button variant="contained" size="large" disabled={busy || tripId === ""} onClick={start}>{busy ? "Démarrage…" : "Démarrer le suivi"}</Button>
            </Stack>
          )}
        </Paper>
      ) : (
        <Stack spacing={1.5}>
          <Paper sx={{ p: 2, bgcolor: gps === "ok" ? "#14532d" : "#78350f", color: "white" }}>
            <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
              <Box>
                <Typography fontWeight={800} fontSize={18}>{current ? current.route : "Voyage en cours"}</Typography>
                <Typography variant="body2" sx={{ opacity: 0.85 }}>{current ? `${current.reference} · bus ${current.bus}` : ""}{startedAt ? ` · depuis ${Math.max(1, Math.round((Date.now() - startedAt) / 60000))} min` : ""}</Typography>
              </Box>
              <Chip size="small" label={gpsInfo[gps].text} sx={{ bgcolor: "rgba(255,255,255,.2)", color: "white", fontWeight: 700 }} />
            </Stack>
            <Stack direction="row" alignItems="flex-end" spacing={2} sx={{ mt: 1.5 }}>
              <Box>
                <Typography fontSize={56} fontWeight={800} lineHeight={1}>{speed ?? "—"}</Typography>
                <Typography variant="body2" sx={{ opacity: 0.85 }}>km/h</Typography>
              </Box>
              <Box sx={{ flex: 1 }} />
              <Stack alignItems="center" sx={{ opacity: heading != null ? 1 : 0.4 }}>
                <NavigationIcon sx={{ fontSize: 34, transform: `rotate(${heading ?? 0}deg)`, transition: "transform .6s" }} />
                <Typography variant="caption">{heading != null ? `${Math.round(heading)}°` : "cap ?"}</Typography>
              </Stack>
              <Box sx={{ textAlign: "right" }}>
                <Typography fontWeight={700}>{accuracy != null ? `±${accuracy} m` : "—"}</Typography>
                <Typography variant="caption" sx={{ opacity: 0.85 }}>précision GPS</Typography>
              </Box>
            </Stack>
          </Paper>

          <Stack direction="row" spacing={1}>
            {[{ v: sentTotal, l: "envoyées" }, { v: queued, l: "en attente", warn: queued > 0 }, { v: online ? "OK" : "Hors", l: "réseau", warn: !online }].map((k) => (
              <Paper key={k.l} sx={{ flex: 1, p: 1, textAlign: "center", border: k.warn ? "1px solid #f59e0b" : "1px solid transparent" }}>
                <Typography fontWeight={800} fontSize={20} color={k.warn ? "warning.main" : "text.primary"}>{k.v}</Typography>
                <Typography variant="caption" color="text.secondary">{k.l}</Typography>
              </Paper>
            ))}
          </Stack>

          {!online && <Alert severity="warning">Pas de réseau : les positions sont gardées sur le téléphone et seront envoyées au retour du signal.</Alert>}
          {gps === "denied" && <Alert severity="error">Autorisez la localisation pour ce site dans les réglages du navigateur, puis redémarrez le suivi.</Alert>}
          {gps === "insecure" && <Alert severity="error">La localisation exige une connexion sécurisée (HTTPS). Contactez votre administrateur.</Alert>}
          {hiddenWarning && <Alert severity="warning" onClose={() => setHiddenWarning(false)}>L'écran a été quitté : des positions ont pu être manquées. Gardez cette page ouverte et l'écran allumé.</Alert>}

          {path.length > 0 && (
            <Paper sx={{ p: 1 }}>
              <MapView markers={[{ id: "me", lat: path[path.length - 1][0], lon: path[path.length - 1][1], label: "Vous êtes ici", selected: true, heading }]} trail={path} height={200} fitKey="me" follow />
            </Paper>
          )}

          <Paper sx={{ p: 1.5 }}>
            <Typography variant="body2" fontWeight={700} sx={{ mb: 0.5 }}>Journal</Typography>
            {!log.length ? <Typography variant="body2" color="text.secondary">En attente du premier envoi…</Typography> : log.map((e, i) => (
              <Stack key={i} direction="row" spacing={1} alignItems="center">
                <Box sx={{ width: 8, height: 8, borderRadius: "50%", bgcolor: e.kind === "ok" ? "success.main" : e.kind === "warn" ? "warning.main" : "error.main" }} />
                <Typography variant="body2" sx={{ flex: 1 }}>{e.text}</Typography>
                <Typography variant="caption" color="text.secondary">{new Date(e.t).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</Typography>
              </Stack>
            ))}
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>Dernière position lue {ago(lastFix)} · dernier envoi {lastSent ? ago(lastSent) : "—"}</Typography>
          </Paper>

          <Button color="error" variant="outlined" size="large" onClick={() => setConfirmStop(true)}>Arrêter le suivi</Button>
        </Stack>
      )}
      <ConfirmDialog open={confirmStop} danger title="Arrêter le suivi ?" text="La compagnie et les passagers ne verront plus la position du bus tant que le suivi n'est pas relancé." confirmLabel="Arrêter" onClose={() => setConfirmStop(false)} onConfirm={stop} />
    </Box>
  );
}
