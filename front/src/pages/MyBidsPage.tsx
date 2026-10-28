import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type {
  Auction,
  MyBid,
  MyBidState,
  Paginated,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import Pagination from "../components/Pagination";
import StatusBadge from "../components/StatusBadge";
import { formatDateTime } from "../lib/datetime";
import { formatCents } from "../lib/money";

const STATE_LABELS: Record<MyBidState, { label: string; className: string }> =
  {
    leading: { label: "Maior lance", className: "badge badge-live" },
    outbid: { label: "Superado", className: "badge" },
    won: { label: "Arrematado", className: "badge badge-live" },
    cancelled: { label: "Cancelado", className: "badge badge-cancelled" },
  };

type Tab = "bids" | "won";

export default function MyBidsPage() {
  const { user, ready } = useAuth();
  const location = useLocation();
  const [tab, setTab] = useState<Tab>("bids");
  const [page, setPage] = useState(1);
  const [reload, setReload] = useState(0);
  const [bids, setBids] = useState<Paginated<MyBid> | null>(null);
  const [won, setWon] = useState<Paginated<Auction> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) {
      return;
    }
    let cancelled = false;
    const fail = (exc: unknown) => {
      if (!cancelled) {
        setError(
          exc instanceof ApiError
            ? exc.message
            : "Não consegui falar com o servidor.",
        );
        setLoading(false);
      }
    };

    if (tab === "bids") {
      api
        .get<Paginated<MyBid>>(`/api/me/bids/?page=${page}`)
        .then((data) => {
          if (!cancelled) {
            setBids(data);
            setError(null);
            setLoading(false);
          }
        })
        .catch(fail);
    } else {
      api
        .get<Paginated<Auction>>(`/api/auctions/won/?page=${page}`)
        .then((data) => {
          if (!cancelled) {
            setWon(data);
            setError(null);
            setLoading(false);
          }
        })
        .catch(fail);
    }

    return () => {
      cancelled = true;
    };
  }, [user, tab, page, reload]);

  function selectTab(next: Tab) {
    setTab(next);
    setPage(1);
    setLoading(true);
    setError(null);
  }

  function goToPage(next: number) {
    setPage(next);
    setLoading(true);
  }

  function retry() {
    setLoading(true);
    setError(null);
    setReload((count) => count + 1);
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
        <h1>Meus lances</h1>
        <div className="empty-state">
          <p>Entre para acompanhar os seus lances e arremates.</p>
          <Link className="btn" to="/entrar" state={{ from: location }}>
            Entrar
          </Link>
        </div>
      </section>
    );
  }

  const current = tab === "bids" ? bids : won;

  return (
    <section>
      <h1>Meus lances</h1>

      <div className="tabs">
        <button
          type="button"
          className={tab === "bids" ? "tab active" : "tab"}
          onClick={() => selectTab("bids")}
        >
          Lances
        </button>
        <button
          type="button"
          className={tab === "won" ? "tab active" : "tab"}
          onClick={() => selectTab("won")}
        >
          Arremates
        </button>
      </div>

      {error && (
        <p className="feedback-error">
          {error}{" "}
          <button type="button" className="btn btn-ghost" onClick={retry}>
            Tentar de novo
          </button>
        </p>
      )}

      {loading ? (
        <p className="empty-state">Carregando…</p>
      ) : !current || current.results.length === 0 ? (
        <p className="empty-state">
          {tab === "bids"
            ? "Você ainda não deu nenhum lance."
            : "Você ainda não arrematou nenhum lote."}
        </p>
      ) : (
        <>
          <ul className="mine-list">
            {tab === "bids"
              ? bids?.results.map((bid) => (
                  <li
                    key={`${bid.auction_id}-${bid.seq}`}
                    className="mine-row"
                  >
                    <div>
                      <Link
                        to={`/lotes/${bid.auction_id}`}
                        className="mine-title"
                      >
                        {bid.auction_title}
                      </Link>
                      <div className="muted tx-meta">
                        lance #{bid.seq} · {formatDateTime(bid.accepted_at)} ·
                        termina {formatDateTime(bid.ends_at)} ·{" "}
                        <StatusBadge status={bid.auction_status} />
                      </div>
                    </div>
                    <div className="mine-right">
                      <strong>{formatCents(bid.amount_cents)}</strong>
                      <span className={STATE_LABELS[bid.state].className}>
                        {STATE_LABELS[bid.state].label}
                      </span>
                      {bid.state === "won" && bid.receipt_public_uuid && (
                        <Link to={`/comprovantes/${bid.receipt_public_uuid}`}>
                          Comprovante
                        </Link>
                      )}
                    </div>
                  </li>
                ))
              : won?.results.map((auction) => (
                  <li key={auction.id} className="mine-row">
                    <div>
                      <Link
                        to={`/lotes/${auction.id}`}
                        className="mine-title"
                      >
                        {auction.item_title}
                      </Link>
                      <div className="muted tx-meta">
                        {auction.bid_count ?? 0} lance(s) · encerrado{" "}
                        {formatDateTime(auction.ends_at)}
                      </div>
                    </div>
                    <div className="mine-right">
                      <StatusBadge status={auction.status} />
                      {auction.receipt_public_uuid && (
                        <Link
                          to={`/comprovantes/${auction.receipt_public_uuid}`}
                        >
                          Comprovante
                        </Link>
                      )}
                    </div>
                  </li>
                ))}
          </ul>
          <Pagination
            page={page}
            hasPrev={current.previous !== null}
            hasNext={current.next !== null}
            onPage={goToPage}
          />
        </>
      )}
    </section>
  );
}
