import { NavLink, Outlet } from "react-router-dom";
import { hasRole, useAuth } from "../auth";

const ROLE_LABEL: Record<string, string> = {
  viewer: "Consulta",
  operator: "Operador",
  approver: "Aprovador",
  admin: "Administrador",
};

export function Layout() {
  const { user, logout } = useAuth();
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">LP</span>
          <div>
            <strong>LUSOPAY</strong>
            <small>Bot Manager</small>
          </div>
        </div>
        <nav>
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/bots">Catálogo de bots</NavLink>
          <NavLink to="/runs">Execuções</NavLink>
          <NavLink to="/approvals">Aprovações</NavLink>
          {hasRole(user, "approver") && <NavLink to="/audit">Auditoria</NavLink>}
          {hasRole(user, "admin") && <NavLink to="/admin">Administração</NavLink>}
        </nav>
        <div className="sidebar-footer">
          <div>
            <strong>{user?.display_name || user?.username}</strong>
            <small>{ROLE_LABEL[user?.role ?? ""]}</small>
          </div>
          <button className="btn btn-ghost" onClick={logout}>Sair</button>
        </div>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
