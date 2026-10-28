import type { BidRejectionCode } from "../api/types";

const MESSAGES: Record<BidRejectionCode, string> = {
  invalid_amount: "O lance deve ser maior que zero.",
  below_minimum: "Seu lance está abaixo do mínimo exigido neste lote.",
  insufficient_balance:
    "Seu saldo disponível não cobre este lance. Adicione saldo na carteira.",
  auction_not_started: "Este lote ainda não começou a aceitar lances.",
  auction_ended: "Este lote já foi encerrado.",
  auction_cancelled: "Este lote foi cancelado.",
  seller_cannot_bid: "O leiloeiro não pode dar lances no próprio lote.",
  auctioneer_cannot_bid: "Leiloeiros não podem dar lances.",
  already_leader: "Você já é o maior lance deste lote.",
  inconsistent_state:
    "O estado do lote mudou. Atualize a página e tente de novo.",
};

export function bidRejectionMessage(
  code: string | null,
  detail: string,
): string {
  if (code && code in MESSAGES) {
    return MESSAGES[code as BidRejectionCode];
  }
  return detail;
}
