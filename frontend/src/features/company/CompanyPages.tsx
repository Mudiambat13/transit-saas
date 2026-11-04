import { useEffect, useState } from "react";
import { Alert, Box, Button, Card, CardContent, Grid, LinearProgress, Paper, Stack, Switch, FormControlLabel, Table, TableBody, TableCell, TableHead, TableRow, Tab, Tabs, TextField, Typography } from "@mui/material";
import { Link } from "react-router-dom";
import { get, patch } from "../../services/api";
import { useAuth } from "../../services/auth";
import { CrudPage } from "../../components/CrudPage";
import { EmptyState, ErrorBox, fmtDateTime, fmtMoney, Loading, PageHeader, StatusChip, useLoad, useToast } from "../../components/common";
import type { Agency, Bus, Driver } from "../../types";

export function DashboardPage() {
  const { me } = useAuth();
  const { data, error, loading, reload } = useLoad(() => get("/reports/dashboard/"));
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (loading || !data) return <Loading />;
  const stats: [string, string | number][] = [
    ["Voyages ouverts", data.trips.open], ["En embarquement", data.trips.boarding], ["Billets aujourd'hui", data.tickets_today],
    ["Billets ce mois", data.tickets_month], ["Annulations (mois)", data.cancelled_month],
  ];
  return (
    <>
      <PageHeader title={`Bonjour${me?.full_name ? `, ${me.full_name}` : ""}`} subtitle={me?.tenant?.name} />
      <Grid container spacing={2} sx={{ mb: 3 }}>
        {stats.map(([l, v]) => (
          <Grid item xs={6} md={2.4} key={l}><Card><CardContent><Typography variant="body2" color="text.secondary">{l}</Typography><Typography variant="h4" fontWeight={800}>{v}</Typography></CardContent></Card></Grid>
        ))}
      </Grid>
      {data.revenue_month.length > 0 && (
        <Alert severity="info" sx={{ mb: 3 }}>Ventes du mois : {data.revenue_month.map((r: any) => fmtMoney(r.total, r.currency)).join(" · ")}</Alert>
      )}
      <Typography variant="h6" fontWeight={700} sx={{ mb: 1 }}>Prochains départs</Typography>
      <Paper>
        {!data.upcoming.length ? <EmptyState text="Aucun voyage à venir." /> : (
          <Table size="small">
            <TableHead><TableRow><TableCell>Voyage</TableCell><TableCell>Itinéraire</TableCell><TableCell>Départ</TableCell><TableCell>Remplissage</TableCell><TableCell>Statut</TableCell></TableRow></TableHead>
            <TableBody>
              {data.upcoming.map((t: any) => (
                <TableRow key={t.id} hover>
                  <TableCell><Link to={`/trips/${t.id}`}>{t.reference}</Link></TableCell><TableCell>{t.route}</TableCell>
                  <TableCell>{fmtDateTime(t.departure_at, me?.tenant?.timezone)}</TableCell>
                  <TableCell sx={{ minWidth: 150 }}><Box sx={{ display: "flex", alignItems: "center", gap: 1 }}><LinearProgress variant="determinate" value={Math.min(100, (100 * t.sold) / t.capacity)} sx={{ flex: 1, height: 8, borderRadius: 4 }} /><Typography variant="caption">{t.sold}/{t.capacity}</Typography></Box></TableCell>
                  <TableCell><StatusChip status={t.status} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Paper>
    </>
  );
}

export function AgenciesPage() {
  const { can } = useAuth();
  return (
    <CrudPage<Agency> title="Agences" endpoint="/agencies/" canEdit={can("agency.manage")} newLabel="Nouvelle agence"
      columns={[{ header: "Nom", render: (a) => <b>{a.name}</b> }, { header: "Ville", render: (a) => a.city }, { header: "Téléphone", render: (a) => a.phone || "—" }, { header: "Statut", render: (a) => (a.is_active ? "Active" : "Inactive") }]}
      fields={[{ name: "name", label: "Nom de l'agence", required: true }, { name: "city", label: "Ville", required: true }, { name: "address", label: "Adresse" }, { name: "phone", label: "Téléphone" }, { name: "is_active", label: "Agence active", type: "switch" }]} />
  );
}

export function FleetPage() {
  const { can } = useAuth();
  const [tab, setTab] = useState(0);
  const edit = can("fleet.manage");
  return (
    <>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}><Tab label="Bus" /><Tab label="Chauffeurs" /></Tabs>
      {tab === 0 ? (
        <CrudPage<Bus> key="bus" title="Bus" subtitle="Les sièges sont générés automatiquement selon la capacité" endpoint="/buses/" canEdit={edit} newLabel="Nouveau bus"
          columns={[{ header: "Immatriculation", render: (b) => <b>{b.plate}</b> }, { header: "Marque / modèle", render: (b) => `${b.brand} ${b.model}`.trim() || "—" }, { header: "Capacité", render: (b) => b.capacity }, { header: "État", render: (b) => b.status }]}
          fields={[{ name: "plate", label: "Immatriculation", required: true }, { name: "brand", label: "Marque" }, { name: "model", label: "Modèle" }, { name: "capacity", label: "Capacité (places)", type: "number", required: true },
            { name: "status", label: "État", type: "select", options: [{ value: "ACTIVE", label: "En service" }, { value: "MAINTENANCE", label: "En maintenance" }, { value: "RETIRED", label: "Retiré" }] }]}
          toPayload={(f, isNew) => ({ ...f, capacity: Number(f.capacity), ...(isNew ? { status: f.status || "ACTIVE" } : {}) })} />
      ) : (
        <CrudPage<Driver> key="drv" title="Chauffeurs" endpoint="/drivers/" canEdit={edit} newLabel="Nouveau chauffeur"
          columns={[{ header: "Nom", render: (d) => <b>{d.full_name}</b> }, { header: "Téléphone", render: (d) => d.phone || "—" }, { header: "Permis", render: (d) => d.license_number || "—" }]}
          fields={[{ name: "full_name", label: "Nom complet", required: true }, { name: "phone", label: "Téléphone" }, { name: "license_number", label: "N° de permis" }, { name: "is_active", label: "Actif", type: "switch" }]} />
      )}
    </>
  );
}

const ROLES = [
  { value: "COMPANY_ADMIN", label: "Administrateur de compagnie" }, { value: "AGENCY_MANAGER", label: "Responsable d'agence" },
  { value: "TICKET_AGENT", label: "Agent de billetterie" }, { value: "BOARDING_AGENT", label: "Agent d'embarquement" }, { value: "DRIVER", label: "Chauffeur / contrôleur" },
];

export function UsersPage() {
  const agencies = useLoad(() => get<any>("/agencies/"));
  return (
    <CrudPage<any> title="Utilisateurs" subtitle="Les permissions sont appliquées côté serveur selon le rôle" endpoint="/users/" canEdit newLabel="Nouvel utilisateur"
      columns={[{ header: "Nom", render: (u) => <b>{u.full_name || "—"}</b> }, { header: "E-mail", render: (u) => u.email }, { header: "Rôle", render: (u) => ROLES.find((r) => r.value === u.role)?.label ?? "—" }, { header: "Statut", render: (u) => (u.is_active ? "Actif" : "Désactivé") }]}
      fields={[{ name: "full_name", label: "Nom complet" }, { name: "email", label: "E-mail", type: "email", required: true }, { name: "phone", label: "Téléphone" },
        { name: "role", label: "Rôle", type: "select", options: ROLES, required: true },
        { name: "agency", label: "Agence (périmètre)", type: "select", options: [{ value: "", label: "Toute la compagnie" }, ...((agencies.data?.results ?? []).map((a: Agency) => ({ value: a.id, label: a.name })))] },
        { name: "password", label: "Mot de passe", type: "password", helper: "Laisser vide pour ne pas le modifier" }, { name: "is_active", label: "Compte actif", type: "switch" }]}
      toPayload={(f, isNew) => {
        const p: any = { ...f, agency: f.agency === "" || f.agency == null ? null : f.agency };
        if (!p.password) delete p.password;
        if (!isNew) delete p.email;
        return p;
      }} />
  );
}

export function SettingsPage() {
  const { me } = useAuth();
  const { data, error, loading, reload } = useLoad(() => get<any>("/company/profile/"));
  const [form, setForm] = useState<any>(null);
  const { toast, node } = useToast();
  useEffect(() => { if (data) setForm(data); }, [data]);
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (loading || !form) return <Loading />;
  const set = (k: string, v: any) => setForm({ ...form, [k]: v });
  const setOpt = (k: string, v: boolean) => setForm({ ...form, settings: { ...(form.settings ?? {}), [k]: v } });
  const save = async () => {
    try {
      const { name, currency, timezone, contact_email, contact_phone, address, settings } = form;
      await patch("/company/profile/", { name, currency, timezone, contact_email, contact_phone, address, settings });
      toast.ok("Paramètres enregistrés. Reconnectez-vous pour les appliquer partout.");
    } catch (e) { toast.fail(e); }
  };
  return (
    <>
      <PageHeader title="Profil de la compagnie" subtitle={me?.tenant?.slug} />
      <Paper sx={{ p: 3, maxWidth: 640 }}>
        <Stack spacing={2}>
          <TextField label="Nom commercial" value={form.name} onChange={(e) => set("name", e.target.value)} size="small" />
          <Stack direction="row" spacing={2}>
            <TextField label="Devise" value={form.currency} onChange={(e) => set("currency", e.target.value.toUpperCase())} size="small" sx={{ flex: 1 }} inputProps={{ maxLength: 3 }} />
            <TextField label="Fuseau horaire" value={form.timezone} onChange={(e) => set("timezone", e.target.value)} size="small" sx={{ flex: 2 }} />
          </Stack>
          <TextField label="E-mail de contact" value={form.contact_email} onChange={(e) => set("contact_email", e.target.value)} size="small" />
          <TextField label="Téléphone" value={form.contact_phone} onChange={(e) => set("contact_phone", e.target.value)} size="small" />
          <TextField label="Adresse" value={form.address} onChange={(e) => set("address", e.target.value)} size="small" />
          <FormControlLabel label="Gestion des sièges (attribution à la vente)" control={<Switch checked={form.settings?.seat_selection !== false} onChange={(e) => setOpt("seat_selection", e.target.checked)} />} />
          <FormControlLabel label="Téléphone du passager obligatoire" control={<Switch checked={!!form.settings?.passenger_phone_required} onChange={(e) => setOpt("passenger_phone_required", e.target.checked)} />} />
          <Box><Button variant="contained" onClick={save}>Enregistrer</Button></Box>
        </Stack>
      </Paper>
      {node}
    </>
  );
}

export function AuditPage() {
  const { data, error, loading, reload } = useLoad(() => get<any[]>("/company/audit/"));
  return (
    <>
      <PageHeader title="Journal d'audit" subtitle="Annulations, validations, clôtures, réouvertures et connexions" />
      <Paper>
        {error ? <ErrorBox message={error} onRetry={reload} /> : loading ? <Loading /> : !data?.length ? <EmptyState text="Aucun événement." /> : (
          <Table size="small">
            <TableHead><TableRow><TableCell>Date</TableCell><TableCell>Action</TableCell><TableCell>Acteur</TableCell><TableCell>Détail</TableCell></TableRow></TableHead>
            <TableBody>{data.map((r) => <TableRow key={r.id}><TableCell>{fmtDateTime(r.created_at)}</TableCell><TableCell>{r.action}</TableCell><TableCell>{r.actor ?? "—"}</TableCell><TableCell sx={{ color: "text.secondary" }}>{Object.entries(r.metadata ?? {}).map(([k, v]) => `${k}: ${v}`).join(" · ")}</TableCell></TableRow>)}</TableBody>
          </Table>
        )}
      </Paper>
    </>
  );
}
