import type { AuctionStatus } from "../api/types";

const STATUS_LABELS: Record<AuctionStatus, string> = {
  scheduled: "Agendado",
  live: "Ao vivo",
  ended: "Encerrado",
  cancelled: "Cancelado",
};

const STATUS_CLASSES: Record<AuctionStatus, string> = {
  scheduled: "badge",
  live: "badge badge-live",
  ended: "badge",
  cancelled: "badge badge-cancelled",
};

export default function StatusBadge({ status }: { status: AuctionStatus }) {
  return <span className={STATUS_CLASSES[status]}>{STATUS_LABELS[status]}</span>;
}
