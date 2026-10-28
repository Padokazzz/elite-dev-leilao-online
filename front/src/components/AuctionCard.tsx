import { Link } from "react-router-dom";
import type { Auction } from "../api/types";
import { formatDateTime } from "../lib/datetime";
import { formatCents } from "../lib/money";
import StatusBadge from "./StatusBadge";

export default function AuctionCard({ auction }: { auction: Auction }) {
  return (
    <Link to={`/lotes/${auction.id}`} className="card auction-card">
      {auction.item_image_url ? (
        <img
          className="auction-thumb"
          src={auction.item_image_url}
          alt={auction.item_title}
          loading="lazy"
        />
      ) : (
        <div className="auction-thumb placeholder" aria-hidden="true">
          {auction.item_title.charAt(0).toUpperCase()}
        </div>
      )}
      <div className="auction-card-head">
        <h2>{auction.item_title}</h2>
        <StatusBadge status={auction.status} />
      </div>
      <p className="muted">Leiloeiro: {auction.seller_pseudonym}</p>
      <p>
        Lance inicial: <strong>{formatCents(auction.starting_bid_cents)}</strong>
      </p>
      <p className="muted">
        {auction.bid_count ?? 0} lance(s) · termina{" "}
        {formatDateTime(auction.ends_at)}
      </p>
    </Link>
  );
}
