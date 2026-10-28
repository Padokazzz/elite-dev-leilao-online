import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { AuditReport, Auction, Paginated } from "../api/types";
import { formatDateTime } from "../lib/datetime";
import { formatCents } from "../lib/money";

const REASON_LABELS: Record<string, string> = {
  sequence_gap: "lacuna na sequência de lances",
  prev_hash_mismatch: "o hash anterior não confere com o lance",
  hash_mismatch: "o conteúdo do lance não confere com o hash",
};

export default function AuditPage() {
  const [searchParams] = useSearchParams();
  const [id, setId] = useState(() => searchParams.get("lote") ?? "");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<AuditReport | null>(null);
  const [ended, setEnded] = useState<Auction[] | null>(null);

  useEffect(() => {
    let cancelled = false;

    api
      .get<Paginated<Auction>>(
        "/api/auctions/?status=ended&ordering=-ends_at",
        false,
      )
      .then((data) => {
        if (!cancelled) {
          setEnded(data.results);
        }
      })
      .catch(() => undefined);

    const initial = searchParams.get("lote");
    if (initial) {
      void verify(initial);
    }

    return () => {
      cancelled = true;
    };
  }, [searchParams]);

  async function verify(rawId: string) {
    const auctionId = Number(rawId);
    if (!Number.isInteger(auctionId) || auctionId <= 0) {
      setReport(null);
      setError("Informe o número de um lote válido.");
      return;
    }

    setChecking(true);
    setError(null);
    setReport(null);
    try {
      const data = await api.get<AuditReport>(
        `/api/auctions/${auctionId}/audit/`,
        false,
      );
      setReport(data);
    } catch (exc) {
      setError(
        exc instanceof ApiError
          ? exc.message
          : "Não consegui falar com o servidor.",
      );
    } finally {
      setChecking(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void verify(id);
  }

  return (
    <section>
      <h1>Auditoria pública</h1>
      <p className="muted">
        Cada lance aceito entra numa cadeia de hashes encadeados. Qualquer
        adulteração por edição ou exclusão quebra a cadeia e aparece aqui —
        sem login e sem expor e-mail ou ID de ninguém.
      </p>

      <div className="card">
        <h2>Verificar um lote</h2>
        <form className="panel-search" onSubmit={submit}>
          <input
            className="input"
            inputMode="numeric"
            placeholder="Número do lote (ex.: 4)"
            aria-label="Número do lote"
            value={id}
            onChange={(event) => {
              setId(event.target.value);
              setError(null);
            }}
          />
          <button className="btn" type="submit" disabled={checking}>
            {checking ? "Verificando…" : "Verificar"}
          </button>
        </form>
        {error && <p className="feedback-error">{error}</p>}
      </div>

      {report && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <h2>Lote #{report.auction_id}</h2>
          {report.intact ? (
            <p className="feedback-success">
              Cadeia íntegra ✓ — {report.chain.length} lance(s) verificados
            </p>
          ) : (
            <p className="feedback-error">
              Cadeia adulterada no lance #{report.tampered?.seq}:{" "}
              {report.tampered ? REASON_LABELS[report.tampered.reason] : ""}
              {report.tampered?.expected_seq !== undefined &&
                ` (sequência esperada: ${report.tampered.expected_seq})`}
            </p>
          )}
          {report.chain.length === 0 ? (
            <p className="muted">Nenhum lance registrado neste lote.</p>
          ) : (
            <table className="audit-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Valor</th>
                  <th>Momento</th>
                  <th>Licitante</th>
                </tr>
              </thead>
              <tbody>
                {report.chain.map((row) => (
                  <tr
                    key={row.seq}
                    className={
                      report.tampered?.seq === row.seq ? "audit-bad" : undefined
                    }
                  >
                    <td>{row.seq}</td>
                    <td>{formatCents(row.amount_cents)}</td>
                    <td>{formatDateTime(row.accepted_at)}</td>
                    <td>{row.bidder}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="muted" style={{ marginTop: "0.5rem" }}>
            <Link to={`/lotes/${report.auction_id}`}>Ver o lote</Link>
          </p>
        </div>
      )}

      {ended && ended.length > 0 && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <h2>Lotes encerrados</h2>
          <ul className="mine-list">
            {ended.map((auction) => (
              <li key={auction.id} className="mine-row">
                <div>
                  <Link to={`/lotes/${auction.id}`} className="mine-title">
                    {auction.item_title}
                  </Link>
                  <div className="muted tx-meta">
                    lote #{auction.id} · {auction.bid_count ?? 0} lance(s) ·
                    encerrado {formatDateTime(auction.ends_at)}
                  </div>
                </div>
                <div className="mine-right">
                  <button
                    className="btn btn-ghost"
                    type="button"
                    disabled={checking}
                    onClick={() => {
                      setId(String(auction.id));
                      void verify(String(auction.id));
                    }}
                  >
                    Verificar
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
