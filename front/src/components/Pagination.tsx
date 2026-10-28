export default function Pagination({
  page,
  hasPrev,
  hasNext,
  onPage,
}: {
  page: number;
  hasPrev: boolean;
  hasNext: boolean;
  onPage: (page: number) => void;
}) {
  return (
    <div className="pagination">
      <button
        type="button"
        className="btn btn-ghost"
        disabled={!hasPrev}
        onClick={() => onPage(page - 1)}
      >
        Anterior
      </button>
      <span className="muted">Página {page}</span>
      <button
        type="button"
        className="btn btn-ghost"
        disabled={!hasNext}
        onClick={() => onPage(page + 1)}
      >
        Próxima
      </button>
    </div>
  );
}
