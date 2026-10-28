export function formatCents(cents: number): string {
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
  }).format(cents / 100);
}

export function parseBrlToCents(text: string): number | null {
  const normalized = text.trim().replace(/\./g, "").replace(",", ".");
  if (!normalized) {
    return null;
  }
  const value = Number(normalized);
  if (Number.isNaN(value) || value < 0) {
    return null;
  }
  return Math.round(value * 100);
}
