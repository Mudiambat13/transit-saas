import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Alert, Box, Button, Chip, Grid, IconButton, InputAdornment, LinearProgress, Paper, Slider, Stack, Switch, TextField, ToggleButton, ToggleButtonGroup, Tooltip, Typography,
} from "@mui/material";
import SearchIcon from "@mui/icons-material/Search";
import PauseIcon from "@mui/icons-material/Pause";
import PlayIcon from "@mui/icons-material/PlayArrow";
import FitScreenIcon from "@mui/icons-material/FitScreen";
import WhatsAppIcon from "@mui/icons-material/WhatsApp";
import LinkIcon from "@mui/icons-material/ContentCopy";
import { get } from "../../services/api";
import { ago, EmptyState, ErrorBox, fmtDateTime, Loading, PageHeader, useLoad, useToast } from "../../components/common";
import { useAuth } from "../../services/auth";
import MapView, { type MapMarker } from "../../components/MapView";

interface Live {
  trip_id: number; reference: string; route: string; bus: string; status: string; stale: boolean; drivers: string[]; departure_at: string; started_at: string;
  last: { lat: number; lon: number; speed_kmh: number | null; heading: number | null; recorded_at: string } | null;
}
type Filter = "all" | "online" | "stale";
const REFRESH_S = 10;

const fmtDuration = (min: number) => (min >= 60 ? `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, "0")}` : `${min} min`);

