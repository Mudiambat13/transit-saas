import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { Alert, Box, Button, Paper, Stack, TextField, Typography } from "@mui/material";
import { ApiError } from "../../services/api";
import { useAuth } from "../../services/auth";

export default function LoginPage() {
  const { me, login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (me) return <Navigate to={me.is_platform_admin ? "/platform" : "/"} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const u = await login(email.trim(), password);
      nav(u.is_platform_admin ? "/platform" : "/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Connexion impossible.");
    } finally { setBusy(false); }
  };

  return (
    <Box sx={{ minHeight: "100vh", display: "grid", placeItems: "center", p: 2, background: "linear-gradient(135deg,#1e3a8a,#1d4ed8 55%,#3b82f6)" }}>
      <Paper component="form" onSubmit={submit} sx={{ p: 4, width: "100%", maxWidth: 400 }}>
        <Typography variant="h5" fontWeight={800} color="primary">Transit SaaS</Typography>
        <Typography color="text.secondary" sx={{ mb: 3 }}>Billetterie et gestion des voyages interurbains</Typography>
        <Stack spacing={2}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField label="Adresse e-mail" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus autoComplete="username" />
          <TextField label="Mot de passe" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" />
          <Button type="submit" variant="contained" size="large" disabled={busy}>{busy ? "Connexion…" : "Se connecter"}</Button>
        </Stack>
      </Paper>
    </Box>
  );
}
