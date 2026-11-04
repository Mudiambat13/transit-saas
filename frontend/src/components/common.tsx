import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Alert, Box, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, Snackbar, Stack, Typography } from "@mui/material";
import { ApiError } from "../services/api";

/** Charge des données avec états chargement / erreur / rechargement. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const reload = useCallback(() => {
    const id = ++seq.current;
    setLoading(true);
    fn()
      .then((d) => { if (id === seq.current) { setData(d); setError(null); } })
      .catch((e) => { if (id === seq.current) setError(e instanceof ApiError ? e.message : "Erreur inattendue."); })
      .finally(() => { if (id === seq.current) setLoading(false); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(reload, [reload]);
  return { data, error, loading, reload, setData };
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ sm: "center" }} spacing={1.5} sx={{ mb: 2.5 }}>
      <Box>
        <Typography variant="h5" fontWeight={800}>{title}</Typography>
        {subtitle && <Typography color="text.secondary" variant="body2">{subtitle}</Typography>}
      </Box>
      <Stack direction="row" spacing={1}>{actions}</Stack>
    </Stack>
  );
}

export function Loading() {
  return <Box sx={{ py: 6, textAlign: "center" }}><CircularProgress size={28} /></Box>;
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return <Alert severity="error" action={onRetry && <Button color="inherit" size="small" onClick={onRetry}>Réessayer</Button>}>{message}</Alert>;
}

export function EmptyState({ text }: { text: string }) {
  return <Box sx={{ py: 5, textAlign: "center", color: "text.secondary" }}><Typography>{text}</Typography></Box>;
}

export function ConfirmDialog({ open, title, text, confirmLabel = "Confirmer", danger, onClose, onConfirm, children }: {
  open: boolean; title: string; text?: string; confirmLabel?: string; danger?: boolean; children?: ReactNode;
  onClose: () => void; onConfirm: () => void | Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} fullWidth maxWidth="xs">
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>{text && <Typography sx={{ mb: 1 }}>{text}</Typography>}{children}</DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>Annuler</Button>
        <Button variant="contained" color={danger ? "error" : "primary"} disabled={busy}
          onClick={async () => { setBusy(true); try { await onConfirm(); } finally { setBusy(false); } }}>{confirmLabel}</Button>
      </DialogActions>
    </Dialog>
  );
}

/** Notifications globales simples. */
export function useToast() {
  const [msg, setMsg] = useState<{ text: string; severity: "success" | "error" } | null>(null);
  const toast = {
    ok: (text: string) => setMsg({ text, severity: "success" }),
    fail: (e: unknown) => setMsg({ text: e instanceof ApiError ? e.message : "Erreur inattendue.", severity: "error" }),
  };
  const node = (
    <Snackbar open={!!msg} autoHideDuration={4500} onClose={() => setMsg(null)} anchorOrigin={{ vertical: "bottom", horizontal: "center" }}>
      {msg ? <Alert severity={msg.severity} onClose={() => setMsg(null)} variant="filled">{msg.text}</Alert> : undefined}
    </Snackbar>
  );
  return { toast, node };
}

const TRIP_COLORS: Record<string, "default" | "primary" | "success" | "warning" | "error" | "info"> = {
  DRAFT: "default", OPEN: "success", BOARDING: "primary", CLOSED: "warning", COMPLETED: "info", CANCELLED: "error", SUSPENDED: "warning",
};
export function StatusChip({ status, label }: { status: string; label?: string }) {
  return <Chip size="small" label={label ?? status} color={TRIP_COLORS[status] ?? "default"} variant={status === "DRAFT" ? "outlined" : "filled"} />;
}

export const fmtDateTime = (iso?: string | null, tz?: string) =>
  iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short", timeZone: tz }) : "—";
export const fmtMoney = (v: string | number, cur: string) => `${Number(v).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${cur}`;

/** Convertit une saisie datetime-local (heure de la compagnie) en ISO UTC. */
export function localInputToIso(value: string, tz: string): string {
  const wall = Date.parse(`${value}:00Z`); // l'heure saisie, lue comme si elle était UTC
  const offsetAt = (utcMs: number) => {
    const p = Object.fromEntries(
      new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" })
        .formatToParts(new Date(utcMs)).map((x) => [x.type, x.value]),
    );
    return Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second) - utcMs;
  };
  let utc = wall - offsetAt(wall);
  utc = wall - offsetAt(utc); // 2e passe : change de décalage (heure d'été) autour du résultat
  return new Date(utc).toISOString();
}

/** Inverse : ISO UTC → valeur `datetime-local` dans le fuseau de la compagnie. */
export function isoToLocalInput(iso: string, tz: string): string {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
      .formatToParts(new Date(iso)).map((x) => [x.type, x.value]),
  );
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}
