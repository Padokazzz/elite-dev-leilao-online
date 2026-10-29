type WithFlag = { is_you: boolean };

/**
 * Retorna o lance que derrubou a sua liderança, ou null.
 *
 * Regra do escopo (§02, sala do lote): indicador claro de
 * "você foi superado". Como toda oferta aceita leva quem deu lance à
 * liderança até ser superado, ter lances seus sem estar no topo
 * significa exatamente isso. Observador (sem lances) nunca é superado.
 */
export function supersedingBid<T extends WithFlag>(
  bids: readonly T[],
): T | null {
  const top = bids[0] ?? null;
  if (!top || top.is_you) {
    return null;
  }
  return bids.some((bid) => bid.is_you) ? top : null;
}
