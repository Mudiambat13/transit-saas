import { useState, type ReactNode } from "react";
import {
  Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, MenuItem, Paper, Stack, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, TextField, InputAdornment, Pagination, FormControlLabel, Switch,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import EditIcon from "@mui/icons-material/Edit";
import SearchIcon from "@mui/icons-material/Search";
import { ApiError, get, patch, post, type Page } from "../services/api";
import { EmptyState, ErrorBox, Loading, PageHeader, useLoad, useToast } from "./common";

export interface FieldDef {
  name: string;
  label: string;
  type?: "text" | "number" | "select" | "email" | "password" | "switch";
  options?: { value: string | number; label: string }[];
  required?: boolean;
  createOnly?: boolean;
  helper?: string;
}
export interface ColumnDef<T> { header: string; render: (row: T) => ReactNode }

/** Page de gestion générique : liste paginée avec recherche + création / modification en boîte de dialogue. */
export function CrudPage<T extends { id: number }>({ title, subtitle, endpoint, columns, fields, canEdit, newLabel, toForm, toPayload }: {
  title: string; subtitle?: string; endpoint: string; columns: ColumnDef<T>[]; fields: FieldDef[]; canEdit: boolean; newLabel: string;
  toForm?: (row: T) => Record<string, any>; toPayload?: (form: Record<string, any>, editing: boolean) => Record<string, any>;
}) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const { data, error, loading, reload } = useLoad(() => get<Page<T>>(endpoint, { search, page }), [endpoint, search, page]);
  const [editing, setEditing] = useState<T | "new" | null>(null);
  const [form, setForm] = useState<Record<string, any>>({});
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const { toast, node } = useToast();

  const open = (row: T | "new") => {
    setErrs({});
    setForm(row === "new" ? Object.fromEntries(fields.filter((f) => f.type === "switch").map((f) => [f.name, true])) : toForm ? toForm(row) : { ...(row as any) });
    setEditing(row);
  };

  const submit = async () => {
    setBusy(true); setErrs({});
    try {
      const isNew = editing === "new";
      const payload = toPayload ? toPayload(form, isNew) : form;
      if (isNew) await post(endpoint, payload); else await patch(`${endpoint}${(editing as T).id}/`, payload);
      toast.ok(isNew ? "Créé avec succès." : "Modifications enregistrées.");
      setEditing(null); reload();
    } catch (e) {
      if (e instanceof ApiError && Object.keys(e.fields).length) setErrs(e.fields);
      toast.fail(e);
    } finally { setBusy(false); }
  };

  return (
    <>
      <PageHeader title={title} subtitle={subtitle} actions={canEdit && <Button variant="contained" startIcon={<AddIcon />} onClick={() => open("new")}>{newLabel}</Button>} />
      <Paper>
        <Stack p={2}>
          <TextField size="small" placeholder="Rechercher…" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }} sx={{ maxWidth: 360 }} />
        </Stack>
        {error ? <ErrorBox message={error} onRetry={reload} /> : loading && !data ? <Loading /> : !data?.results.length ? <EmptyState text="Aucun élément pour le moment." /> : (
          <TableContainer>
            <Table size="small">
              <TableHead><TableRow>{columns.map((c) => <TableCell key={c.header}>{c.header}</TableCell>)}{canEdit && <TableCell width={56} />}</TableRow></TableHead>
              <TableBody>
                {data.results.map((row) => (
                  <TableRow key={row.id} hover>
                    {columns.map((c) => <TableCell key={c.header}>{c.render(row)}</TableCell>)}
                    {canEdit && <TableCell><IconButton size="small" aria-label="Modifier" onClick={() => open(row)}><EditIcon fontSize="small" /></IconButton></TableCell>}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {data.count > 25 && <Stack alignItems="center" p={2}><Pagination count={Math.ceil(data.count / 25)} page={page} onChange={(_, p) => setPage(p)} /></Stack>}
          </TableContainer>
        )}
      </Paper>

      <Dialog open={!!editing} onClose={() => !busy && setEditing(null)} fullWidth maxWidth="sm">
        <DialogTitle>{editing === "new" ? newLabel : "Modifier"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            {fields.filter((f) => !(f.createOnly && editing !== "new")).map((f) =>
              f.type === "switch" ? (
                <FormControlLabel key={f.name} label={f.label} control={<Switch checked={!!form[f.name]} onChange={(e) => setForm({ ...form, [f.name]: e.target.checked })} />} />
              ) : (
                <TextField key={f.name} label={f.label} type={f.type === "select" ? undefined : f.type ?? "text"} select={f.type === "select"}
                  required={f.required} value={form[f.name] ?? ""} onChange={(e) => setForm({ ...form, [f.name]: e.target.value })}
                  error={!!errs[f.name]} helperText={errs[f.name] ?? f.helper} size="small" fullWidth>
                  {f.options?.map((o) => <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>)}
                </TextField>
              ))}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditing(null)} disabled={busy}>Annuler</Button>
          <Button variant="contained" onClick={submit} disabled={busy}>Enregistrer</Button>
        </DialogActions>
      </Dialog>
      {node}
    </>
  );
}
