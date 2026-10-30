import { Navigate, Route, Routes } from "react-router-dom";
import { hasRole, useAuth } from "./auth";
import { Layout } from "./components/Layout";
import { Admin } from "./pages/Admin";
import { Audit } from "./pages/Audit";
import { BotDetail } from "./pages/BotDetail";
import { Bots } from "./pages/Bots";
import { Dashboard } from "./pages/Dashboard";
import { FlowEditor } from "./pages/FlowEditor";
import { ImportRobot } from "./pages/ImportRobot";
import { Login } from "./pages/Login";
import { RunDetail } from "./pages/RunDetail";
import { Runs } from "./pages/Runs";

export function App() {
  const { user, loading } = useAuth();
  if (loading) return <p className="muted center">A carregar…</p>;
  if (!user) return <Login />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="bots" element={<Bots />} />
        <Route path="bots/:key" element={<BotDetail />} />
        {hasRole(user, "admin") && <Route path="flows/new" element={<FlowEditor />} />}
        {hasRole(user, "admin") && <Route path="flows/import-robot" element={<ImportRobot />} />}
        <Route path="flows/:key" element={<FlowEditor />} />
        <Route path="runs" element={<Runs />} />
        <Route path="runs/:id" element={<RunDetail />} />
        <Route path="approvals" element={<Runs fixedStatus="WAITING_APPROVAL" title="Aprovações pendentes" />} />
        {hasRole(user, "approver") && <Route path="audit" element={<Audit />} />}
        {hasRole(user, "admin") && <Route path="admin" element={<Admin />} />}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
