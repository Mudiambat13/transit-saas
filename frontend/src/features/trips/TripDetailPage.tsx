import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Alert, Box, Button, Card, CardContent, Chip, Grid, LinearProgress, Paper, Stack, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs, TextField, Typography } from "@mui/material";
import PictureAsPdfIcon from "@mui/icons-material/PictureAsPdf";
import { get, openPdf, post, type Page } from "../../services/api";
import { useAuth } from "../../services/auth";
import { ConfirmDialog, EmptyState, ErrorBox, fmtDateTime, fmtMoney, Loading, PageHeader, StatusChip, useLoad, useToast } from "../../components/common";
import type { ManifestRow, Ticket, Trip } from "../../types";

type Act = { key: string; label: string; endpoint: string; show: (s: string) => boolean; perm: string; danger?: boolean; needsReason?: boolean; confirm: string; variant?: "contained" | "outlined" };

const ACTIONS: Act[] = [
  { key: "open", label: "Ouvrir à la vente", endpoint: "open-sales", show: (s) => s === "DRAFT" || s === "SUSPENDED", perm: "trip.manage", confirm: "Les agents pourront vendre des billets pour ce voyage.", variant: "contained" },
  { key: "suspend", label: "Suspendre la vente", endpoint: "suspend", show: (s) => s === "OPEN", perm: "trip.manage", confirm: "La vente sera suspendue jusqu'à réouverture.", variant: "outlined" },
  { key: "board", label: "Démarrer l'embarquement", endpoint: "start-boarding", show: (s) => s === "OPEN", perm: "trip.manage", confirm: "Le scan des billets sera activé.", variant: "contained" },
  { key: "close", label: "Clôturer l'embarquement", endpoint: "close-boarding", show: (s) => s === "BOARDING", perm: "manifest.finalize", confirm: "Les scans seront bloqués et le manifeste définitif sera figé et archivé à votre nom. Cette action est tracée.", variant: "contained" },
  { key: "complete", label: "Marquer comme terminé", endpoint: "complete", show: (s) => s === "CLOSED", perm: "trip.manage", confirm: "Le voyage sera marqué comme terminé.", variant: "outlined" },
  { key: "reopen", label: "Rouvrir (exceptionnel)", endpoint: "reopen", show: (s) => s === "CLOSED", perm: "trip.reopen", danger: true, needsReason: true, confirm: "Procédure exceptionnelle : un motif est obligatoire et la réouverture est journalisée. Une nouvelle clôture produira une nouvelle version du manifeste.", variant: "outlined" },
  { key: "cancel", label: "Annuler le voyage", endpoint: "cancel", show: (s) => ["DRAFT", "OPEN", "SUSPENDED"].includes(s), perm: "trip.manage", danger: true, confirm: "Le voyage sera annulé.", variant: "outlined" },
];

