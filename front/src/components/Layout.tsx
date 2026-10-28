import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { currentTheme, toggleTheme } from "../theme";

export default function Layout() {
  const [dark, setDark] = useState(currentTheme() === "dark");

  return (
    <div className="app">
      <header className="topbar">
        <NavLink to="/" className="brand">
          Casa de Leilões
        </NavLink>
        <nav className="nav">
          <NavLink to="/" end>
            Vitrine
          </NavLink>
          <NavLink to="/meus-lances">Meus lances</NavLink>
          <NavLink to="/carteira">Carteira</NavLink>
          <NavLink to="/entrar">Entrar</NavLink>
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
