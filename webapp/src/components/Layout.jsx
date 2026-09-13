import { NavLink, useNavigate } from "react-router-dom";
import { LayoutDashboard, KeyRound, LogOut, Shield } from "lucide-react";
import { clearToken } from "../api";

export default function Layout({ children, me }) {
  const navigate = useNavigate();

  function handleLogout() {
    clearToken();
    navigate("/login");
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Shield size={16} color="var(--teal)" /> CBDC Fraud Detection
        </div>
        <nav>
          <NavLink to="/dashboard" className={({ isActive }) => (isActive ? "active" : "")}>
            <LayoutDashboard size={16} /> Dashboard
          </NavLink>
          <NavLink to="/api-keys" className={({ isActive }) => (isActive ? "active" : "")}>
            <KeyRound size={16} /> API Keys
          </NavLink>
          <div className="navlink" onClick={handleLogout}>
            <LogOut size={16} /> Log out
          </div>
        </nav>
        {me && (
          <div className="org-box">
            <div className="org-name">{me.org_name}</div>
            <div className="org-email">{me.email}</div>
          </div>
        )}
      </aside>
      <main className="main-content">{children}</main>
    </div>
  );
}
