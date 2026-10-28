import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import type { Role } from "../api/types";
import { useAuth } from "../auth/AuthContext";

export default function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("bidder");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    try {
      await register({ username, email, password, role });
      navigate("/");
    } catch (exc) {
      setError(
        exc instanceof ApiError
          ? exc.message
          : "Não consegui falar com o servidor. Tente de novo.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section style={{ maxWidth: 420, margin: "0 auto" }}>
      <h1>Criar conta</h1>
      <form className="card" onSubmit={handleSubmit}>
        <div className="field">
          <label className="label" htmlFor="register-username">
            Nome de exibição
          </label>
          <input
            id="register-username"
            className="input"
            autoComplete="username"
            required
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
        </div>
        <div className="field">
          <label className="label" htmlFor="register-email">
            E-mail
          </label>
          <input
            id="register-email"
            className="input"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>
        <div className="field">
          <label className="label" htmlFor="register-password">
            Senha
          </label>
          <input
            id="register-password"
            className="input"
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>
        <div className="field">
          <label className="label" htmlFor="register-role">
            Quero
          </label>
          <select
            id="register-role"
            className="select"
            value={role}
            onChange={(event) => setRole(event.target.value as Role)}
          >
            <option value="bidder">Licitar nos lotes</option>
            <option value="auctioneer">Conduzir leilões</option>
          </select>
        </div>
        {error && <p className="feedback-error">{error}</p>}
        <button className="btn" type="submit" disabled={busy}>
          {busy ? "Criando conta…" : "Criar conta"}
        </button>
        <p className="muted" style={{ marginBottom: 0 }}>
          Já tem conta? <Link to="/entrar">Entrar</Link>
        </p>
      </form>
    </section>
  );
}
