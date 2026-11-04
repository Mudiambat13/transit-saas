import { useState } from "react";
import { Button, Card, CardContent, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Grid, IconButton, MenuItem, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Tooltip, Typography } from "@mui/material";
import BlockIcon from "@mui/icons-material/Block";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import AddIcon from "@mui/icons-material/Add";
import { ApiError, get, patch, post, type Page } from "../../services/api";
import { ConfirmDialog, EmptyState, ErrorBox, fmtDateTime, Loading, PageHeader, useLoad, useToast } from "../../components/common";
import { CrudPage } from "../../components/CrudPage";
import type { Plan, Tenant } from "../../types";

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <Card><CardContent>
      <Typography variant="body2" color="text.secondary">{label}</Typography>
      <Typography variant="h4" fontWeight={800}>{value}</Typography>
    </CardContent></Card>
  );
}

export function PlatformDashboard() {
  const { data, error, loading, reload } = useLoad(() => get("/platform/metrics/"));
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (loading || !data) return <Loading />;
  return (
    <>
      <PageHeader title="Tableau de bord plateforme" subtitle="Indicateurs globaux du SaaS" />
      <Grid container spacing={2}>
        {[["Compagnies", data.tenants.total], ["Actives", data.tenants.active], ["Suspendues", data.tenants.suspended], ["Utilisateurs", data.users],
          ["Voyages (mois)", data.trips_this_month], ["Billets (mois)", data.tickets_this_month], ["Embarquements (mois)", data.boardings_this_month]].map(([l, v]) => (
          <Grid item xs={6} md={3} key={l as string}><Stat label={l as string} value={v as number} /></Grid>
        ))}
      </Grid>
    </>
  );
}

const emptyForm = { name: "", slug: "", currency: "USD", timezone: "Africa/Lubumbashi", plan: "", admin_full_name: "", admin_email: "", admin_password: "" };

