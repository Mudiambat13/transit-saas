import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import AppLayout from "./layouts/AppLayout";
import { Loading } from "./components/common";
import { useAuth } from "./services/auth";
import LoginPage from "./features/auth/LoginPage";
import { CompaniesPage, PlansPage, PlatformAuditPage, PlatformDashboard } from "./features/platform/PlatformPages";
import { AgenciesPage, AuditPage, DashboardPage, FleetPage, SettingsPage, UsersPage } from "./features/company/CompanyPages";
import TripsPage from "./features/trips/TripsPage";
import TripDetailPage from "./features/trips/TripDetailPage";
import { SellTicketPage, TicketsPage } from "./features/ticketing/TicketPages";
import ScannerPage from "./features/boarding/ScannerPage";
import { Alert } from "@mui/material";

/** Garde de route : l'UI se limite à masquer ; chaque endpoint reste protégé côté serveur. */
function Guard({ platform, perm }: { platform?: boolean; perm?: string }) {
  const { me, loading, can } = useAuth();
  if (loading) return <Loading />;
  if (!me) return <Navigate to="/login" replace />;
  if (platform && !me.is_platform_admin) return <Navigate to="/" replace />;
  if (!platform && me.is_platform_admin) return <Navigate to="/platform" replace />;
  if (perm && !can(perm)) return <Alert severity="warning">Vous n'avez pas accès à cette page.</Alert>;
  return <Outlet />;
}

function Home() {
  const { me, can } = useAuth();
  if (can("report.view")) return <DashboardPage />;
  if (can("ticket.create")) return <Navigate to="/tickets/new" replace />;
  if (can("boarding.scan")) return <Navigate to="/boarding" replace />;
  return <Navigate to="/trips" replace key={me?.id} />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<AppLayout />}>
        <Route element={<Guard platform />}>
          <Route path="/platform" element={<PlatformDashboard />} />
          <Route path="/platform/companies" element={<CompaniesPage />} />
          <Route path="/platform/plans" element={<PlansPage />} />
          <Route path="/platform/audit" element={<PlatformAuditPage />} />
        </Route>
        <Route element={<Guard />}>
          <Route path="/" element={<Home />} />
          <Route path="/trips" element={<TripsPage />} />
          <Route path="/trips/:id" element={<TripDetailPage />} />
          <Route path="/tickets" element={<TicketsPage />} />
          <Route path="/tickets/new" element={<SellTicketPage />} />
          <Route path="/boarding" element={<ScannerPage />} />
          <Route path="/fleet" element={<FleetPage />} />
          <Route path="/agencies" element={<AgenciesPage />} />
          <Route path="/users" element={<UsersPage />} />
          <Route path="/audit" element={<AuditPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
