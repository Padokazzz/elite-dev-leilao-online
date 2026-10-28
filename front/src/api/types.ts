export type Role = "bidder" | "auctioneer";

export type User = {
  id: number;
  username: string;
  email: string;
  role: Role;
};

export type LoginResponse = {
  token: string;
  user: User;
};

export type AuctionStatus = "scheduled" | "live" | "ended" | "cancelled";

export type Auction = {
  id: number;
  status: AuctionStatus;
  seller_pseudonym: string;
  item_id: number;
  item_title: string;
  item_image_url?: string | null;
  starting_bid_cents: number;
  minimum_increment_cents: number;
  starts_at: string;
  ends_at: string;
  winner_pseudonym: string | null;
  bid_count?: number;
  receipt_public_uuid?: string | null;
};

export type Paginated<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

export type ArtworkSearchResult = {
  id: string;
  title: string;
  description: string;
  image_url: string;
  /** image_id do ArtIC; vazio quando a obra não tem imagem. */
  image_id: string;
};

export type ImportedArtwork = {
  id: number;
  title: string;
  created: boolean;
};

export type MineAuction = Auction & {
  received_cents: number | null;
};

export type MineResponse = Paginated<MineAuction> & {
  summary: { total_received_cents: number };
};

export type BidRow = {
  seq: number;
  amount_cents: number;
  accepted_at: string;
  is_you: boolean;
};

export type BidsResponse = {
  results: BidRow[];
};

export type PlaceBidResponse = {
  bid: { seq: number; amount_cents: number; accepted_at: string };
  extended: boolean;
  ends_at: string;
  next_minimum_cents: number;
};

export type BidRejectionCode =
  | "invalid_amount"
  | "below_minimum"
  | "insufficient_balance"
  | "auction_not_started"
  | "auction_ended"
  | "auction_cancelled"
  | "seller_cannot_bid"
  | "auctioneer_cannot_bid"
  | "already_leader"
  | "inconsistent_state";

export type Wallet = {
  balance_cents: number;
  committed_cents: number;
  available_cents: number;
  updated_at: string;
};

export type WalletTransactionRow = {
  kind: string;
  kind_label: string;
  delta_cents: number;
  committed_delta_cents: number;
  description: string;
  auction_id: number | null;
  created_at: string;
};

export type TransactionsResponse = {
  results: WalletTransactionRow[];
};

export type MyBidState = "leading" | "outbid" | "won" | "cancelled";

export type MyBid = {
  seq: number;
  amount_cents: number;
  accepted_at: string;
  auction_id: number;
  auction_title: string;
  auction_status: AuctionStatus;
  ends_at: string;
  state: MyBidState;
  receipt_public_uuid: string | null;
};

export type RoomSnapshot = {
  type: "room.snapshot";
  auction_id: number;
  status: AuctionStatus;
  ends_at: string;
  starting_bid_cents: number;
  minimum_increment_cents: number;
  last_bid_cents: number | null;
  last_seq: number;
  you_lead: boolean;
};

export type BidPlacedEvent = {
  type: "bid.placed";
  bid: { seq: number; amount_cents: number; accepted_at: string };
  extended: boolean;
  ends_at: string;
  next_minimum_cents: number;
  is_you: boolean;
};

export type AuctionClosedEvent = {
  type: "auction.closed";
  auction_id: number;
  winner_pseudonym: string | null;
  receipt_public_uuid: string | null;
  amount_cents: number | null;
  you_won: boolean;
};

export type AuctionCancelledEvent = {
  type: "auction.cancelled";
  auction_id: number;
};

export type RoomEvent =
  | RoomSnapshot
  | BidPlacedEvent
  | AuctionClosedEvent
  | AuctionCancelledEvent;

export type Receipt = {
  public_uuid: string;
  auction_id: number;
  item_title: string;
  amount_cents: number;
  settled_at: string;
  winner: string;
  seller: string;
};

export type AuditRow = {
  seq: number;
  amount_cents: number;
  accepted_at: string;
  bidder: string;
};

export type AuditTamper = {
  seq: number;
  reason: "sequence_gap" | "prev_hash_mismatch" | "hash_mismatch";
  expected_seq?: number;
};

export type AuditReport = {
  auction_id: number;
  intact: boolean;
  chain: AuditRow[];
  tampered: AuditTamper | null;
};

export type ApiErrorBody = {
  code?: string;
  detail?: string | string[];
  [key: string]: unknown;
};