function Kpi({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <Paper sx={{ p: 1.5, flex: 1, minWidth: 110 }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="h5" fontWeight={800} sx={{ color }}>{value}</Typography>
    </Paper>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return <Box sx={{ flex: 1, minWidth: 90 }}><Typography variant="caption" color="text.secondary">{label}</Typography><Typography fontWeight={700}>{value}</Typography></Box>;
}

export default function LiveMapPage() {
  const { me } = useAuth();
  const { toast, node } = useToast();
  const [params, setParams] = useSearchParams();
  const selected = params.get("trip") ? Number(params.get("trip")) : null;
  const live = useLoad(() => get<Live[]>("/tracking/live/"), []);
  const detail = useLoad(() => (selected ? get<any>(`/trips/${selected}/tracking/`) : Promise.resolve(null)), [selected]);
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  const [auto, setAuto] = useState(true);
  const [follow, setFollow] = useState(true);
  const [count, setCount] = useState(REFRESH_S);
  const [fitAll, setFitAll] = useState(0);
  const [replayIdx, setReplayIdx] = useState<number | null>(null);   // null = en direct

  // Compte à rebours + rafraîchissement automatique (suspendu si l'utilisateur met en pause).
  useEffect(() => {
    if (!auto) return;
    const id = setInterval(() => {
      setCount((c) => {
        if (c > 1) return c - 1;
        live.reload(); if (selected) detail.reload();
        return REFRESH_S;
      });
    }, 1000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto, selected]);

  useEffect(() => { setReplayIdx(null); }, [selected]);

  const select = useCallback((id: string | number | null) => setParams(id == null ? {} : { trip: String(id) }), [setParams]);
  const refreshNow = () => { live.reload(); if (selected) detail.reload(); setCount(REFRESH_S); };

  const fleet = live.data ?? [];
  const online = fleet.filter((b) => !b.stale).length;
  const shown = [...fleet].sort((a, b) => a.reference.localeCompare(b.reference)).filter((b) => (filter === "all" || (filter === "online" ? !b.stale : b.stale)) && `${b.reference} ${b.bus} ${b.route} ${b.drivers.join(" ")}`.toLowerCase().includes(q.toLowerCase()));
  const d = detail.data;
  const replay: [number, number, number | null, string][] = d?.replay ?? [];
  const cur = replayIdx != null ? replay[replayIdx] : null;

  const markers = useMemo<MapMarker[]>(() => {
    const m: MapMarker[] = shown.filter((b) => b.last).map((b) => ({
      id: b.trip_id, lat: b.last!.lat, lon: b.last!.lon, heading: b.last!.heading, label: `${b.reference} · ${b.bus}`, stale: b.stale, selected: b.trip_id === selected,
    }));
    if (selected && d?.last && !m.some((x) => x.id === selected)) m.push({ id: selected, lat: d.last.lat, lon: d.last.lon, label: d.trip.reference, stale: true, selected: true });
    return m;
  }, [shown, d, selected]);   // eslint-disable-line react-hooks/exhaustive-deps

  const link = d?.tracking_code ? `${window.location.origin}/suivi/${d.tracking_code}` : "";
  const copy = async () => { try { await navigator.clipboard.writeText(link); toast.ok("Lien copié."); } catch { toast.ok(link); } };
  const wa = `https://wa.me/?text=${encodeURIComponent(`Suivez le bus ${d?.trip?.route ?? ""} en direct : ${link}`)}`;

  if (live.error) return <ErrorBox message={live.error} onRetry={live.reload} />;
  if (live.loading && !live.data) return <Loading />;

  return (
    <>
      <PageHeader title="Suivi en direct" subtitle="Cliquez sur un bus pour voir son parcours, ses statistiques et rejouer son trajet" />
      <Stack direction="row" spacing={1.5} sx={{ mb: 2 }} flexWrap="wrap" useFlexGap>
        <Kpi label="Bus suivis" value={fleet.length} />
        <Kpi label="En ligne" value={online} color="#16a34a" />
        <Kpi label="Sans signal" value={fleet.length - online} color={fleet.length - online ? "#d97706" : undefined} />
        <Paper sx={{ p: 1.5, flex: 2, minWidth: 220, display: "flex", alignItems: "center", gap: 1 }}>
          <Box sx={{ flex: 1 }}>
            <Typography variant="caption" color="text.secondary">{auto ? `Actualisation dans ${count} s` : "Actualisation en pause"}</Typography>
            <LinearProgress variant="determinate" value={auto ? ((REFRESH_S - count) / REFRESH_S) * 100 : 0} sx={{ mt: 0.5, height: 6, borderRadius: 3 }} />
          </Box>
          <Tooltip title={auto ? "Mettre en pause" : "Reprendre"}><IconButton onClick={() => { setAuto(!auto); setCount(REFRESH_S); }}>{auto ? <PauseIcon /> : <PlayIcon />}</IconButton></Tooltip>
          <Button size="small" onClick={refreshNow}>Actualiser</Button>
        </Paper>
      </Stack>

      <Grid container spacing={2}>
        <Grid item xs={12} md={8}>
          <Box sx={{ position: "relative" }}>
            <MapView markers={markers} trail={d?.trail ?? []} cursor={cur ? [cur[0], cur[1]] : null} height={560} onSelect={select} fitKey={`${selected ?? "all"}-${fitAll}`} follow={follow && !!selected && replayIdx == null} />
            <Stack direction="row" spacing={1} sx={{ position: "absolute", top: 10, right: 10, zIndex: 500 }}>
              <Paper sx={{ px: 1, display: "flex", alignItems: "center" }}>
                <Typography variant="caption">Suivre le bus</Typography>
                <Switch size="small" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
              </Paper>
              <Tooltip title="Tout afficher"><Paper><IconButton size="small" onClick={() => { select(null); setFitAll((n) => n + 1); }}><FitScreenIcon /></IconButton></Paper></Tooltip>
            </Stack>
          </Box>
        </Grid>

        <Grid item xs={12} md={4}>
          <Stack spacing={2}>
            <Paper sx={{ p: 1.5 }}>
              <TextField size="small" fullWidth placeholder="Rechercher un bus, un chauffeur, une ville…" value={q} onChange={(e) => setQ(e.target.value)}
                InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }} />
              <ToggleButtonGroup size="small" exclusive value={filter} onChange={(_, v) => v && setFilter(v)} sx={{ mt: 1 }} fullWidth>
                <ToggleButton value="all">Tous ({fleet.length})</ToggleButton>
                <ToggleButton value="online">En ligne ({online})</ToggleButton>
                <ToggleButton value="stale">Sans signal ({fleet.length - online})</ToggleButton>
              </ToggleButtonGroup>
            </Paper>

            {!shown.length ? <Paper><EmptyState text={fleet.length ? "Aucun bus ne correspond." : "Aucun bus suivi pour le moment."} /></Paper> : shown.map((b) => (
              <Paper key={b.trip_id} onClick={() => select(b.trip_id)} sx={{ p: 1.5, cursor: "pointer", borderLeft: 5, borderColor: b.stale ? "#f59e0b" : "#16a34a", outline: b.trip_id === selected ? "2px solid #2563eb" : "none", "&:hover": { bgcolor: "action.hover" } }}>
                <Stack direction="row" justifyContent="space-between" alignItems="center">
                  <Typography fontWeight={700}>{b.reference} <Typography component="span" variant="body2" color="text.secondary">{b.bus}</Typography></Typography>
                  <Chip size="small" color={b.stale ? "warning" : "success"} label={b.stale ? "Sans signal" : "En ligne"} />
                </Stack>
                <Typography variant="body2">{b.route}</Typography>
                <Typography variant="caption" color="text.secondary">
                  {b.last ? `Signal ${ago(b.last.recorded_at)}${b.last.speed_kmh != null ? ` · ${Math.round(b.last.speed_kmh)} km/h` : ""}` : "En attente du premier signal"}
                  {b.drivers.length ? ` · ${b.drivers.join(", ")}` : ""}
                </Typography>
              </Paper>
            ))}
          </Stack>
        </Grid>

        {d && (
          <Grid item xs={12}>
            <Paper sx={{ p: 2 }}>
              <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={1} sx={{ mb: 1.5 }}>
                <Box>
                  <Typography variant="h6" fontWeight={800}>{d.trip.reference} · {d.trip.route}</Typography>
                  <Typography variant="body2" color="text.secondary">Bus {d.bus}{d.drivers?.length ? ` · ${d.drivers.join(", ")}` : ""} · départ {fmtDateTime(d.departure_at, me?.tenant?.timezone)}</Typography>
                </Box>
                {link && (
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Button size="small" variant="outlined" startIcon={<LinkIcon />} onClick={copy}>Copier le lien passagers</Button>
                    <Button size="small" variant="contained" color="success" startIcon={<WhatsAppIcon />} href={wa} target="_blank" rel="noopener">WhatsApp</Button>
                  </Stack>
                )}
              </Stack>
              {!d.active && <Alert severity="info" sx={{ mb: 1.5 }}>Le suivi de ce voyage n'est pas actif : vous voyez le dernier parcours enregistré.</Alert>}
              {d.active && d.stale && <Alert severity="warning" sx={{ mb: 1.5 }}>Aucun signal depuis plus de 5 minutes : téléphone éteint, hors réseau, ou application quittée. Appelez le chauffeur.</Alert>}
              <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
                <Stat label="Vitesse" value={d.last?.speed_kmh != null ? `${Math.round(d.last.speed_kmh)} km/h` : "—"} />
                <Stat label="Distance parcourue" value={`${d.stats.distance_km} km`} />
                <Stat label="Durée" value={fmtDuration(d.stats.duration_min)} />
                <Stat label="Vitesse moyenne" value={d.stats.avg_speed_kmh != null ? `${d.stats.avg_speed_kmh} km/h` : "—"} />
                <Stat label="Vitesse max" value={d.stats.max_speed_kmh != null ? `${d.stats.max_speed_kmh} km/h` : "—"} />
                <Stat label="Dernier signal" value={ago(d.last?.recorded_at)} />
              </Stack>
              {replay.length > 1 && (
                <Box sx={{ mt: 1 }}>
                  <Stack direction="row" justifyContent="space-between">
                    <Typography variant="body2" fontWeight={700}>Rejeu du parcours</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {cur ? `${fmtDateTime(cur[3], me?.tenant?.timezone)}${cur[2] != null ? ` · ${Math.round(cur[2])} km/h` : ""}` : "En direct — déplacez le curseur pour revoir le trajet"}
                    </Typography>
                  </Stack>
                  <Slider size="small" min={0} max={replay.length - 1} value={replayIdx ?? replay.length - 1} onChange={(_, v) => setReplayIdx(v === replay.length - 1 ? null : (v as number))} aria-label="Rejeu du parcours" />
                </Box>
              )}
              {d.suspect_points > 0 && <Typography variant="caption" color="text.secondary">{d.suspect_points} position(s) aberrante(s) ignorée(s).</Typography>}
            </Paper>
          </Grid>
        )}
      </Grid>
      {node}
    </>
  );
}
