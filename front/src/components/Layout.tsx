import { useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { currentTheme, toggleTheme } from "../theme";

export default function Layout() {
  const [dark, setDark] = useState(currentTheme() === "dark");
  const { user, logout } = useAuth();

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
          {user && <NavLink to="/meus-lances">Meus lances</NavLink>}
          {user && <NavLink to="/carteira">Carteira</NavLink>}
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
          className="btn btn-ghost"
          aria-label={dark ? "Ativar tema claro" : "Ativar tema escuro"}
          onClick={() => setDark(toggleTheme() === "dark")}
        >
          {dark ? "☀️" : "🌙"}
        </button>
      </header>
      <main className="page">
        <Outlet />
      </main>
    </div>
  );
}
