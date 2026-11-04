import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Alert, Box, Button, Chip, Grid, IconButton, MenuItem, Pagination, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, ToggleButton, ToggleButtonGroup, Tooltip, Typography } from "@mui/material";
import PrintIcon from "@mui/icons-material/Print";
import CancelIcon from "@mui/icons-material/Cancel";
import { ApiError, get, openPdf, post, type Page } from "../../services/api";
import { useAuth } from "../../services/auth";
import { ConfirmDialog, EmptyState, ErrorBox, fmtDateTime, fmtMoney, Loading, PageHeader, useLoad, useToast } from "../../components/common";
import type { SeatInfo, Ticket, Trip } from "../../types";

export function TicketsPage() {
  const { me, can } = useAuth();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const { data, error, loading, reload } = useLoad(() => get<Page<Ticket>>("/tickets/", { search, page }), [search, page]);
  const [cancelTarget, setCancelTarget] = useState<Ticket | null>(null);
  const [reason, setReason] = useState("");
  const { toast, node } = useToast();

  const cancel = async () => {
    if (!cancelTarget) return;
    try { await post(`/tickets/${cancelTarget.id}/cancel/`, { reason }); toast.ok("Billet annulé."); setCancelTarget(null); setReason(""); reload(); }
    catch (e) { toast.fail(e); }
  };

  return (
    <>
      <PageHeader title="Billets" subtitle="Recherche par nom, téléphone, référence ou voyage" actions={can("ticket.create") && <Button component={Link} to="/tickets/new" variant="contained">Vendre un billet</Button>} />
      <Paper>
        <Stack p={2}><TextField size="small" placeholder="Nom, téléphone, référence…" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} sx={{ maxWidth: 380 }} /></Stack>
        {error ? <ErrorBox message={error} onRetry={reload} /> : loading && !data ? <Loading /> : !data?.results.length ? <EmptyState text="Aucun billet trouvé." /> : (
          <TableContainer>
            <Table size="small">
              <TableHead><TableRow><TableCell>Référence</TableCell><TableCell>Passager</TableCell><TableCell>Voyage</TableCell><TableCell>Siège</TableCell><TableCell>Prix</TableCell><TableCell>Émis le</TableCell><TableCell>Statut</TableCell><TableCell /></TableRow></TableHead>
              <TableBody>{data.results.map((k) => (
                <TableRow key={k.id} hover>
                  <TableCell><b>{k.reference}</b></TableCell><TableCell>{k.passenger_name}<br /><Typography variant="caption" color="text.secondary">{k.passenger_phone}</Typography></TableCell>
                  <TableCell><Link to={`/trips/${k.trip}`}>{k.trip_reference}</Link><br /><Typography variant="caption" color="text.secondary">{k.route}</Typography></TableCell>
                  <TableCell>{k.seat_code ?? "—"}</TableCell><TableCell>{fmtMoney(k.price, k.currency)}</TableCell><TableCell>{fmtDateTime(k.created_at, me?.tenant?.timezone)}</TableCell>
                  <TableCell>{k.status === "CANCELLED" ? <Chip size="small" color="error" label="Annulé" /> : k.boarded ? <Chip size="small" color="success" label="Embarqué" /> : <Chip size="small" label="Valide" />}</TableCell>
                  <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                    {can("ticket.reprint") && <Tooltip title="Imprimer / PDF"><IconButton size="small" onClick={() => openPdf(`/tickets/${k.id}/pdf/`).catch(toast.fail)}><PrintIcon fontSize="small" /></IconButton></Tooltip>}
                    {can("ticket.cancel") && k.status === "ACTIVE" && !k.boarded && <Tooltip title="Annuler"><IconButton size="small" color="error" onClick={() => setCancelTarget(k)}><CancelIcon fontSize="small" /></IconButton></Tooltip>}
                  </TableCell>
                </TableRow>
              ))}</TableBody>
            </Table>
            {data.count > 25 && <Stack alignItems="center" p={2}><Pagination count={Math.ceil(data.count / 25)} page={page} onChange={(_, p) => setPage(p)} /></Stack>}
          </TableContainer>
        )}
      </Paper>
      <ConfirmDialog open={!!cancelTarget} danger title={`Annuler ${cancelTarget?.reference}`} text="Le billet ne sera plus valable à l'embarquement et son siège sera libéré. L'annulation est tracée." confirmLabel="Annuler le billet" onClose={() => setCancelTarget(null)} onConfirm={cancel}>
        <TextField autoFocus fullWidth size="small" label="Motif (obligatoire)" value={reason} onChange={(e) => setReason(e.target.value)} sx={{ mt: 1 }} />
      </ConfirmDialog>
      {node}
    </>
  );
}

