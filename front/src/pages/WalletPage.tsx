import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type {
  TransactionsResponse,
  Wallet,
  WalletTransactionRow,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { formatDateTime } from "../lib/datetime";
import {
  centsToDecimalString,
  formatCents,
  formatSignedCents,
  parseBrlToCents,
} from "../lib/money";

export default function WalletPage() {
  const { user, ready } = useAuth();
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [rows, setRows] = useState<WalletTransactionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  const [amount, setAmount] = useState("");
  const [depositing, setDepositing] = useState(false);
  const [depositError, setDepositError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!user) {
      return;
    }
    let cancelled = false;

    Promise.all([
      api.get<Wallet>("/api/wallets/"),
      api.get<TransactionsResponse>("/api/wallets/transactions/"),
    ])
      .then(([walletData, transactions]) => {
        if (!cancelled) {
          setWallet(walletData);
          setRows(transactions.results);
          setError(null);
          setLoading(false);
        }
      })
      .catch((exc: unknown) => {
        if (!cancelled) {
          setError(
            exc instanceof ApiError
              ? exc.message
              : "Não consegui falar com o servidor.",
          );
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [user, reload]);

  function retry() {
    setLoading(true);
    setError(null);
    setReload((count) => count + 1);
  }

  async function submitDeposit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setDepositError(null);
    setNotice(null);

    const cents = parseBrlToCents(amount);
    if (cents === null || cents <= 0) {
      setDepositError("Digite um valor válido, ex.: 50,00");
      return;
    }

    setDepositing(true);
    try {
      const updated = await api.post<Wallet>("/api/wallets/deposit/", {
        amount: centsToDecimalString(cents),
      });
      setWallet(updated);
      setAmount("");
      setNotice(`Depósito de ${formatCents(cents)} creditado ✓`);
      setReload((count) => count + 1);
    } catch (exc) {
      setDepositError(
        exc instanceof ApiError
          ? exc.message
          : "Não consegui falar com o servidor.",
      );
    } finally {
      setDepositing(false);
    }
  }

  if (!ready) {
    return (
      <section>
        <p className="empty-state">Carregando…</p>
      </section>
    );
  }

  if (!user) {
    return (
      <section>
        <h1>Carteira</h1>
        <div className="empty-state">
          <p>Entre para ver o seu saldo e o extrato de movimentações.</p>
          <Link className="btn" to="/entrar">
            Entrar
          </Link>
        </div>
      </section>
    );
  }

  if (loading && !wallet) {
    return (
      <section>
        <p className="empty-state">Carregando carteira…</p>
      </section>
    );
  }

  if (error && !wallet) {
    return (
      <section>
        <h1>Carteira</h1>
        <p className="feedback-error">
          {error}{" "}
          <button type="button" className="btn btn-ghost" onClick={retry}>
            Tentar de novo
          </button>
        </p>
      </section>
    );
  }

  return (
    <section>
      <h1>Carteira</h1>

      {wallet && (
        <div className="card wallet-stats">
          <div>
            <span className="muted">Disponível</span>
            <strong className="stat-big">
              {formatCents(wallet.available_cents)}
            </strong>
          </div>
          <div>
            <span className="muted">Comprometido em lotes</span>
            <strong>{formatCents(wallet.committed_cents)}</strong>
          </div>
          <div>
            <span className="muted">Saldo total</span>
            <strong>{formatCents(wallet.balance_cents)}</strong>
          </div>
        </div>
      )}

      <div className="card" style={{ marginTop: "1rem" }}>
        <h2>Depositar</h2>
        <form onSubmit={submitDeposit}>
          <div className="field">
            <label className="label" htmlFor="deposit-amount">
              Valor (R$)
            </label>
            <input
              id="deposit-amount"
              className="input"
              inputMode="decimal"
              placeholder="50,00"
              required
              value={amount}
              onChange={(event) => {
                setAmount(event.target.value);
                setDepositError(null);
              }}
            />
          </div>
          {depositError && <p className="feedback-error">{depositError}</p>}
          {notice && <p className="feedback-success">{notice}</p>}
          <button className="btn" type="submit" disabled={depositing}>
            {depositing ? "Depositando…" : "Depositar"}
          </button>
        </form>
      </div>

      <div className="card" style={{ marginTop: "1rem" }}>
        <h2>Extrato</h2>
        {error && (
          <p className="feedback-error">
            {error}{" "}
            <button type="button" className="btn btn-ghost" onClick={retry}>
              Tentar de novo
            </button>
          </p>
        )}
        {rows.length === 0 ? (
          <p className="muted">Nenhuma movimentação ainda.</p>
        ) : (
          <ul className="tx-list">
            {rows.map((row, index) => (
              <li key={`${row.created_at}-${index}`} className="tx-row">
                <div>
                  <strong>{row.kind_label}</strong>
                  <span className="muted"> — {row.description}</span>
                  <div className="muted tx-meta">
                    {formatDateTime(row.created_at)}
                    {row.auction_id !== null && ` · lote #${row.auction_id}`}
                  </div>
                </div>
                <div className="tx-amounts">
                  <span
                    className={row.delta_cents >= 0 ? "pos" : "neg"}
                  >
                    {formatSignedCents(row.delta_cents)}
                  </span>
                  {row.committed_delta_cents !== 0 && (
                    <span className="muted">
                      comprometido{" "}
                      {formatSignedCents(row.committed_delta_cents)}
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
