import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import { api, apiUrl, ApiError } from "../api/client";
import type {
  ArtworkSearchResult,
  AuctionStatus,
  ImportedArtwork,
  MineAuction,
  MineResponse,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import Pagination from "../components/Pagination";
import StatusBadge from "../components/StatusBadge";
import Thumb from "../components/Thumb";
import { formatDateTime, toDateTimeLocalValue } from "../lib/datetime";
import { formatCents, parseBrlToCents } from "../lib/money";

const STATUS_TABS: { label: string; value: "" | AuctionStatus }[] = [
  { label: "Todos", value: "" },
  { label: "Agendados", value: "scheduled" },
  { label: "Ao vivo", value: "live" },
  { label: "Encerrados", value: "ended" },
  { label: "Cancelados", value: "cancelled" },
];

function failMessage(exc: unknown): string {
  return exc instanceof ApiError
    ? exc.message
    : "Não consegui falar com o servidor.";
}

function toIso(value: string): string | null {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function resultLabel(auction: MineAuction): string {
  if (auction.status === "ended") {
    return auction.received_cents !== null
      ? `Arrematado por ${formatCents(auction.received_cents)}`
      : "Encerrado sem lances";
  }
  if (auction.status === "cancelled") {
    return "Cancelado · lances comprometidos estornados";
  }
  if (auction.status === "live") {
    return "Lances abertos";
  }
  return "Aguardando o início";
}

/** Miniatura de obra ainda não importada (proxy do servidor; o ArtIC bloqueia hotlink). */
function previewSrc(imageId: string): string | null {
  return imageId ? apiUrl(`/api/catalog/preview/${imageId}/`) : null;
}

export default function PainelPage() {
  const { user, ready } = useAuth();
  const location = useLocation();

  const [mine, setMine] = useState<MineResponse | null>(null);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<"" | AuctionStatus>("");
  const [reload, setReload] = useState(0);
  const [mineLoading, setMineLoading] = useState(true);
  const [mineError, setMineError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [results, setResults] = useState<ArtworkSearchResult[] | null>(null);

  const [importingId, setImportingId] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [selected, setSelected] = useState<
    (ImportedArtwork & { imageId: string }) | null
  >(null);

  const [startingBid, setStartingBid] = useState("");
  const [increment, setIncrement] = useState("");
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [createdId, setCreatedId] = useState<number | null>(null);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editStart, setEditStart] = useState("");
  const [editEnd, setEditEnd] = useState("");
  const [savingSchedule, setSavingSchedule] = useState(false);
  const [scheduleError, setScheduleError] = useState<string | null>(null);

  const [confirmingId, setConfirmingId] = useState<number | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  useEffect(() => {
    if (!user || user.role !== "auctioneer") {
      return;
    }
    let cancelled = false;
    const params = new URLSearchParams({ page: String(page) });
    if (statusFilter) {
      params.set("status", statusFilter);
    }

    api
      .get<MineResponse>(`/api/auctions/mine/?${params.toString()}`)
      .then((data) => {
        if (!cancelled) {
          setMine(data);
          setMineError(null);
          setMineLoading(false);
        }
      })
      .catch((exc: unknown) => {
        if (!cancelled) {
          setMineError(failMessage(exc));
          setMineLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [user, page, statusFilter, reload]);

  function reloadMine() {
    setMineLoading(true);
    setReload((count) => count + 1);
  }

  async function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSearchError(null);
    setImportError(null);

    const term = query.trim();
    if (!term) {
      setSearchError("Digite um termo para pesquisar.");
      return;
    }

    setSearching(true);
    try {
      const data = await api.get<{ results: ArtworkSearchResult[] }>(
        `/api/catalog/search/?q=${encodeURIComponent(term)}&limit=10`,
      );
      setResults(data.results);
      if (data.results.length === 0) {
        setSearchError("Nenhuma obra encontrada para este termo.");
      }
    } catch (exc) {
      setSearchError(failMessage(exc));
    } finally {
      setSearching(false);
    }
  }

  async function importArtwork(artwork: ArtworkSearchResult) {
    setImportError(null);
    setImportingId(artwork.id);
    try {
      const item = await api.post<ImportedArtwork>("/api/catalog/import/", {
        external_id: artwork.id,
      });
      setSelected({ ...item, imageId: artwork.image_id });
      setResults(null);
      setQuery("");
    } catch (exc) {
      setImportError(failMessage(exc));
    } finally {
      setImportingId(null);
    }
  }

  async function submitCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreateError(null);
    if (!selected) {
      return;
    }

    const bidCents = parseBrlToCents(startingBid);
    if (bidCents === null || bidCents <= 0) {
      setCreateError("Lance inicial inválido, ex.: 100,00");
      return;
    }
    const incrementCents = parseBrlToCents(increment);
    if (incrementCents === null || incrementCents <= 0) {
      setCreateError("Incremento mínimo inválido, ex.: 5,00");
      return;
    }
    const startsIso = toIso(startsAt);
    const endsIso = toIso(endsAt);
    if (!startsIso || !endsIso) {
      setCreateError("Preencha o início e o fim do lote.");
      return;
    }
    if (new Date(endsIso) <= new Date(startsIso)) {
      setCreateError("O fim deve ser depois do início.");
      return;
    }

    setCreating(true);
    try {
      const auction = await api.post<MineAuction>("/api/auctions/", {
        item_id: selected.id,
        starting_bid_cents: bidCents,
        minimum_increment_cents: incrementCents,
        starts_at: startsIso,
        ends_at: endsIso,
        status: "scheduled",
      });
      setCreatedId(auction.id);
      setSelected(null);
      setStartingBid("");
      setIncrement("");
      setStartsAt("");
      setEndsAt("");
      reloadMine();
    } catch (exc) {
      setCreateError(failMessage(exc));
    } finally {
      setCreating(false);
    }
  }

  async function saveSchedule(auctionId: number) {
    setScheduleError(null);

    const startsIso = toIso(editStart);
    const endsIso = toIso(editEnd);
    if (!startsIso || !endsIso) {
      setScheduleError("Preencha o início e o fim.");
      return;
    }
    if (new Date(endsIso) <= new Date(startsIso)) {
      setScheduleError("O fim deve ser depois do início.");
      return;
    }

    setSavingSchedule(true);
    try {
      await api.patch<MineAuction>(`/api/auctions/${auctionId}/`, {
        starts_at: startsIso,
        ends_at: endsIso,
      });
      setEditingId(null);
      reloadMine();
    } catch (exc) {
      setScheduleError(failMessage(exc));
    } finally {
      setSavingSchedule(false);
    }
  }

  async function cancelAuction(auctionId: number) {
    setCancelError(null);
    setCancelling(true);
    try {
      await api.post<MineAuction>(`/api/auctions/${auctionId}/cancel/`);
      setConfirmingId(null);
      reloadMine();
    } catch (exc) {
      setCancelError(failMessage(exc));
    } finally {
      setCancelling(false);
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
        <h1>Painel do leiloeiro</h1>
        <div className="empty-state">
          <p>Entre como leiloeiro para criar e gerenciar lotes.</p>
          <Link className="btn" to="/entrar" state={{ from: location }}>
            Entrar
          </Link>
        </div>
      </section>
    );
  }

  if (user.role !== "auctioneer") {
    return (
      <section>
        <h1>Painel do leiloeiro</h1>
        <div className="empty-state">
          <p>
            Esta área é restrita a leiloeiros. Crie uma conta como leiloeiro
            para gerenciar lotes.
          </p>
          <Link className="btn" to="/">
            Ver a vitrine
          </Link>
        </div>
      </section>
    );
  }

  return (
    <section>
      <h1>Painel do leiloeiro</h1>

      <div className="card">
        <h2>Criar lote</h2>
        {selected ? (
          <>
            <div className="selected-artwork">
              <Thumb
                src={previewSrc(selected.imageId)}
                alt={selected.title}
                className="selected-thumb"
              />
              <div className="selected-artwork-text">
                <span className="muted">Obra selecionada</span>
                <strong>{selected.title}</strong>
              </div>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setSelected(null)}
              >
                Trocar de obra
              </button>
            </div>
            <form onSubmit={submitCreate}>
              <div className="panel-form-grid">
                <div className="field">
                  <label className="label" htmlFor="lot-starting">
                    Lance inicial (R$)
                  </label>
                  <input
                    id="lot-starting"
                    className="input"
                    inputMode="decimal"
                    placeholder="100,00"
                    required
                    value={startingBid}
                    onChange={(event) => {
                      setStartingBid(event.target.value);
                      setCreateError(null);
                    }}
                  />
                </div>
                <div className="field">
                  <label className="label" htmlFor="lot-increment">
                    Incremento mínimo (R$)
                  </label>
                  <input
                    id="lot-increment"
                    className="input"
                    inputMode="decimal"
                    placeholder="5,00"
                    required
                    value={increment}
                    onChange={(event) => {
                      setIncrement(event.target.value);
                      setCreateError(null);
                    }}
                  />
                </div>
                <div className="field">
                  <label className="label" htmlFor="lot-starts">
                    Início
                  </label>
                  <input
                    id="lot-starts"
                    className="input"
                    type="datetime-local"
                    required
                    value={startsAt}
                    onChange={(event) => {
                      setStartsAt(event.target.value);
                      setCreateError(null);
                    }}
                  />
                </div>
                <div className="field">
                  <label className="label" htmlFor="lot-ends">
                    Fim
                  </label>
                  <input
                    id="lot-ends"
                    className="input"
                    type="datetime-local"
                    required
                    value={endsAt}
                    onChange={(event) => {
                      setEndsAt(event.target.value);
                      setCreateError(null);
                    }}
                  />
                </div>
              </div>
              {createError && <p className="feedback-error">{createError}</p>}
              <button className="btn" type="submit" disabled={creating}>
                {creating ? "Criando…" : "Criar lote agendado"}
              </button>
            </form>
          </>
        ) : (
          <>
            <form className="panel-search" onSubmit={submitSearch}>
              <input
                className="input"
                placeholder='Buscar obra no catálogo (ex.: "painting", "van gogh")'
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setSearchError(null);
                }}
              />
              <button className="btn" type="submit" disabled={searching}>
                {searching ? "Buscando…" : "Buscar"}
              </button>
            </form>
            {importError && <p className="feedback-error">{importError}</p>}
            {searchError && <p className="feedback-error">{searchError}</p>}
            {results && results.length > 0 && (
              <ul className="artwork-grid">
                {results.map((artwork) => (
                  <li key={artwork.id} className="card artwork-card">
                    <Thumb
                      src={previewSrc(artwork.image_id)}
                      alt={artwork.title}
                      className="artwork-thumb"
                    />
                    <div className="artwork-body">
                      <strong className="artwork-title">
                        {artwork.title}
                      </strong>
                      {artwork.description && (
                        <div className="muted artwork-desc">
                          {artwork.description.slice(0, 120)}
                        </div>
                      )}
                      <button
                        className="btn btn-ghost"
                        type="button"
                        disabled={importingId === artwork.id}
                        onClick={() => void importArtwork(artwork)}
                      >
                        {importingId === artwork.id
                          ? "Importando…"
                          : "Usar esta obra"}
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
        {createdId !== null && (
          <p className="feedback-success">
            Lote criado ✓{" "}
            <Link to={`/lotes/${createdId}`}>Abrir lote #{createdId}</Link>
          </p>
        )}
      </div>

      <div className="card" style={{ marginTop: "1rem" }}>
        <div className="panel-head">
          <h2>Meus lotes</h2>
          {mine && (
            <span className="muted">
              Total recebido:{" "}
              <strong>{formatCents(mine.summary.total_received_cents)}</strong>
            </span>
          )}
        </div>

        <div className="tabs">
          {STATUS_TABS.map((tab) => (
            <button
              key={tab.value}
              type="button"
              className={statusFilter === tab.value ? "tab active" : "tab"}
              onClick={() => {
                setStatusFilter(tab.value);
                setPage(1);
                setMineLoading(true);
                setMineError(null);
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {mineError && (
          <p className="feedback-error">
            {mineError}{" "}
            <button type="button" className="btn btn-ghost" onClick={reloadMine}>
              Tentar de novo
            </button>
          </p>
        )}

        {mineLoading ? (
          <p className="empty-state">Carregando…</p>
        ) : !mine || mine.results.length === 0 ? (
          <p className="empty-state">
            {statusFilter
              ? "Nenhum lote com este status."
              : "Nenhum lote ainda. Importe uma obra acima para começar."}
          </p>
        ) : (
          <>
            <ul className="mine-list">
              {mine.results.map((auction) => (
                <li key={auction.id} className="mine-row">
                  <div className="mine-main">
                    <Thumb
                      src={
                        auction.item_image_url
                          ? apiUrl(
                              `/api/catalog/image/${auction.item_id}/`,
                            )
                          : null
                      }
                      alt={auction.item_title}
                      className="mine-thumb"
                    />
                    <div>
                      <Link
                        to={`/lotes/${auction.id}`}
                        className="mine-title"
                      >
                        {auction.item_title}
                      </Link>
                      <div className="muted tx-meta">
                        lote #{auction.id} · {auction.bid_count} lance(s) ·
                        início {formatDateTime(auction.starts_at)} · fim{" "}
                        {formatDateTime(auction.ends_at)}
                      </div>
                      <div className="muted">{resultLabel(auction)}</div>
                      {cancelError && confirmingId === auction.id && (
                        <p className="feedback-error">{cancelError}</p>
                      )}
                      {scheduleError && editingId === auction.id && (
                        <p className="feedback-error">{scheduleError}</p>
                      )}
                      {editingId === auction.id && (
                        <div className="panel-editor">
                          <input
                            className="input"
                            type="datetime-local"
                            aria-label="Novo início"
                            value={editStart}
                            onChange={(event) => {
                              setEditStart(event.target.value);
                              setScheduleError(null);
                            }}
                          />
                          <input
                            className="input"
                            type="datetime-local"
                            aria-label="Novo fim"
                            value={editEnd}
                            onChange={(event) => {
                              setEditEnd(event.target.value);
                              setScheduleError(null);
                            }}
                          />
                          <button
                            className="btn"
                            type="button"
                            disabled={savingSchedule}
                            onClick={() => void saveSchedule(auction.id)}
                          >
                            {savingSchedule ? "Salvando…" : "Salvar"}
                          </button>
                          <button
                            className="btn btn-ghost"
                            type="button"
                            onClick={() => setEditingId(null)}
                          >
                            Fechar
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="mine-right">
                    <StatusBadge status={auction.status} />
                    <div className="panel-actions">
                      {auction.status === "scheduled" && (
                        <button
                          className="btn btn-ghost"
                          type="button"
                          onClick={() => {
                            setEditingId(auction.id);
                            setConfirmingId(null);
                            setScheduleError(null);
                            setEditStart(
                              toDateTimeLocalValue(auction.starts_at),
                            );
                            setEditEnd(toDateTimeLocalValue(auction.ends_at));
                          }}
                        >
                          Programar
                        </button>
                      )}
                      {(auction.status === "scheduled" ||
                        auction.status === "live") &&
                        (confirmingId === auction.id ? (
                          <>
                            <button
                              className="btn btn-ghost"
                              type="button"
                              onClick={() => {
                                setConfirmingId(null);
                                setCancelError(null);
                              }}
                            >
                              Não
                            </button>
                            <button
                              className="btn btn-danger"
                              type="button"
                              disabled={cancelling}
                              onClick={() => void cancelAuction(auction.id)}
                            >
                              {cancelling ? "Cancelando…" : "Confirmar"}
                            </button>
                          </>
                        ) : (
                          <button
                            className="btn btn-ghost"
                            type="button"
                            onClick={() => {
                              setConfirmingId(auction.id);
                              setEditingId(null);
                              setCancelError(null);
                            }}
                          >
                            Cancelar
                          </button>
                        ))}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
            <Pagination
              page={page}
              hasPrev={mine.previous !== null}
              hasNext={mine.next !== null}
              onPage={(next) => {
                setPage(next);
                setMineLoading(true);
              }}
            />
          </>
        )}
      </div>
    </section>
  );
}
