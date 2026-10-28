import { useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { currentTheme, toggleTheme } from "../theme";

export default function Layout() {
  const [dark, setDark] = useState(currentTheme() === "dark");
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const location = useLocation();
  const { user, logout } = useAuth();
  const menuOpen = menuFor === location.pathname;

  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">
          Casa de Leilões
        </Link>
        <nav className="nav">
          <NavLink to="/" end>
            Vitrine
          </NavLink>
          <NavLink to="/auditoria">Auditoria</NavLink>
          {user && <NavLink to="/meus-lances">Meus lances</NavLink>}
          {user && <NavLink to="/carteira">Carteira</NavLink>}
          {user?.role === "auctioneer" && (
            <NavLink to="/painel">Painel</NavLink>
          )}
          {user ? (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => void logout()}
            >
              Sair ({user.username})
            </button>
          ) : (
            <NavLink to="/entrar">Entrar</NavLink>
          )}
        </nav>
        <button
          type="button"
          className="btn btn-ghost theme-toggle"
          aria-label={dark ? "Ativar tema claro" : "Ativar tema escuro"}
          onClick={() => setDark(toggleTheme() === "dark")}
        >
          {dark ? "☀️" : "🌙"}
        </button>
        <button
          type="button"
          className="btn btn-ghost menu-toggle"
          aria-label={menuOpen ? "Fechar menu" : "Abrir menu"}
          aria-expanded={menuOpen}
          aria-controls="menu-mobile"
          onClick={() => setMenuFor(menuOpen ? null : location.pathname)}
        >
          {menuOpen ? "✕" : "☰"}
        </button>
      </header>
      {menuOpen && (
        <nav id="menu-mobile" className="menu-mobile" aria-label="Menu">
          <NavLink to="/" end onClick={() => setMenuFor(null)}>
            Vitrine
          </NavLink>
          <NavLink to="/auditoria" onClick={() => setMenuFor(null)}>
            Auditoria
          </NavLink>
          {user && (
            <NavLink to="/meus-lances" onClick={() => setMenuFor(null)}>
              Meus lances
            </NavLink>
          )}
          {user && (
            <NavLink to="/carteira" onClick={() => setMenuFor(null)}>
              Carteira
            </NavLink>
          )}
          {user?.role === "auctioneer" && (
            <NavLink to="/painel" onClick={() => setMenuFor(null)}>
              Painel
            </NavLink>
          )}
          {user ? (
            <button
              type="button"
              className="menu-mobile-item"
              onClick={() => void logout()}
            >
              Sair ({user.username})
            </button>
          ) : (
            <NavLink to="/entrar">Entrar</NavLink>
          )}
        </nav>
      )}
      <main className="page">
        <Outlet />
      </main>
    </div>
  );
}