export default function TripDetailPage() {
  const { id } = useParams();
  const { me, can } = useAuth();
  const tz = me?.tenant?.timezone;
  const trip = useLoad(() => get<Trip>(`/trips/${id}/`), [id]);
  const stats = useLoad(() => (can("report.view") ? get<any>(`/trips/${id}/stats/`) : Promise.resolve(null)), [id, trip.data?.status]);
  const [tab, setTab] = useState(0);
  const [act, setAct] = useState<Act | null>(null);
  const [reason, setReason] = useState("");
  const { toast, node } = useToast();

  if (trip.error) return <ErrorBox message={trip.error} onRetry={trip.reload} />;
  if (trip.loading && !trip.data) return <Loading />;
  const t = trip.data!;
  const run = async () => {
    if (!act) return;
    if (act.needsReason && reason.trim().length < 5) { toast.fail(new Error("Motif trop court")); return; }
    try {
      await post(`/trips/${t.id}/${act.endpoint}/`, act.needsReason ? { reason } : {});
      toast.ok("Action effectuée.");
      setAct(null); setReason(""); trip.reload(); stats.reload();
    } catch (e) { toast.fail(e); }
  };

  return (
    <>
      <PageHeader title={`${t.reference} · ${t.origin} → ${t.destination}`} subtitle={`${fmtDateTime(t.departure_at, tz)} · ${t.agency_name} · Bus ${t.bus_plate}`}
        actions={<StatusChip status={t.status} label={t.status_label} />} />
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 2 }}>
        {ACTIONS.filter((a) => a.show(t.status) && can(a.perm)).map((a) => (
          <Button key={a.key} variant={a.variant} color={a.danger ? "error" : "primary"} onClick={() => setAct(a)}>{a.label}</Button>
        ))}
        {can("ticket.create") && ["OPEN", "BOARDING"].includes(t.status) && <Button component={Link} to={`/tickets/new?trip=${t.id}`} variant="contained" color="success">Vendre un billet</Button>}
        {can("boarding.scan") && t.status === "BOARDING" && <Button component={Link} to={`/boarding?trip=${t.id}`} variant="contained" color="secondary">Ouvrir le scanner</Button>}
      </Stack>
      {t.status === "CLOSED" && <Alert severity="success" sx={{ mb: 2 }}>Embarquement clôturé. Le manifeste définitif est archivé (onglet Manifestes).</Alert>}

      <Grid container spacing={2} sx={{ mb: 2 }}>
        {[["Prix", fmtMoney(t.price, t.currency)], ["Capacité", t.capacity], ["Vendus", stats.data?.sold ?? t.sold], ["Places restantes", stats.data?.remaining ?? Math.max(t.capacity - t.sold, 0)],
          ...(stats.data ? [["Embarqués", stats.data.boarded], ["Absents (si clôture maintenant)", stats.data.absent]] : [])].map(([l, v]) => (
          <Grid item xs={6} md={2} key={l as string}><Card><CardContent sx={{ py: 1.5 }}><Typography variant="caption" color="text.secondary">{l}</Typography><Typography variant="h6" fontWeight={800}>{v}</Typography></CardContent></Card></Grid>
        ))}
      </Grid>
      {stats.data && <Box sx={{ mb: 2 }}><LinearProgress variant="determinate" value={Math.min(100, stats.data.fill_rate)} sx={{ height: 8, borderRadius: 4 }} /><Typography variant="caption" color="text.secondary">Remplissage : {stats.data.fill_rate} %</Typography></Box>}
      {t.drivers_detail.length > 0 && <Typography variant="body2" sx={{ mb: 1 }}>Chauffeur(s) : {t.drivers_detail.map((d) => <Chip key={d.id} size="small" label={d.full_name} sx={{ mr: 0.5 }} />)}</Typography>}

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 1 }}>
        {can("ticket.view") && <Tab label="Billets" />}
        {can("manifest.view") && <Tab label="Manifestes" />}
        {can("boarding.view") && <Tab label="Embarquement" />}
      </Tabs>
      <TabContent tab={tab} trip={t} can={can} tz={tz} onChanged={() => { trip.reload(); stats.reload(); }} toast={toast} />
      <ConfirmDialog open={!!act} danger={act?.danger} title={act?.label ?? ""} text={act?.confirm} confirmLabel={act?.label} onClose={() => { setAct(null); setReason(""); }} onConfirm={run}>
        {act?.needsReason && <TextField autoFocus fullWidth size="small" label="Motif (obligatoire)" value={reason} onChange={(e) => setReason(e.target.value)} sx={{ mt: 1 }} />}
      </ConfirmDialog>
      {node}
    </>
  );
}

function TabContent({ tab, trip, can, tz, onChanged, toast }: { tab: number; trip: Trip; can: (p: string) => boolean; tz?: string; onChanged: () => void; toast: ReturnType<typeof useToast>["toast"] }) {
  const tabs = [can("ticket.view") && "tickets", can("manifest.view") && "manifests", can("boarding.view") && "boarding"].filter(Boolean) as string[];
  const which = tabs[tab];
  if (which === "tickets") return <TripTickets trip={trip} tz={tz} />;
  if (which === "manifests") return <TripManifests trip={trip} can={can} toast={toast} onChanged={onChanged} />;
  if (which === "boarding") return <TripBoarding trip={trip} tz={tz} />;
  return null;
}

