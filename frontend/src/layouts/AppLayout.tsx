import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  AppBar, Box, Chip, Divider, Drawer, IconButton, List, ListItemButton, ListItemIcon, ListItemText, Toolbar, Typography, useMediaQuery, useTheme,
} from "@mui/material";
import MenuIcon from "@mui/icons-material/Menu";
import DashboardIcon from "@mui/icons-material/SpaceDashboard";
import BusinessIcon from "@mui/icons-material/Business";
import StoreIcon from "@mui/icons-material/Storefront";
import PeopleIcon from "@mui/icons-material/People";
import BusIcon from "@mui/icons-material/DirectionsBus";
import RouteIcon from "@mui/icons-material/AltRoute";
import ConfirmationNumberIcon from "@mui/icons-material/ConfirmationNumber";
import QrCodeScannerIcon from "@mui/icons-material/QrCodeScanner";
import HistoryIcon from "@mui/icons-material/History";
import LogoutIcon from "@mui/icons-material/Logout";
import SettingsIcon from "@mui/icons-material/Settings";
import { useAuth } from "../services/auth";

interface Item { to: string; label: string; icon: JSX.Element; perm?: string }

const PLATFORM: Item[] = [
  { to: "/platform", label: "Tableau de bord", icon: <DashboardIcon /> },
  { to: "/platform/companies", label: "Compagnies", icon: <BusinessIcon /> },
  { to: "/platform/plans", label: "Offres", icon: <SettingsIcon /> },
  { to: "/platform/audit", label: "Journal", icon: <HistoryIcon /> },
];
const COMPANY: Item[] = [
  { to: "/", label: "Tableau de bord", icon: <DashboardIcon />, perm: "report.view" },
  { to: "/trips", label: "Voyages", icon: <RouteIcon />, perm: "trip.view" },
  { to: "/tickets", label: "Billets", icon: <ConfirmationNumberIcon />, perm: "ticket.view" },
  { to: "/boarding", label: "Embarquement", icon: <QrCodeScannerIcon />, perm: "boarding.scan" },
  { to: "/fleet", label: "Flotte", icon: <BusIcon />, perm: "fleet.view" },
  { to: "/agencies", label: "Agences", icon: <StoreIcon />, perm: "agency.manage" },
  { to: "/users", label: "Utilisateurs", icon: <PeopleIcon />, perm: "user.manage" },
  { to: "/audit", label: "Journal", icon: <HistoryIcon />, perm: "report.view" },
  { to: "/settings", label: "Compagnie", icon: <SettingsIcon />, perm: "company.manage" },
];
const W = 244;

export default function AppLayout() {
  const { me, can, logout } = useAuth();
  const theme = useTheme();
  const desktop = useMediaQuery(theme.breakpoints.up("md"));
  const [open, setOpen] = useState(false);
  const nav = useNavigate();
  const platform = !!me?.is_platform_admin;
  const items = (platform ? PLATFORM : COMPANY).filter((i) => !i.perm || can(i.perm));

  const drawer = (
    <Box sx={{ height: "100%", display: "flex", flexDirection: "column", bgcolor: platform ? "#0f172a" : "#1e3a8a", color: "white" }}>
      <Box sx={{ p: 2.5 }}>
        <Typography fontWeight={800} fontSize={18}>Transit SaaS</Typography>
        <Typography variant="caption" sx={{ opacity: 0.75 }}>{platform ? "Administration plateforme" : me?.tenant?.name}</Typography>
      </Box>
      <Divider sx={{ borderColor: "rgba(255,255,255,.15)" }} />
      <List sx={{ flex: 1, px: 1 }}>
        {items.map((i) => (
          <ListItemButton key={i.to} component={NavLink} to={i.to} end={i.to === "/" || i.to === "/platform"} onClick={() => setOpen(false)}
            sx={{ borderRadius: 2, mb: 0.5, color: "inherit", "&.active": { bgcolor: "rgba(255,255,255,.18)" }, "&:hover": { bgcolor: "rgba(255,255,255,.1)" } }}>
            <ListItemIcon sx={{ color: "inherit", minWidth: 38 }}>{i.icon}</ListItemIcon>
            <ListItemText primary={i.label} />
          </ListItemButton>
        ))}
      </List>
      <Divider sx={{ borderColor: "rgba(255,255,255,.15)" }} />
      <Box sx={{ p: 2 }}>
        <Typography variant="body2" noWrap>{me?.full_name || me?.email}</Typography>
        <Chip size="small" label={platform ? "Super Admin" : me?.role?.replace("_", " ")} sx={{ mt: 0.5, bgcolor: "rgba(255,255,255,.18)", color: "white" }} />
        <ListItemButton onClick={async () => { await logout(); nav("/login"); }} sx={{ mt: 1, borderRadius: 2, color: "inherit" }}>
          <ListItemIcon sx={{ color: "inherit", minWidth: 36 }}><LogoutIcon fontSize="small" /></ListItemIcon>
          <ListItemText primary="Se déconnecter" />
        </ListItemButton>
      </Box>
    </Box>
  );

  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      {!desktop && (
        <AppBar position="fixed" color="primary" elevation={0}>
          <Toolbar variant="dense">
            <IconButton color="inherit" edge="start" onClick={() => setOpen(true)} aria-label="Menu"><MenuIcon /></IconButton>
            <Typography fontWeight={700} sx={{ ml: 1 }}>Transit SaaS</Typography>
          </Toolbar>
        </AppBar>
      )}
      <Drawer variant={desktop ? "permanent" : "temporary"} open={desktop || open} onClose={() => setOpen(false)}
        sx={{ width: desktop ? W : 0, "& .MuiDrawer-paper": { width: W, border: 0 } }}>{drawer}</Drawer>
      <Box component="main" sx={{ flex: 1, minWidth: 0, p: { xs: 1.5, md: 3 }, pt: { xs: 8, md: 3 } }}>
        <Outlet />
      </Box>
    </Box>
  );
}
