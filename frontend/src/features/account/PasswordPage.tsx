import { useState } from "react";
import { Button, Paper, Stack, TextField } from "@mui/material";
import { post } from "../../services/api";
import { PageHeader, useToast } from "../../components/common";

/** Changement de son propre mot de passe (le mot de passe provisoire donné par l'administrateur doit être remplacé). */
export function PasswordPage() {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const { toast, node } = useToast();
  const mismatch = again !== "" && again !== next;

  const save = async () => {
    setBusy(true);
    try {
      await post("/auth/change-password/", { current_password: cur, new_password: next });
      setCur(""); setNext(""); setAgain("");
      toast.ok("Mot de passe modifié.");
    } catch (e) { toast.fail(e); } finally { setBusy(false); }
  };

  return (
    <>
      <PageHeader title="Mon mot de passe" subtitle="Choisissez un mot de passe d'au moins 8 caractères, difficile à deviner" />
      <Paper sx={{ p: 3, maxWidth: 440 }}>
        <Stack spacing={2}>
          <TextField label="Mot de passe actuel" type="password" size="small" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} />
          <TextField label="Nouveau mot de passe" type="password" size="small" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
          <TextField label="Confirmer le nouveau mot de passe" type="password" size="small" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)}
            error={mismatch} helperText={mismatch ? "Les deux mots de passe sont différents" : undefined} />
          <Button variant="contained" disabled={busy || !cur || next.length < 8 || next !== again} onClick={save}>{busy ? "Enregistrement…" : "Changer le mot de passe"}</Button>
        </Stack>
      </Paper>
      {node}
    </>
  );
}