export function CompaniesPage() {
  const { data, error, loading, reload } = useLoad(() => get<Page<Tenant>>("/platform/tenants/"));
  const plans = useLoad(() => get<Plan[]>("/platform/plans/"));
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<Record<string, string>>(emptyForm);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [target, setTarget] = useState<Tenant | null>(null);
  const { toast, node } = useToast();

  const create = async () => {
    setErrs({});
    try {
      await post("/platform/tenants/", { ...form, plan: form.plan || undefined });
      toast.ok("Compagnie créée avec son administrateur initial.");
      setCreating(false); setForm(emptyForm); reload();
    } catch (e) {
      if (e instanceof ApiError) setErrs(e.fields);
      toast.fail(e);
    }
  };
  const toggle = async () => {
    if (!target) return;
    try {
      await post(`/platform/tenants/${target.id}/${target.status === "ACTIVE" ? "suspend" : "reactivate"}/`);
      toast.ok(target.status === "ACTIVE" ? "Compagnie suspendue." : "Compagnie réactivée.");
      setTarget(null); reload();
    } catch (e) { toast.fail(e); }
  };
  const planOptions = Array.isArray(plans.data) ? plans.data : (plans.data as any)?.results ?? [];
  const f = (name: string, label: string, extra: object = {}) => (
    <TextField label={label} size="small" value={form[name]} onChange={(e) => setForm({ ...form, [name]: e.target.value })} error={!!errs[name]} helperText={errs[name]} {...extra} />
  );

  return (
    <>
      <PageHeader title="Compagnies" subtitle="Chaque compagnie dispose d'un espace isolé" actions={<Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreating(true)}>Nouvelle compagnie</Button>} />
      <Paper>
        {error ? <ErrorBox message={error} onRetry={reload} /> : loading && !data ? <Loading /> : !data?.results.length ? <EmptyState text="Aucune compagnie." /> : (
          <Table size="small">
            <TableHead><TableRow><TableCell>Compagnie</TableCell><TableCell>Offre</TableCell><TableCell>Agences</TableCell><TableCell>Utilisateurs</TableCell><TableCell>Statut</TableCell><TableCell /></TableRow></TableHead>
            <TableBody>
              {data.results.map((t) => (
                <TableRow key={t.id} hover>
                  <TableCell><b>{t.name}</b><br /><Typography variant="caption" color="text.secondary">{t.slug}</Typography></TableCell>
                  <TableCell>{t.plan_name ?? "—"}</TableCell><TableCell>{t.counts.agencies}</TableCell><TableCell>{t.counts.users}</TableCell>
                  <TableCell><Chip size="small" color={t.status === "ACTIVE" ? "success" : "warning"} label={t.status === "ACTIVE" ? "Active" : "Suspendue"} /></TableCell>
                  <TableCell align="right">
                    <Tooltip title={t.status === "ACTIVE" ? "Suspendre" : "Réactiver"}>
                      <IconButton onClick={() => setTarget(t)} color={t.status === "ACTIVE" ? "warning" : "success"}>{t.status === "ACTIVE" ? <BlockIcon /> : <CheckCircleIcon />}</IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Paper>

      <Dialog open={creating} onClose={() => setCreating(false)} fullWidth maxWidth="sm">
        <DialogTitle>Nouvelle compagnie</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            {f("name", "Nom commercial", { required: true })}
            {f("slug", "Identifiant (slug)", { required: true, helperText: errs.slug ?? "Lettres minuscules, chiffres et tirets" })}
            <Stack direction="row" spacing={2}>{f("currency", "Devise", { sx: { flex: 1 } })}{f("timezone", "Fuseau horaire", { sx: { flex: 2 } })}</Stack>
            {f("plan", "Offre", { select: true, children: [<MenuItem key="" value="">Aucune</MenuItem>, ...planOptions.map((p: Plan) => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)] })}
            <Typography variant="subtitle2" sx={{ pt: 1 }}>Administrateur initial</Typography>
            {f("admin_full_name", "Nom complet")}
            {f("admin_email", "E-mail", { type: "email", required: true })}
            {f("admin_password", "Mot de passe provisoire", { type: "password", required: true })}
          </Stack>
        </DialogContent>
        <DialogActions><Button onClick={() => setCreating(false)}>Annuler</Button><Button variant="contained" onClick={create}>Créer</Button></DialogActions>
      </Dialog>

      <ConfirmDialog open={!!target} danger={target?.status === "ACTIVE"} title={target?.status === "ACTIVE" ? "Suspendre la compagnie ?" : "Réactiver la compagnie ?"}
        text={target?.status === "ACTIVE" ? `${target?.name} ne pourra plus se connecter ni vendre de billets tant qu'elle est suspendue.` : `${target?.name} retrouvera l'accès à son espace.`}
        confirmLabel={target?.status === "ACTIVE" ? "Suspendre" : "Réactiver"} onClose={() => setTarget(null)} onConfirm={toggle} />
      {node}
    </>
  );
}

export function PlansPage() {
  return (
    <CrudPage<Plan> title="Offres et limites" subtitle="0 = illimité" endpoint="/platform/plans/" canEdit newLabel="Nouvelle offre"
      columns={[
        { header: "Offre", render: (p) => <b>{p.name}</b> }, { header: "Prix", render: (p) => `${p.price} ${p.currency}` },
        { header: "Agences", render: (p) => p.max_agencies || "∞" }, { header: "Utilisateurs", render: (p) => p.max_users || "∞" },
        { header: "Voyages/mois", render: (p) => p.max_trips_per_month || "∞" }, { header: "Billets/mois", render: (p) => p.max_tickets_per_month || "∞" },
      ]}
      fields={[
        { name: "name", label: "Nom", required: true }, { name: "price", label: "Prix", type: "number" }, { name: "currency", label: "Devise" },
        { name: "max_agencies", label: "Agences max", type: "number" }, { name: "max_users", label: "Utilisateurs max", type: "number" },
        { name: "max_trips_per_month", label: "Voyages max / mois", type: "number" }, { name: "max_tickets_per_month", label: "Billets max / mois", type: "number" },
      ]} />
  );
}

export function PlatformAuditPage() {
  const { data, error, loading, reload } = useLoad(() => get<any[]>("/platform/audit/"));
  return (
    <>
      <PageHeader title="Journal d'administration" subtitle="Actions sensibles sur la plateforme" />
      <Paper>
        {error ? <ErrorBox message={error} onRetry={reload} /> : loading ? <Loading /> : !data?.length ? <EmptyState text="Aucun événement." /> : (
          <Table size="small">
            <TableHead><TableRow><TableCell>Date</TableCell><TableCell>Action</TableCell><TableCell>Compagnie</TableCell><TableCell>Acteur</TableCell></TableRow></TableHead>
            <TableBody>{data.map((r) => <TableRow key={r.id}><TableCell>{fmtDateTime(r.created_at)}</TableCell><TableCell>{r.action}</TableCell><TableCell>{r.tenant ?? "—"}</TableCell><TableCell>{r.actor ?? "—"}</TableCell></TableRow>)}</TableBody>
          </Table>
        )}
      </Paper>
    </>
  );
}

// `patch` est volontairement importé pour d'éventuelles éditions inline futures.
void patch;