export function SellTicketPage() {
  const { me } = useAuth();
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const tripId = params.get("trip") ?? "";
  const trips = useLoad(() => get<Page<Trip>>("/trips/", { sellable: 1, ordering: "departure_at" }), []);
  const seats = useLoad(() => (tripId ? get<SeatInfo>(`/trips/${tripId}/available-seats/`) : Promise.resolve(null)), [tripId]);
  const trip = trips.data?.results.find((t) => String(t.id) === tripId);
  const [form, setForm] = useState({ full_name: "", phone: "", id_type: "", id_number: "", price: "", payment_method: "CASH", payment_reference: "" });
  const [seat, setSeat] = useState<number | null>(null);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [issued, setIssued] = useState<Ticket | null>(null);
  const { toast, node } = useToast();
  useEffect(() => { setSeat(null); if (trip) setForm((f) => ({ ...f, price: trip.price })); }, [tripId, trip?.price]);
  const set = (k: string, v: string) => setForm({ ...form, [k]: v });

  const submit = async () => {
    setBusy(true); setErrs({});
    try {
      const t = await post<Ticket>("/tickets/", { trip: Number(tripId), ...form, price: form.price || null, seat });
      setIssued(t); toast.ok("Billet émis."); seats.reload();
      openPdf(`/tickets/${t.id}/pdf/`).catch(() => undefined);
    } catch (e) {
      if (e instanceof ApiError) setErrs(e.fields);
      toast.fail(e); seats.reload();
    } finally { setBusy(false); }
  };
  const reset = () => { setIssued(null); setForm({ ...form, full_name: "", phone: "", id_type: "", id_number: "", payment_reference: "" }); setSeat(null); };

  if (trips.loading && !trips.data) return <Loading />;
  const E = (k: string) => ({ error: !!errs[k], helperText: errs[k] });
  const cur = trip?.currency ?? me?.tenant?.currency;

  return (
    <>
      <PageHeader title="Vente d'un billet" subtitle="Guichet" />
      {issued && (
        <Alert severity="success" sx={{ mb: 2 }} action={<Stack direction="row" spacing={1}><Button color="inherit" size="small" onClick={() => openPdf(`/tickets/${issued.id}/pdf/`)}>Réimprimer</Button><Button color="inherit" size="small" onClick={reset}>Nouveau billet</Button></Stack>}>
          Billet <b>{issued.reference}</b> émis pour {issued.passenger_name} — siège {issued.seat_code ?? "non attribué"}.
        </Alert>
      )}
      <Grid container spacing={2}>
        <Grid item xs={12} md={7}>
          <Paper sx={{ p: 2.5 }}>
            <Stack spacing={2}>
              <TextField select size="small" label="Voyage" value={tripId} onChange={(e) => { setParams({ trip: e.target.value }); setIssued(null); }}>
                {trips.data?.results.map((t) => <MenuItem key={t.id} value={String(t.id)}>{t.reference} · {t.origin} → {t.destination} · {fmtDateTime(t.departure_at, me?.tenant?.timezone)} ({t.capacity - t.sold} places)</MenuItem>)}
              </TextField>
              {!trips.data?.results.length && <Alert severity="info">Aucun voyage ouvert à la vente.</Alert>}
              <TextField label="Nom complet du passager" size="small" required value={form.full_name} onChange={(e) => set("full_name", e.target.value)} {...E("full_name")} />
              <Stack direction="row" spacing={2}>
                <TextField label="Téléphone" size="small" fullWidth value={form.phone} onChange={(e) => set("phone", e.target.value)} {...E("phone")} required={!!me?.tenant?.settings?.passenger_phone_required} />
              </Stack>
              <Stack direction="row" spacing={2}>
                <TextField label="Type de pièce (facultatif)" size="small" fullWidth value={form.id_type} onChange={(e) => set("id_type", e.target.value)} />
                <TextField label="N° de pièce (facultatif)" size="small" fullWidth value={form.id_number} onChange={(e) => set("id_number", e.target.value)} />
              </Stack>
              <Stack direction="row" spacing={2}>
                <TextField label={`Prix (${cur})`} type="number" size="small" fullWidth value={form.price} onChange={(e) => set("price", e.target.value)} {...E("price")} />
                <TextField select label="Paiement" size="small" fullWidth value={form.payment_method} onChange={(e) => set("payment_method", e.target.value)}>
                  {[["CASH", "Espèces"], ["MOBILE_MONEY", "Mobile money"], ["CARD", "Carte"], ["BANK", "Virement"], ["OTHER", "Autre"]].map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
                </TextField>
              </Stack>
              <TextField label="Référence de paiement (facultatif)" size="small" value={form.payment_reference} onChange={(e) => set("payment_reference", e.target.value)} />
              <Box><Button variant="contained" size="large" disabled={busy || !tripId || !form.full_name.trim()} onClick={submit}>{busy ? "Émission…" : "Émettre le billet"}</Button></Box>
            </Stack>
          </Paper>
        </Grid>
        <Grid item xs={12} md={5}>
          <Paper sx={{ p: 2.5 }}>
            <Typography fontWeight={700} sx={{ mb: 1 }}>Sièges {seats.data ? `· ${seats.data.remaining} libre(s) sur ${seats.data.capacity}` : ""}</Typography>
            {!tripId ? <Typography color="text.secondary">Choisissez un voyage.</Typography> : seats.loading && !seats.data ? <Loading /> : seats.error ? <ErrorBox message={seats.error} onRetry={seats.reload} /> : seats.data && (
              seats.data.seat_selection ? (
                <>
                  <Typography variant="caption" color="text.secondary">Sans choix, le premier siège libre est attribué automatiquement.</Typography>
                  <ToggleButtonGroup exclusive value={seat} onChange={(_, v) => setSeat(v)} sx={{ display: "flex", flexWrap: "wrap", gap: 0.75, mt: 1 }}>
                    {seats.data.seats.slice(0, seats.data.capacity).map((s) => (
                      <ToggleButton key={s.id} value={s.id} disabled={!s.available} size="small" sx={{ width: 46, borderRadius: "8px !important", border: "1px solid #cbd5e1 !important" }}>{s.code}</ToggleButton>
                    ))}
                  </ToggleButtonGroup>
                </>
              ) : <Typography color="text.secondary">La gestion des sièges est désactivée pour cette compagnie.</Typography>
            )}
          </Paper>
        </Grid>
      </Grid>
      {node}
      <span hidden>{nav.name}</span>
    </>
  );
}
