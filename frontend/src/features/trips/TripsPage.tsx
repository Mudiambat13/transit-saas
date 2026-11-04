import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Autocomplete, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Pagination, Paper, Stack, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, TextField,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import { ApiError, get, post, type Page } from "../../services/api";
import { useAuth } from "../../services/auth";
import { EmptyState, ErrorBox, fmtDateTime, fmtMoney, Loading, localInputToIso, PageHeader, StatusChip, useLoad, useToast } from "../../components/common";
import type { Agency, Bus, Driver, Trip } from "../../types";

const STATUSES = [["", "Tous"], ["DRAFT", "Brouillon"], ["OPEN", "Ouverts"], ["BOARDING", "Embarquement"], ["CLOSED", "Clôturés"], ["COMPLETED", "Terminés"], ["CANCELLED", "Annulés"]];

export default function TripsPage() {
  const { me, can } = useAuth();
  const tz = me?.tenant?.timezone;
  const nav = useNavigate();
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const { data, error, loading, reload } = useLoad(() => get<Page<Trip>>("/trips/", { status, search, page }), [status, search, page]);
  const [creating, setCreating] = useState(false);

  return (
    <>
      <PageHeader title="Voyages" actions={can("trip.manage") && <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreating(true)}>Nouveau voyage</Button>} />
      <Paper>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} p={2}>
          <TextField size="small" placeholder="Référence, ville…" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} sx={{ minWidth: 260 }} />
          <TextField size="small" select label="Statut" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} sx={{ minWidth: 180 }}>
            {STATUSES.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
          </TextField>
        </Stack>
        {error ? <ErrorBox message={error} onRetry={reload} /> : loading && !data ? <Loading /> : !data?.results.length ? <EmptyState text="Aucun voyage." /> : (
          <TableContainer>
            <Table size="small">
              <TableHead><TableRow><TableCell>Référence</TableCell><TableCell>Itinéraire</TableCell><TableCell>Départ</TableCell><TableCell>Bus</TableCell><TableCell>Prix</TableCell><TableCell>Vendus</TableCell><TableCell>Statut</TableCell></TableRow></TableHead>
              <TableBody>
                {data.results.map((t) => (
                  <TableRow key={t.id} hover sx={{ cursor: "pointer" }} onClick={() => nav(`/trips/${t.id}`)}>
                    <TableCell><Link to={`/trips/${t.id}`} onClick={(e) => e.stopPropagation()}><b>{t.reference}</b></Link></TableCell>
                    <TableCell>{t.origin} → {t.destination}</TableCell><TableCell>{fmtDateTime(t.departure_at, tz)}</TableCell>
                    <TableCell>{t.bus_plate}</TableCell><TableCell>{fmtMoney(t.price, t.currency)}</TableCell>
                    <TableCell>{t.sold}/{t.capacity}</TableCell><TableCell><StatusChip status={t.status} label={t.status_label} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {data.count > 25 && <Stack alignItems="center" p={2}><Pagination count={Math.ceil(data.count / 25)} page={page} onChange={(_, p) => setPage(p)} /></Stack>}
          </TableContainer>
        )}
      </Paper>
      <TripFormDialog open={creating} onClose={() => setCreating(false)} onSaved={(id) => { setCreating(false); nav(`/trips/${id}`); }} />
    </>
  );
}

function TripFormDialog({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: (id: number) => void }) {
  const { me } = useAuth();
  const tz = me?.tenant?.timezone ?? "UTC";
  const agencies = useLoad(() => get<Page<Agency>>("/agencies/"), []);
  const buses = useLoad(() => get<Page<Bus>>("/buses/"), []);
  const drivers = useLoad(() => get<Page<Driver>>("/drivers/"), []);
  const [form, setForm] = useState<Record<string, any>>({ origin: "", destination: "", departure: "", arrival: "", agency: me?.agency_id ?? "", bus: "", price: "", reference: "", notes: "" });
  const [driverSel, setDriverSel] = useState<Driver[]>([]);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const { toast, node } = useToast();
  const set = (k: string, v: any) => setForm({ ...form, [k]: v });

  const submit = async () => {
    setBusy(true); setErrs({});
    try {
      if (!form.departure) { setErrs({ departure_at: "La date de départ est obligatoire." }); return; }
      const t = await post<Trip>("/trips/", {
        reference: form.reference || undefined, agency: form.agency, origin: form.origin, destination: form.destination,
        departure_at: localInputToIso(form.departure, tz), arrival_estimated_at: form.arrival ? localInputToIso(form.arrival, tz) : null,
        bus: form.bus, price: form.price, currency: me?.tenant?.currency, notes: form.notes, driver_ids: driverSel.map((d) => d.id),
      });
      onSaved(t.id);
    } catch (e) {
      if (e instanceof ApiError) setErrs(e.fields);
      toast.fail(e);
    } finally { setBusy(false); }
  };

  const E = (k: string) => ({ error: !!errs[k], helperText: errs[k] });
  return (
    <Dialog open={open} onClose={() => !busy && onClose()} fullWidth maxWidth="sm">
      <DialogTitle>Nouveau voyage</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Stack direction="row" spacing={2}>
            <TextField label="Départ (ville)" size="small" required fullWidth value={form.origin} onChange={(e) => set("origin", e.target.value)} {...E("origin")} />
            <TextField label="Destination" size="small" required fullWidth value={form.destination} onChange={(e) => set("destination", e.target.value)} {...E("destination")} />
          </Stack>
          <Stack direction="row" spacing={2}>
            <TextField label={`Départ prévu (${tz})`} type="datetime-local" size="small" required fullWidth InputLabelProps={{ shrink: true }} value={form.departure} onChange={(e) => set("departure", e.target.value)} {...E("departure_at")} />
            <TextField label="Arrivée estimée" type="datetime-local" size="small" fullWidth InputLabelProps={{ shrink: true }} value={form.arrival} onChange={(e) => set("arrival", e.target.value)} {...E("arrival_estimated_at")} />
          </Stack>
          <TextField select label="Agence de départ" size="small" required value={form.agency} onChange={(e) => set("agency", e.target.value)} {...E("agency")} disabled={!!me?.agency_id}>
            {agencies.data?.results.filter((a) => a.is_active).map((a) => <MenuItem key={a.id} value={a.id}>{a.name} — {a.city}</MenuItem>)}
          </TextField>
          <TextField select label="Bus" size="small" required value={form.bus} onChange={(e) => set("bus", e.target.value)} {...E("bus")}
            helperText={errs.bus ?? "La capacité provient de la configuration du bus"}>
            {buses.data?.results.filter((b) => b.status === "ACTIVE").map((b) => <MenuItem key={b.id} value={b.id}>{b.plate} — {b.capacity} places</MenuItem>)}
          </TextField>
          <Autocomplete multiple size="small" options={drivers.data?.results ?? []} getOptionLabel={(d) => d.full_name} value={driverSel} onChange={(_, v) => setDriverSel(v)}
            renderTags={(v, getProps) => v.map((d, i) => <Chip size="small" label={d.full_name} {...getProps({ index: i })} key={d.id} />)}
            renderInput={(p) => <TextField {...p} label="Chauffeur(s)" />} />
          <Stack direction="row" spacing={2}>
            <TextField label={`Prix du billet (${me?.tenant?.currency})`} type="number" size="small" required fullWidth value={form.price} onChange={(e) => set("price", e.target.value)} {...E("price")} />
            <TextField label="Référence (auto si vide)" size="small" fullWidth value={form.reference} onChange={(e) => set("reference", e.target.value)} {...E("reference")} />
          </Stack>
          <TextField label="Notes internes" size="small" multiline minRows={2} value={form.notes} onChange={(e) => set("notes", e.target.value)} />
        </Stack>
      </DialogContent>
      <DialogActions><Button onClick={onClose} disabled={busy}>Annuler</Button><Button variant="contained" onClick={submit} disabled={busy}>Créer le voyage</Button></DialogActions>
      {node}
    </Dialog>
  );
}
