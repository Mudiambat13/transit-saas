import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Alert, Box, Button, Chip, MenuItem, Paper, Stack, TextField, Typography } from "@mui/material";
import WifiOffIcon from "@mui/icons-material/WifiOff";
import { BrowserQRCodeReader, type IScannerControls } from "@zxing/browser";
import { ApiError, get, post, type Page } from "../../services/api";
import { Loading, fmtDateTime, useLoad } from "../../components/common";
import { useAuth } from "../../services/auth";
import type { ScanOutcome, Trip } from "../../types";

const COLORS = { green: "#15803d", red: "#b91c1c", orange: "#d97706" } as const;

/** Identifiant de rejeu : si la requête est renvoyée après une coupure réseau, le serveur ne compte pas deux fois. */
const newKey = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`);

export default function ScannerPage() {
  const { me } = useAuth();
  const [params, setParams] = useSearchParams();
  const tripId = params.get("trip") ?? "";
  const trips = useLoad(() => get<Page<Trip>>("/trips/", { status: "BOARDING,OPEN" }), []);
  const [online, setOnline] = useState(navigator.onLine);
  const [outcome, setOutcome] = useState<ScanOutcome | null>(null);
  const [pending, setPending] = useState(false);
  const [netError, setNetError] = useState<string | null>(null);
  const [manual, setManual] = useState("");
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [history, setHistory] = useState<{ at: string; outcome: ScanOutcome }[]>([]);
  const videoRef = useRef<HTMLVideoElement>(null);
  const lastCode = useRef<{ code: string; at: number }>({ code: "", at: 0 });
  const busy = useRef(false);
  const tripRef = useRef(tripId);
  tripRef.current = tripId;

  useEffect(() => {
    const on = () => setOnline(true), off = () => setOnline(false);
    window.addEventListener("online", on); window.addEventListener("offline", off);
    return () => { window.removeEventListener("online", on); window.removeEventListener("offline", off); };
  }, []);

  const submit = useCallback(async (code: string) => {
    if (!tripRef.current || busy.current) return;
    // Anti-rebond : la caméra relit le même QR plusieurs fois par seconde.
    const now = Date.now();
    if (code === lastCode.current.code && now - lastCode.current.at < 3000) return;
    lastCode.current = { code, at: now };
    busy.current = true; setPending(true); setNetError(null);
    try {
      const out = await post<ScanOutcome>("/boarding/scan/", { trip: Number(tripRef.current), code, idempotency_key: newKey(), device: navigator.userAgent.slice(0, 60) });
      setOutcome(out); setHistory((h) => [{ at: new Date().toISOString(), outcome: out }, ...h].slice(0, 15));
      if (navigator.vibrate) navigator.vibrate(out.result === "VALIDATED" ? 80 : [120, 80, 120]);
    } catch (e) {
      // Jamais de « validé » sans confirmation du serveur.
      setOutcome(null);
      lastCode.current = { code: "", at: 0 };
      setNetError(e instanceof ApiError && e.code === "network" ? "Pas de connexion : l'embarquement n'a PAS été validé. Réessayez dès que le réseau revient." : e instanceof ApiError ? e.message : "Erreur inattendue.");
    } finally { busy.current = false; setPending(false); }
  }, []);

  useEffect(() => {
    if (!tripId || !videoRef.current) return;
    let controls: IScannerControls | undefined;
    let cancelled = false;
    const reader = new BrowserQRCodeReader();
    reader.decodeFromConstraints({ video: { facingMode: { ideal: "environment" } } }, videoRef.current, (result) => { if (result) submit(result.getText()); })
      .then((c) => { if (cancelled) c.stop(); else { controls = c; setCameraError(null); } })
      .catch(() => setCameraError("Caméra indisponible ou refusée. Autorisez l'accès à la caméra, ou saisissez la référence du billet ci-dessous."));
    return () => { cancelled = true; controls?.stop(); };
  }, [tripId, submit]);

  if (trips.loading && !trips.data) return <Loading />;
  const bg = outcome ? COLORS[outcome.color] : undefined;

  return (
    <Box sx={{ maxWidth: 560, mx: "auto" }}>
      <Typography variant="h5" fontWeight={800} sx={{ mb: 1.5 }}>Embarquement</Typography>
      {!online && <Alert icon={<WifiOffIcon />} severity="warning" sx={{ mb: 1.5 }}>Hors connexion : les scans ne peuvent pas être validés tant que le réseau n'est pas rétabli.</Alert>}
      <TextField select fullWidth size="small" label="Voyage à embarquer" value={tripId} onChange={(e) => { setOutcome(null); setParams({ trip: e.target.value }); }} sx={{ mb: 1.5, bgcolor: "white" }}>
        {trips.data?.results.map((t) => <MenuItem key={t.id} value={String(t.id)} disabled={t.status !== "BOARDING"}>{t.reference} · {t.origin} → {t.destination} · {fmtDateTime(t.departure_at, me?.tenant?.timezone)}{t.status !== "BOARDING" ? " (embarquement non démarré)" : ""}</MenuItem>)}
      </TextField>

      {tripId && (
        <>
          <Paper sx={{ overflow: "hidden", position: "relative", bgcolor: "#000", aspectRatio: "1 / 1" }}>
            <video ref={videoRef} muted playsInline style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            {pending && <Chip label="Vérification…" sx={{ position: "absolute", top: 8, left: 8 }} />}
            {cameraError && <Alert severity="error" sx={{ position: "absolute", inset: "auto 8px 8px 8px" }}>{cameraError}</Alert>}
          </Paper>

          {netError && <Alert severity="error" sx={{ mt: 1.5 }}>{netError}</Alert>}
          {outcome && (
            <Paper role="status" aria-live="assertive" sx={{ mt: 1.5, p: 2.5, bgcolor: bg, color: "white", textAlign: "center", border: 0 }}>
              <Typography variant="h5" fontWeight={800}>{outcome.message}</Typography>
              {outcome.ticket && <Typography sx={{ mt: 0.5 }}>{outcome.ticket.passenger} · siège {outcome.ticket.seat ?? "—"} · {outcome.ticket.reference}</Typography>}
            </Paper>
          )}

          <Stack direction="row" spacing={1} sx={{ mt: 1.5 }} component="form" onSubmit={(e) => { e.preventDefault(); if (manual.trim()) { lastCode.current = { code: "", at: 0 }; submit(manual.trim()); setManual(""); } }}>
            <TextField fullWidth size="small" label="Saisie manuelle de la référence (secours)" placeholder="TKT-XXXXXXXX" value={manual} onChange={(e) => setManual(e.target.value)} sx={{ bgcolor: "white" }} />
            <Button type="submit" variant="contained" disabled={!manual.trim() || pending}>Valider</Button>
          </Stack>

          {history.length > 0 && (
            <Paper sx={{ mt: 2, p: 1.5 }}>
              <Typography variant="subtitle2" sx={{ mb: 0.5 }}>Derniers scans</Typography>
              {history.map((h, i) => (
                <Stack key={i} direction="row" spacing={1} alignItems="center" sx={{ py: 0.4 }}>
                  <Box sx={{ width: 10, height: 10, borderRadius: "50%", bgcolor: COLORS[h.outcome.color] }} />
                  <Typography variant="body2" sx={{ flex: 1 }}>{h.outcome.ticket?.passenger ?? h.outcome.message}</Typography>
                  <Typography variant="caption" color="text.secondary">{new Date(h.at).toLocaleTimeString("fr-FR")}</Typography>
                </Stack>
              ))}
            </Paper>
          )}
        </>
      )}
    </Box>
  );
}
