import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Alert, Box, Chip, Grid, List, ListItemButton, ListItemText, Paper, Stack, Typography } from "@mui/material";
import { get } from "../../services/api";
import { ago, EmptyState, ErrorBox, Loading, PageHeader, StatusChip, useLoad } from "../../components/common";
import MapView, { type MapMarker } from "../../components/MapView";

interface Live {
  trip_id: number; reference: string; route: string; bus: string; status: string; stale: boolean;
  last: { lat: number; lon: number; speed_kmh: number | null; recorded_at: string } | null;
}
const REFRESH_MS = 10_000;

export default function LiveMapPage() {
  const [params, setParams] = useSearchParams();
  const selected = params.get("trip") ? Number(params.get("trip")) : null;
  const live = useLoad(() => get<Live[]>("/tracking/live/"), []);
  const detail = useLoad(() => (selected ? get<any>(`/trips/${selected}/tracking/`) : Promise.resolve(null)), [selected]);
  const [, tick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => { live.reload(); if (selected) detail.reload(); tick((n) => n + 1); }, REFRESH_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  const select = useCallback((id: string | number) => setParams({ trip: String(id) }), [setParams]);

  const markers = useMemo<MapMarker[]>(() => {
    const m: MapMarker[] = (live.data ?? []).filter((b) => b.last).map((b) => ({
      id: b.trip_id, lat: b.last!.lat, lon: b.last!.lon, label: `${b.reference} · ${b.bus}`, stale: b.stale, selected: b.trip_id === selected,
    }));
    // Voyage choisi mais plus actif : on montre quand même sa dernière position connue.
    const d = detail.data;
    if (selected && d?.last && !m.some((x) => x.id === selected)) m.push({ id: selected, lat: d.last.lat, lon: d.last.lon, label: d.trip.reference, stale: true, selected: true });
    return m;
  }, [live.data, detail.data, selected]);

  const trail = (detail.data?.trail ?? []) as [number, number][];
  const d = detail.data;

  if (live.error) return <ErrorBox message={live.error} onRetry={live.reload} />;
  if (live.loading && !live.data) return <Loading />;

  return (
    <>
      <PageHeader title="Suivi en direct" subtitle="Position des bus actuellement suivis · actualisation toutes les 10 secondes" />
      <Grid container spacing={2}>
        <Grid item xs={12} md={8}>
          <MapView markers={markers} trail={trail} height={520} onSelect={select} fitKey={selected ?? "all"} />
        </Grid>
        <Grid item xs={12} md={4}>
          <Paper>
            {!live.data?.length ? <EmptyState text="Aucun bus suivi pour le moment." /> : (
              <List dense disablePadding>
                {live.data.map((b) => (
                  <ListItemButton key={b.trip_id} selected={b.trip_id === selected} onClick={() => select(b.trip_id)} divider>
                    <ListItemText
                      primary={<Stack direction="row" spacing={1} alignItems="center"><b>{b.reference}</b><Typography variant="body2" color="text.secondary">{b.bus}</Typography></Stack>}
                      secondary={<>{b.route}<br />{b.last ? <>Dernier signal {ago(b.last.recorded_at)}{b.last.speed_kmh != null ? ` · ${Math.round(b.last.speed_kmh)} km/h` : ""}</> : "En attente du premier signal"}</>} />
                    {b.stale ? <Chip size="small" color="warning" label="Sans signal" /> : <StatusChip status={b.status} label="En ligne" />}
                  </ListItemButton>
                ))}
              </List>
            )}
          </Paper>
          {d && (
            <Paper sx={{ p: 2, mt: 2 }}>
              <Typography fontWeight={700}>{d.trip.reference} · {d.trip.route}</Typography>
              {!d.active && <Alert severity="info" sx={{ mt: 1 }}>Le suivi de ce voyage n'est pas actif.</Alert>}
              {d.active && d.stale && <Alert severity="warning" sx={{ mt: 1 }}>Aucun signal depuis plus de 5 minutes : téléphone éteint, hors réseau, ou application quittée.</Alert>}
              {d.last && <Typography variant="body2" sx={{ mt: 1 }}>Dernière position : {ago(d.last.recorded_at)}{d.last.accuracy_m != null ? ` · précision ±${Math.round(d.last.accuracy_m)} m` : ""}</Typography>}
              {d.suspect_points > 0 && <Typography variant="caption" color="text.secondary" display="block">{d.suspect_points} position(s) aberrante(s) ignorée(s).</Typography>}
              {d.tracking_code && (
                <Box sx={{ mt: 1.5 }}>
                  <Typography variant="caption" color="text.secondary">Lien passagers</Typography>
                  <Typography variant="body2" sx={{ wordBreak: "break-all", userSelect: "all" }}>{`${window.location.origin}/suivi/${d.tracking_code}`}</Typography>
                </Box>
              )}
            </Paper>
          )}
        </Grid>
      </Grid>
    </>
  );
}
