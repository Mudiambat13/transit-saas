import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Box, Button, Chip, MenuItem, Paper, Stack, TextField, Typography } from "@mui/material";
import GpsFixedIcon from "@mui/icons-material/GpsFixed";
import { ApiError, get, post } from "../../services/api";
import { ago, ConfirmDialog, ErrorBox, fmtDateTime, Loading, useLoad } from "../../components/common";
import { useAuth } from "../../services/auth";
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
  const lastRecorded = useRef<number | null>(null);
  const watchId = useRef<number | null>(null);
  const wakeLock = useRef<any>(null);

  useEffect(() => {
    const on = () => setOnline(true), off = () => setOnline(false);
    window.addEventListener("online", on); window.addEventListener("offline", off);
    const t = setInterval(() => tick((n) => n + 1), 10_000);   // rafraîchit « il y a X min »
    return () => { window.removeEventListener("online", on); window.removeEventListener("offline", off); clearInterval(t); };
  }, []);

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
    setRunning(trip); setGps("waiting"); setQueued(trackerStore.load(trip).length);
    lastRecorded.current = null;
    acquireWake();
    watchId.current = navigator.geolocation.watchPosition(
      (pos) => {
        setGps("ok"); setLastFix(new Date(pos.timestamp).toISOString());
        if (enqueue(trip, toPoint(pos), lastRecorded.current)) { lastRecorded.current = Date.now(); setQueued(trackerStore.load(trip).length); }
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
      if (r.status === "sent") { setLastSent(new Date().toISOString()); setError(null); }
      if (r.status === "ended") { setNotice(r.reason); stopLocal(running, true); trips.reload(); }
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
    stopLocal(trip, true); setConfirmStop(false); setNotice("Suivi arrêté."); trips.reload();
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
              <TextField select size="small" label="Voyage" value={tripId} onChange={(e) => setTripId(Number(e.target.value))}>
                {list.map((t) => <MenuItem key={t.id} value={t.id}>{t.reference} · {t.route} · {fmtDateTime(t.departure_at, me?.tenant?.timezone)}{t.tracking_active ? " (suivi actif)" : ""}</MenuItem>)}
              </TextField>
              <Alert severity="warning" icon={<GpsFixedIcon />}>
                Branchez le téléphone, <b>gardez cet écran allumé</b> et cette page ouverte pendant tout le trajet. Si vous verrouillez le téléphone ou ouvrez une autre application, la localisation s'interrompt : pour un suivi fiable écran verrouillé, utilisez l'application Android « Transit Suivi ».
              </Alert>
              <Alert severity="info">Votre position est partagée avec votre compagnie uniquement pendant ce voyage, jusqu'à l'arrêt du suivi ou la fin du voyage.</Alert>
              <Button variant="contained" size="large" disabled={busy || tripId === ""} onClick={start}>{busy ? "Démarrage…" : "Démarrer le suivi"}</Button>
            </Stack>
          )}
        </Paper>
      ) : (
        <Paper sx={{ p: 2.5 }}>
          <Stack spacing={1.5}>
            <Typography fontWeight={700}>{current ? `${current.reference} · ${current.route}` : "Voyage en cours"}</Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Chip label={gpsInfo[gps].text} color={gpsInfo[gps].color} />
              <Chip label={online ? "Réseau OK" : "Hors réseau"} color={online ? "success" : "warning"} variant="outlined" />
              <Chip label={`En attente d'envoi : ${queued}`} color={queued > 20 ? "warning" : "default"} variant="outlined" />
            </Stack>
            <Typography variant="body2">Dernière position lue : <b>{ago(lastFix)}</b></Typography>
            <Typography variant="body2">Dernier envoi réussi : <b>{lastSent ? ago(lastSent) : "—"}</b></Typography>
            {!online && <Alert severity="warning">Pas de réseau : les positions sont gardées sur le téléphone et seront envoyées au retour du signal.</Alert>}
            {gps === "denied" && <Alert severity="error">Autorisez la localisation pour ce site dans les réglages du navigateur, puis redémarrez le suivi.</Alert>}
            {gps === "insecure" && <Alert severity="error">La localisation exige une connexion sécurisée (HTTPS). Contactez votre administrateur.</Alert>}
            {hiddenWarning && <Alert severity="warning" onClose={() => setHiddenWarning(false)}>L'écran a été quitté : des positions ont pu être manquées. Gardez cette page ouverte et l'écran allumé.</Alert>}
            <Button color="error" variant="outlined" onClick={() => setConfirmStop(true)}>Arrêter le suivi</Button>
          </Stack>
        </Paper>
      )}
      <ConfirmDialog open={confirmStop} danger title="Arrêter le suivi ?" text="La compagnie et les passagers ne verront plus la position du bus tant que le suivi n'est pas relancé." confirmLabel="Arrêter" onClose={() => setConfirmStop(false)} onConfirm={stop} />
    </Box>
  );
}
