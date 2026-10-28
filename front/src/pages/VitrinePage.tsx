import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "../api/client";
import type { Auction, Paginated } from "../api/types";
import AuctionCard from "../components/AuctionCard";
import Pagination from "../components/Pagination";
import { parseBrlToCents } from "../lib/money";

const TABS = [
  { label: "Todos", value: "" },
  { label: "Ao vivo", value: "live" },
  { label: "Agendados", value: "scheduled" },
  { label: "Encerrados", value: "ended" },
];

type Filters = { q: string; min: string; max: string };

const EMPTY_FILTERS: Filters = { q: "", min: "", max: "" };

export default function VitrinePage() {
  const [status, setStatus] = useState("");
  const [ordering, setOrdering] = useState("ends_at");
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [refresh, setRefresh] = useState(0);

  const [q, setQ] = useState("");
  const [minPrice, setMinPrice] = useState("");
  const [maxPrice, setMaxPrice] = useState("");

  const [data, setData] = useState<Paginated<Auction> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [sheetOpen, setSheetOpen] = useState(false);
  const qRef = useRef<HTMLInputElement>(null);
  const openerRef = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);

  const activeCount =
    (filters.q ? 1 : 0) +
    (filters.min ? 1 : 0) +
    (filters.max ? 1 : 0) +
    (ordering !== "ends_at" ? 1 : 0);

  useEffect(() => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (filters.q) params.set("q", filters.q);
    if (ordering !== "ends_at") params.set("ordering", ordering);
    const min = parseBrlToCents(filters.min);
    const max = parseBrlToCents(filters.max);
    if (min !== null) params.set("min_price", String(min));
    if (max !== null) params.set("max_price", String(max));
    if (page > 1) params.set("page", String(page));

    let cancelled = false;

    api
      .get<Paginated<Auction>>(`/api/auctions/?${params.toString()}`, false)
      .then((result) => {
        if (!cancelled) {
          setData(result);
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
  }, [status, ordering, page, filters, refresh]);

  useEffect(() => {
    if (sheetOpen) {
      qRef.current?.focus();
    } else if (wasOpen.current) {
      openerRef.current?.focus();
    }
    wasOpen.current = sheetOpen;
  }, [sheetOpen]);

  function selectStatus(value: string) {
    setStatus(value);
    setPage(1);
    setLoading(true);
  }

  function changeOrdering(value: string) {
    setOrdering(value);
    setPage(1);
    setLoading(true);
  }

  function goToPage(nextPage: number) {
    setPage(nextPage);
    setLoading(true);
  }

  function applyFilters(event: FormEvent<HTMLFormElement>): boolean {
    event.preventDefault();
    const min = minPrice.trim() ? parseBrlToCents(minPrice) : null;
    const max = maxPrice.trim() ? parseBrlToCents(maxPrice) : null;
    if ((minPrice.trim() && min === null) || (maxPrice.trim() && max === null)) {
      setError("Faixa de preço inválida. Use algo como 100,50.");
      return false;
    }
    setError(null);
    setPage(1);
    setLoading(true);
    setFilters({ q: q.trim(), min: minPrice.trim(), max: maxPrice.trim() });
    return true;
  }

  function handleApply(event: FormEvent<HTMLFormElement>) {
    if (applyFilters(event)) {
      setSheetOpen(false);
    }
  }

  function clearFilters() {
    setQ("");
    setMinPrice("");
    setMaxPrice("");
    setOrdering("ends_at");
    setError(null);
    setPage(1);
    setLoading(true);
    setFilters(EMPTY_FILTERS);
    setSheetOpen(false);
  }

  function retry() {
    setLoading(true);
    setRefresh((count) => count + 1);
  }

  return (
    <section>
      <h1>Vitrine</h1>

      <div className="tabs">
        {TABS.map((tab) => (
          <button
            key={tab.value}
            type="button"
            className={status === tab.value ? "tab active" : "tab"}
            onClick={() => selectStatus(tab.value)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="vitrine-controls" data-open={sheetOpen}>
        <button
          type="button"
          className="search-trigger"
          aria-expanded={sheetOpen}
          aria-controls="filtros-sheet"
          onClick={(event) => {
            openerRef.current = event.currentTarget;
            setSheetOpen(true);
          }}
        >
          🔍 {filters.q ? `“${filters.q}”` : "Buscar por título…"}
        </button>
        <button
          type="button"
          className="btn filters-btn"
          aria-expanded={sheetOpen}
          aria-controls="filtros-sheet"
          onClick={(event) => {
            openerRef.current = event.currentTarget;
            setSheetOpen(true);
          }}
        >
          ⚙ Filtros
          {activeCount > 0 && (
            <span className="filter-count">{activeCount}</span>
          )}
        </button>

        <form
          id="filtros-sheet"
          className="filters"
          data-open={sheetOpen}
          onSubmit={handleApply}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setSheetOpen(false);
            }
          }}
        >
          <h2 className="sheet-title">
            Filtros
            <button
              type="button"
              className="sheet-close"
              aria-label="Fechar filtros"
              onClick={() => setSheetOpen(false)}
            >
              ✕
            </button>
          </h2>
          <input
            ref={qRef}
            className="input"
            type="search"
            placeholder="Buscar por título…"
            aria-label="Buscar lotes"
            value={q}
            onChange={(event) => setQ(event.target.value)}
          />
          <div className="price-row">
            <input
              className="input"
              inputMode="decimal"
              placeholder="Mín. (R$)"
              aria-label="Preço mínimo"
              value={minPrice}
              onChange={(event) => setMinPrice(event.target.value)}
            />
            <input
              className="input"
              inputMode="decimal"
              placeholder="Máx. (R$)"
              aria-label="Preço máximo"
              value={maxPrice}
              onChange={(event) => setMaxPrice(event.target.value)}
            />
          </div>
          <select
            className="select"
            aria-label="Ordenação"
            value={ordering}
            onChange={(event) => changeOrdering(event.target.value)}
          >
            <option value="ends_at">Termina primeiro</option>
            <option value="-ends_at">Termina por último</option>
            <option value="starting_bid_cents">Menor lance inicial</option>
            <option value="-starting_bid_cents">Maior lance inicial</option>
          </select>
          <button className="btn filters-submit" type="submit">
            Buscar
          </button>
          {error && <p className="feedback-error sheet-error">{error}</p>}
          <div className="sheet-actions">
            <button
              className="btn btn-ghost sheet-clear"
              type="button"
              onClick={clearFilters}
            >
              Limpar
            </button>
            <button className="btn sheet-apply" type="submit">
              Aplicar filtros
            </button>
          </div>
        </form>

        <div
          className="sheet-backdrop"
          data-open={sheetOpen}
          aria-hidden="true"
          onClick={() => setSheetOpen(false)}
        />

        {error && (
          <p className="feedback-error">
            {error}{" "}
            <button
              type="button"
              className="btn btn-ghost"
              onClick={retry}
            >
              Tentar de novo
            </button>
          </p>
        )}
      </div>

      {loading ? (
        <p className="empty-state">Carregando lotes…</p>
      ) : data && data.results.length > 0 ? (
        <>
          <div className="grid">
            {data.results.map((auction) => (
              <AuctionCard key={auction.id} auction={auction} />
            ))}
          </div>
          <Pagination
            page={page}
            hasPrev={data.previous !== null}
            hasNext={data.next !== null}
            onPage={goToPage}
          />
        </>
      ) : (
        !error && <p className="empty-state">Nenhum lote encontrado.</p>
      )}
    </section>
  );
}
