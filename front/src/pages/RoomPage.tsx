import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api, apiUrl, ApiError } from "../api/client";
import type {
  AuctionDetail,
  AuctionStatus,
  BidRow,
  BidsResponse,
  PlaceBidResponse,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import StatusBadge from "../components/StatusBadge";
import Thumb from "../components/Thumb";
import useAuctionRoom from "../hooks/useAuctionRoom";
import useCountdown from "../hooks/useCountdown";
import { formatDateTime, formatRemaining, formatTime } from "../lib/datetime";
import { bidRejectionMessage } from "../lib/bidErrors";
import { formatCents, parseBrlToCents } from "../lib/money";

type BidError = { message: string; needsFunds: boolean };

type AppliedBid = {
  seq: number;
  next_minimum_cents: number;
  ends_at: string;
};

export default function RoomPage() {
  const { auctionId } = useParams();
  const { user, ready } = useAuth();
  const id = Number(auctionId);
  const invalidId = !Number.isFinite(id) || id <= 0;
  const live = useAuctionRoom(id, Boolean(user));

  const [detail, setDetail] = useState<AuctionDetail | null>(null);
  const [restBids, setRestBids] = useState<BidRow[]>([]);
  const [localBids, setLocalBids] = useState<BidRow[]>([]);
  const [localApplied, setLocalApplied] = useState<AppliedBid | null>(null);
  const [loadState, setLoadState] = useState<
    "loading" | "ready" | "missing" | "error"
  >("loading");

  const [amount, setAmount] = useState("");
  const [bidError, setBidError] = useState<BidError | null>(null);
  const [bidSuccess, setBidSuccess] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (invalidId) {
      return;
    }
    let cancelled = false;

    api
      .get<AuctionDetail>(`/api/auctions/${id}/`, false)
      .then((data) => {
        if (!cancelled) {
          setDetail(data);
          setLoadState("ready");
        }
      })
      .catch((exc: unknown) => {
        if (!cancelled) {
          setLoadState(
            exc instanceof ApiError && exc.status === 404
              ? "missing"
              : "error",
          );
        }
      });

    return () => {
      cancelled = true;
    };
  }, [id, invalidId]);

  useEffect(() => {
    if (!user || invalidId) {
      return;
    }
    let cancelled = false;

    api
      .get<BidsResponse>(`/api/auctions/${id}/bids/`)
      .then((data) => {
        if (!cancelled) {
          setRestBids(data.results);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setRestBids([]);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [id, user, invalidId]);

  const snapshot = live.snapshot;

  const mergedBids = useMemo(() => {
    const bySeq = new Map<number, BidRow>();
    for (const bid of restBids) {
      bySeq.set(bid.seq, bid);
    }
    for (const bid of localBids) {
      bySeq.set(bid.seq, bid);
    }
    for (const event of live.bidEvents) {
      if (!bySeq.has(event.bid.seq)) {
        bySeq.set(event.bid.seq, {
          seq: event.bid.seq,
          amount_cents: event.bid.amount_cents,
          accepted_at: event.bid.accepted_at,
          bidder_pseudonym: event.bid.bidder_pseudonym,
          is_you: event.is_you,
        });
      }
    }
    return [...bySeq.values()].sort((a, b) => b.seq - a.seq);
  }, [restBids, localBids, live.bidEvents]);

  const top = mergedBids[0] ?? null;
  const topSeq = top?.seq ?? 0;

  useEffect(() => {
    if (!user || !snapshot || snapshot.last_seq <= topSeq) {
      return;
    }
    let cancelled = false;
    api
      .get<BidsResponse>(`/api/auctions/${id}/bids/`)
      .then((data) => {
        if (!cancelled) {
          setRestBids(data.results);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [user, snapshot, topSeq, id]);

  const baseStatus: AuctionStatus = live.cancelled
    ? "cancelled"
    : live.closed
      ? "ended"
      : snapshot?.status ?? detail?.status ?? "scheduled";

  const untilStart = useCountdown(
    detail?.starts_at ?? null,
    baseStatus === "scheduled",
  );

  const status: AuctionStatus =
    baseStatus === "scheduled" && untilStart !== null && untilStart <= 0
      ? "live"
      : baseStatus;

  // Ficha da obra (vem só no detalhe; a lista não traz estes campos).
  const attrs = detail?.item_attributes;
  const artist =
    typeof attrs?.artist === "string" && attrs.artist !== ""
      ? attrs.artist
      : "";
  const sourceUrl =
    typeof attrs?.source_url === "string" && attrs.source_url !== ""
      ? attrs.source_url
      : "";
  const metaFacts = [attrs?.date, attrs?.medium, attrs?.dimensions].filter(
    (value): value is string => typeof value === "string" && value !== "",
  );

  const newestWs = live.bidEvents[live.bidEvents.length - 1] ?? null;
  const topSource =
    newestWs && newestWs.bid.seq === topSeq
      ? newestWs
      : localApplied && localApplied.seq === topSeq
        ? localApplied
        : null;

  const lastBidCents =
    top?.amount_cents ?? snapshot?.last_bid_cents ?? null;

  const endsAt =
    topSource?.ends_at ?? snapshot?.ends_at ?? detail?.ends_at ?? null;

  const nextMinimum = top
    ? (topSource?.next_minimum_cents ??
      top.amount_cents +
        (snapshot?.minimum_increment_cents ??
          detail?.minimum_increment_cents ??
          0))
    : detail?.starting_bid_cents ?? 0;

  const youLead = live.closed
    ? false
    : top
      ? top.is_you
      : (snapshot?.you_lead ?? false);

  const remaining = useCountdown(endsAt, status === "live");

  const extendedNote = Boolean(newestWs?.extended) && status === "live";

  async function submitBid(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBidError(null);
    setBidSuccess(null);

    const cents = parseBrlToCents(amount);
    if (cents === null || cents <= 0) {
      setBidError({
        message: "Digite um valor válido, ex.: 150,00",
        needsFunds: false,
      });
      return;
    }
    if (cents < nextMinimum) {
      setBidError({
        message: `O lance mínimo agora é ${formatCents(nextMinimum)}.`,
        needsFunds: false,
      });
      return;
    }

    setSubmitting(true);
    try {
      const response = await api.post<PlaceBidResponse>(
        `/api/auctions/${id}/bids/`,
        { amount_cents: cents },
      );
      setLocalBids((prev) =>
        prev.some((bid) => bid.seq === response.bid.seq)
          ? prev
          : [
              {
                seq: response.bid.seq,
                amount_cents: response.bid.amount_cents,
                accepted_at: response.bid.accepted_at,
                bidder_pseudonym: response.bid.bidder_pseudonym,
                is_you: true,
              },
              ...prev,
            ],
      );
      setLocalApplied({
        seq: response.bid.seq,
        next_minimum_cents: response.next_minimum_cents,
        ends_at: response.ends_at,
      });
      setAmount("");
      setBidSuccess(
        `Lance de ${formatCents(response.bid.amount_cents)} aceito${
          response.extended ? " — relógio estendido em 2 min" : ""
        }.`,
      );
    } catch (exc) {
      if (exc instanceof ApiError) {
        setBidError({
          message: bidRejectionMessage(exc.code, exc.message),
          needsFunds: exc.code === "insufficient_balance",
        });
      } else {
        setBidError({
          message: "Não consegui falar com o servidor. Tente de novo.",
          needsFunds: false,
        });
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (invalidId || loadState === "missing") {
    return (
      <section>
        <h1>Lote não encontrado</h1>
        <p className="empty-state">
          Este lote não existe ou foi removido.{" "}
          <Link to="/">Voltar à vitrine</Link>
        </p>
      </section>
    );
  }

  if (loadState === "error" || !detail) {
    if (loadState === "loading") {
      return (
        <section>
          <p className="empty-state">Carregando lote…</p>
        </section>
      );
    }
    return (
      <section>
        <h1>Erro ao carregar</h1>
        <p className="feedback-error">
          Não consegui falar com o servidor.{" "}
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => window.location.reload()}
          >
            Recarregar
          </button>
        </p>
      </section>
    );
  }

  return (
    <section className="room">
      <div className="card">
        <div className="room-art">
          <Thumb
            src={
              detail.item_image_url
                ? apiUrl(`/api/catalog/image/${detail.item_id}/`)
                : null
            }
            alt={detail.item_title}
            className="room-art-thumb"
          />
          <div className="room-art-info">
            {artist !== "" && (
              <div className="room-art-artist">{artist}</div>
            )}
            <div className="auction-card-head">
              <h1>{detail.item_title}</h1>
              <StatusBadge status={status} />
            </div>
            {metaFacts.length > 0 && (
              <p className="room-art-meta">{metaFacts.join(" · ")}</p>
            )}
            {detail.item_description && (
              <p className="room-art-desc">{detail.item_description}</p>
            )}
            {sourceUrl !== "" && (
              <a
                className="room-art-source link-touch"
                href={sourceUrl}
                target="_blank"
                rel="noreferrer"
              >
                Ver ficha original ↗
              </a>
            )}
          </div>
        </div>
        <p className="muted">
          Leiloeiro: {detail.seller_pseudonym} · lance inicial{" "}
          {formatCents(detail.starting_bid_cents)} · incremento mínimo{" "}
          {formatCents(detail.minimum_increment_cents)}
        </p>

        {live.unavailable === "offline" && (
          <p className="feedback-error">
            Sem conexão ao vivo — os dados podem estar defasados. Recarregue a
            página.
          </p>
        )}

        {status === "live" && remaining !== null && (
          <div className="countdown-row">
            <span className={remaining <= 0 ? "muted" : "countdown"}>
              {remaining <= 0
                ? "encerrando…"
                : `⏱ ${formatRemaining(remaining)}`}
            </span>
            <span className="current-price">
              {lastBidCents !== null ? (
                <>
                  lance atual <strong>{formatCents(lastBidCents)}</strong>
                </>
              ) : (
                <>
                  sem lances — abertura{" "}
                  {formatCents(detail.starting_bid_cents)}
                </>
              )}
            </span>
          </div>
        )}

        {status === "scheduled" && untilStart !== null && (
          <p className="muted">
            Começa em{" "}
            {untilStart > 0 ? formatRemaining(untilStart) : "breve"}
          </p>
        )}

        {status === "live" && (
          <p className="muted">
            Próximo lance mínimo:{" "}
            <strong>{formatCents(nextMinimum)}</strong>. Nos últimos 2 minutos,
            um novo lance estende o relógio em 2 min.
          </p>
        )}

        {extendedNote && (
          <p className="feedback-success">
            ⏱ Relógio estendido: um lance nos últimos 2 minutos reiniciou a
            contagem.
          </p>
        )}

        {youLead && status === "live" && (
          <p className="feedback-success">⚡ Você é o maior lance.</p>
        )}
      </div>

      {live.closed && (
        <div className="banner banner-win card" role="status">
          {live.closed.you_won ? (
            <p>
              🏆 <strong>Você arrematou!</strong>
              {live.closed.amount_cents !== null &&
                ` por ${formatCents(live.closed.amount_cents)}`}
              {live.closed.receipt_public_uuid && (
                <>
                  {" · "}
                  <Link
                    to={`/comprovantes/${live.closed.receipt_public_uuid}`}
                  >
                    Ver comprovante
                  </Link>
                </>
              )}
            </p>
          ) : live.closed.winner_pseudonym === null ? (
            <p>Lote encerrado sem lances.</p>
          ) : (
            <p>
              Lote encerrado — vencedor{" "}
              <strong>{live.closed.winner_pseudonym}</strong>
              {live.closed.amount_cents !== null &&
                ` com ${formatCents(live.closed.amount_cents)}`}
              .
            </p>
          )}
        </div>
      )}

      {!live.closed && status === "ended" && detail.winner_pseudonym && (
        <div className="banner card" role="status">
          <p>
            Lote encerrado — vencedor{" "}
            <strong>{detail.winner_pseudonym}</strong>
            {lastBidCents !== null && ` com ${formatCents(lastBidCents)}`}.
          </p>
        </div>
      )}

      {!live.closed && status === "ended" && !detail.winner_pseudonym && (
        <div className="banner card" role="status">
          <p>Lote encerrado sem lances.</p>
        </div>
      )}

      {status === "cancelled" && (
        <div className="banner banner-cancelled card" role="status">
          <p>Este lote foi cancelado. Os lances são estornados.</p>
        </div>
      )}

      <div className="room-grid">
        <div className="card">
          <h2>Dar lance</h2>

          {!ready ? null : !user ? (
            <div className="empty-state">
              <p>Entre para acompanhar ao vivo e participar dos lances.</p>
              <Link className="btn" to="/entrar">
                Entrar
              </Link>
            </div>
          ) : status === "live" ? (
            youLead ? (
              <p className="muted">
                Você é o maior lance. Aguarde um novo lance para superar.
              </p>
            ) : (
              <form onSubmit={submitBid}>
                <div className="field">
                  <label className="label" htmlFor="bid-amount">
                    Seu lance (R$) — mínimo {formatCents(nextMinimum)}
                  </label>
                  <input
                    id="bid-amount"
                    className="input"
                    inputMode="decimal"
                    placeholder={formatCents(nextMinimum)
                      .replace("R$", "")
                      .trim()}
                    required
                    value={amount}
                    onChange={(event) => {
                      setAmount(event.target.value);
                      setBidError(null);
                    }}
                  />
                </div>
                {bidError && (
                  <p className="feedback-error">
                    {bidError.message}{" "}
                    {bidError.needsFunds && (
                      <Link to="/carteira">Ir para a carteira</Link>
                    )}
                  </p>
                )}
                {bidSuccess && (
                  <p className="feedback-success">{bidSuccess}</p>
                )}
                <button className="btn" type="submit" disabled={submitting}>
                  {submitting ? "Enviando…" : "Dar lance"}
                </button>
              </form>
            )
          ) : (
            <p className="muted">
              {status === "scheduled"
                ? "Os lances começam quando o leilão iniciar."
                : status === "ended"
                  ? "Este lote já foi encerrado."
                  : "Este lote foi cancelado."}
            </p>
          )}
        </div>

        <div className="card">
          <h2>Lances</h2>
          {mergedBids.length === 0 ? (
            <p className="muted">
              {user
                ? "Nenhum lance ainda — seja o primeiro."
                : "Entre para ver o histórico de lances."}
            </p>
          ) : (
            <ul className="bid-list">
              {mergedBids.map((bid) => (
                <li
                  key={bid.seq}
                  className={bid.is_you ? "bid-row you" : "bid-row"}
                >
                  <span className="muted">#{bid.seq}</span>
                  <span className="bid-by">{bid.bidder_pseudonym}</span>
                  <strong>{formatCents(bid.amount_cents)}</strong>
                  <span className="muted">
                    {formatTime(bid.accepted_at)}
                  </span>
                  {bid.is_you && <span className="badge">Você</span>}
                </li>
              ))}
            </ul>
          )}
          <p className="muted">
            Termina {formatDateTime(endsAt ?? detail.ends_at)}
          </p>
        </div>
      </div>
    </section>
  );
}