function TripTickets({ trip, tz }: { trip: Trip; tz?: string }) {
  const { data, error, loading, reload } = useLoad(() => get<Page<Ticket>>("/tickets/", { trip: trip.id, ordering: "-created_at" }), [trip.id, trip.sold]);
  return (
    <Paper>
      {error ? <ErrorBox message={error} onRetry={reload} /> : loading && !data ? <Loading /> : !data?.results.length ? <EmptyState text="Aucun billet vendu." /> : (
        <Table size="small">
          <TableHead><TableRow><TableCell>Référence</TableCell><TableCell>Passager</TableCell><TableCell>Siège</TableCell><TableCell>Prix</TableCell><TableCell>Émis le</TableCell><TableCell>Statut</TableCell></TableRow></TableHead>
          <TableBody>{data.results.map((k) => (
            <TableRow key={k.id}><TableCell><b>{k.reference}</b></TableCell><TableCell>{k.passenger_name}</TableCell><TableCell>{k.seat_code ?? "—"}</TableCell><TableCell>{fmtMoney(k.price, k.currency)}</TableCell><TableCell>{fmtDateTime(k.created_at, tz)}</TableCell>
              <TableCell>{k.status === "CANCELLED" ? <Chip size="small" color="error" label="Annulé" /> : k.boarded ? <Chip size="small" color="success" label="Embarqué" /> : <Chip size="small" label="Valide" />}</TableCell></TableRow>
          ))}</TableBody>
        </Table>
      )}
    </Paper>
  );
}

function TripManifests({ trip, can, toast, onChanged }: { trip: Trip; can: (p: string) => boolean; toast: ReturnType<typeof useToast>["toast"]; onChanged: () => void }) {
  const { data, error, loading, reload } = useLoad(() => get<ManifestRow[]>(`/trips/${trip.id}/manifests/`), [trip.id, trip.status]);
  const gen = async () => {
    try { const m = await post<ManifestRow>(`/trips/${trip.id}/manifests/preview/`); toast.ok(`Manifeste ${m.number} généré.`); reload(); onChanged(); openPdf(`/manifests/${m.id}/pdf/`); }
    catch (e) { toast.fail(e); }
  };
  return (
    <Paper>
      {can("manifest.generate") && trip.status !== "CLOSED" && trip.status !== "COMPLETED" && (
        <Stack p={2}><Box><Button variant="contained" onClick={gen}>Générer le manifeste prévisionnel</Button></Box></Stack>
      )}
      {error ? <ErrorBox message={error} onRetry={reload} /> : loading && !data ? <Loading /> : !data?.length ? <EmptyState text="Aucun manifeste généré." /> : (
        <Table size="small">
          <TableHead><TableRow><TableCell>N°</TableCell><TableCell>Type</TableCell><TableCell>Version</TableCell><TableCell>Statut</TableCell><TableCell>Généré par</TableCell><TableCell>Date</TableCell><TableCell /></TableRow></TableHead>
          <TableBody>{data.map((m) => (
            <TableRow key={m.id}><TableCell><b>{m.number}</b></TableCell><TableCell><Chip size="small" color={m.type === "FINAL" ? "primary" : "default"} label={m.type_label} /></TableCell><TableCell>{m.version}</TableCell><TableCell>{m.status_label}</TableCell><TableCell>{m.created_by_name ?? "—"}</TableCell><TableCell>{fmtDateTime(m.created_at)}</TableCell>
              <TableCell align="right"><Button size="small" startIcon={<PictureAsPdfIcon />} onClick={() => openPdf(`/manifests/${m.id}/pdf/`).catch(toast.fail)}>PDF</Button></TableCell></TableRow>
          ))}</TableBody>
        </Table>
      )}
    </Paper>
  );
}

function TripBoarding({ trip, tz }: { trip: Trip; tz?: string }) {
  const { data, error, loading, reload } = useLoad(() => get<any>(`/trips/${trip.id}/boarding/`), [trip.id, trip.status]);
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (loading && !data) return <Loading />;
  return (
    <Paper>
      <Stack direction="row" spacing={2} p={2} alignItems="center">
        <Chip color="success" label={`Embarqués : ${data.totals.boarded}`} /><Chip label={`Restants : ${data.totals.remaining}`} /><Button size="small" onClick={reload}>Actualiser</Button>
      </Stack>
      {!data.passengers.length ? <EmptyState text="Aucun passager." /> : (
        <Table size="small">
          <TableHead><TableRow><TableCell>Siège</TableCell><TableCell>Passager</TableCell><TableCell>Référence</TableCell><TableCell>Statut</TableCell></TableRow></TableHead>
          <TableBody>{data.passengers.map((p: any) => (
            <TableRow key={p.ticket_id}><TableCell>{p.seat ?? "—"}</TableCell><TableCell>{p.passenger}</TableCell><TableCell>{p.reference}</TableCell>
              <TableCell>{p.boarded ? <Chip size="small" color="success" label={`Embarqué ${fmtDateTime(p.boarded_at, tz)}`} /> : <Chip size="small" label="En attente" />}</TableCell></TableRow>
          ))}</TableBody>
        </Table>
      )}
    </Paper>
  );
}
