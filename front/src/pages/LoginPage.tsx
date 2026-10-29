import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(() => {
    const state = location.state as { expired?: boolean } | null;
    return state?.expired ? "Sua sessão expirou. Entre de novo." : null;
  });
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    try {
      await login(email, password);
      const from =
        (location.state as { from?: { pathname: string } } | null)?.from
          ?.pathname ?? "/";
      navigate(from, { replace: true });
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
      <h1>Entrar</h1>
      <form className="card" onSubmit={handleSubmit}>
        <div className="field">
          <label className="label" htmlFor="login-email">
            E-mail
          </label>
          <input
            id="login-email"
            className="input"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>
        <div className="field">
          <label className="label" htmlFor="login-password">
            Senha
          </label>
          <input
            id="login-password"
            className="input"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>
        {error && <p className="feedback-error">{error}</p>}
        <button className="btn" type="submit" disabled={busy}>
          {busy ? "Entrando…" : "Entrar"}
        </button>
        <p className="muted" style={{ marginBottom: 0 }}>
          Ainda não tem conta?{" "}
          <Link className="link-touch" to="/registrar">
            Criar conta
          </Link>
        </p>
      </form>
    </section>
  );
}
