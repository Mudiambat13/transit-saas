import { useEffect, useMemo } from "react";
import { useParams } from "react-router-dom";
import { Alert, Box, Chip, Container, Paper, Stack, Typography } from "@mui/material";
import { get } from "../../services/api";
import { ago, fmtDateTime, Loading, useLoad } from "../../components/common";
import MapView from "../../components/MapView";

interface Pub {
  company: string; origin: string; destination: string; departure_at: string; status: string; status_label: string; timezone: string;
  tracking_active: boolean; stale: boolean | null; position: { lat: number; lon: number; speed_kmh: number | null; recorded_at: string } | null; trail: [number, number][];
}

/** Page passagers : publique, sans connexion, sans menu. Données minimales (jamais de bus, chauffeur ni billet). */
export default function PublicTrackPage() {
  const { code } = useParams();
  const { data, error, loading, reload } = useLoad(() => get<Pub>(`/public/track/${code}/`), [code]);

  useEffect(() => { const id = setInterval(reload, 15_000); return () => clearInterval(id); }, [reload]);
  useEffect(() => { document.title = data ? `Suivi ${data.origin} → ${data.destination}` : "Suivi du bus"; }, [data]);

  const markers = useMemo(() => (data?.position ? [{ id: "bus", lat: data.position.lat, lon: data.position.lon, label: "Bus", stale: !!data.stale }] : []), [data]);

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "background.default", py: { xs: 2, md: 5 } }}>
      <Container maxWidth="sm">
        <Typography variant="overline" color="primary" fontWeight={800}>Suivi du bus</Typography>
        {loading && !data ? <Loading /> : error && !data ? (
          <Alert severity="warning" sx={{ mt: 1 }}>Ce lien de suivi n'est pas valide ou n'est plus disponible.</Alert>
        ) : data && (
          <Stack spacing={2}>
            <Box>
              <Typography variant="h5" fontWeight={800}>{data.origin} → {data.destination}</Typography>
              <Typography color="text.secondary">{data.company} · départ {fmtDateTime(data.departure_at, data.timezone)}</Typography>
            </Box>
            <Stack direction="row" spacing={1}><Chip label={data.status_label} color={data.status === "CANCELLED" ? "error" : "primary"} /></Stack>
            {data.status === "COMPLETED" && <Alert severity="success">Ce voyage est terminé.</Alert>}
            {data.status === "CANCELLED" && <Alert severity="error">Ce voyage a été annulé. Contactez votre agence.</Alert>}
            {data.position ? (
              <>
                {data.stale && <Alert severity="warning">Signal faible : la dernière position date de {ago(data.position.recorded_at)}. Le bus est peut-être dans une zone sans réseau.</Alert>}
                <MapView markers={markers} trail={data.trail} height={380} fitKey="bus" />
                <Paper sx={{ p: 2 }}>
                  <Typography>Dernière position : <b>{ago(data.position.recorded_at)}</b></Typography>
                  {data.position.speed_kmh != null && <Typography color="text.secondary">Vitesse : {Math.round(data.position.speed_kmh)} km/h</Typography>}
                </Paper>
              </>
            ) : !["COMPLETED", "CANCELLED"].includes(data.status) && (
              <Alert severity="info">La position du bus n'est pas disponible pour le moment. Elle apparaîtra dès que le bus aura pris la route et que le suivi sera actif.</Alert>
            )}
            <Typography variant="caption" color="text.secondary">Cette page se met à jour automatiquement. Les positions peuvent avoir quelques minutes de retard.</Typography>
          </Stack>
        )}
      </Container>
    </Box>
  );
}
