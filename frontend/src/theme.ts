import { createTheme } from "@mui/material/styles";

export const theme = createTheme({
  palette: {
    primary: { main: "#1d4ed8" },
    secondary: { main: "#0f172a" },
    background: { default: "#f1f5f9" },
    success: { main: "#15803d" },
    warning: { main: "#d97706" },
    error: { main: "#b91c1c" },
  },
  shape: { borderRadius: 10 },
  typography: { fontFamily: '"Inter","Segoe UI",system-ui,sans-serif', button: { textTransform: "none", fontWeight: 600 } },
  components: {
    MuiPaper: { defaultProps: { elevation: 0 }, styleOverrides: { root: { border: "1px solid #e2e8f0" } } },
    MuiButton: { defaultProps: { disableElevation: true } },
    MuiTableCell: { styleOverrides: { head: { fontWeight: 700, color: "#475569", background: "#f8fafc" } } },
  },
});
