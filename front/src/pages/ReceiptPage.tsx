import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { Receipt } from "../api/types";
import { formatDateTime } from "../lib/datetime";
import { formatCents } from "../lib/money";

export default function ReceiptPage() {
  const { uuid } = useParams();
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [state, setState] = useState<
    "loading" | "ready" | "missing" | "error"
  >("loading");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!uuid) {
      return;
    }
    let cancelled = false;

    api
      .get<Receipt>(`/api/receipts/${uuid}/`, false)
      .then((data) => {
        if (!cancelled) {
          setReceipt(data);
          setState("ready");
        }
      })
      .catch((exc: unknown) => {
        if (!cancelled) {
          setState(
            exc instanceof ApiError && exc.status === 404
              ? "missing"
              : "error",
          );
        }
      });

    return () => {
      cancelled = true;
    };
  }, [uuid]);

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  if (!uuid) {
    return (
      <section className="receipt">
        <h1>Comprovante não encontrado</h1>
        <p className="empty-state">
          Este comprovante não existe. <Link to="/">Voltar à vitrine</Link>
        </p>
      </section>
    );
  }

  if (state === "loading") {
    return (
      <section className="receipt">
        <p className="empty-state">Carregando comprovante…</p>
      </section>
    );
  }

  if (state === "missing" || !receipt) {
    return (
      <section className="receipt">
        <h1>Comprovante não encontrado</h1>
        <p className="empty-state">
          Este comprovante não existe. <Link to="/">Voltar à vitrine</Link>
        </p>
      </section>
    );
  }

  if (state === "error") {
    return (
      <section className="receipt">
        <h1>Erro ao carregar</h1>
        <p className="feedback-error">
          Não consegui falar com o servidor. Recarregue a página.
        </p>
      </section>
    );
  }

  return (
    <section className="receipt">
      <div className="card receipt-card">
        <p className="muted receipt-kicker">COMPROVANTE DE ARREMATE</p>
        <h1>{receipt.item_title}</h1>
        <p className="stat-big">{formatCents(receipt.amount_cents)}</p>
        <dl className="receipt-rows">
          <div>
            <dt>Arrematante</dt>
            <dd>{receipt.winner}</dd>
          </div>
          <div>
            <dt>Leiloeiro</dt>
            <dd>{receipt.seller}</dd>
          </div>
          <div>
            <dt>Liquidação</dt>
            <dd>{formatDateTime(receipt.settled_at)}</dd>
          </div>
          <div>
            <dt>Lote</dt>
            <dd>
              <Link to={`/lotes/${receipt.auction_id}`}>
                #{receipt.auction_id}
              </Link>
            </dd>
          </div>
        </dl>
        <p className="muted receipt-uuid">{receipt.public_uuid}</p>
        <div className="receipt-actions">
          <button type="button" className="btn btn-ghost" onClick={() => void copyLink()}>
            {copied ? "Link copiado ✓" : "Copiar link"}
          </button>
          <Link
            className="btn btn-ghost"
            to={`/auditoria?lote=${receipt.auction_id}`}
          >
            Verificar auditoria do lote
          </Link>
        </div>
      </div>
    </section>
  );
}
