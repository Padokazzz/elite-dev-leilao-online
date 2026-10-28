export function formatCents(cents: number): string {
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
  }).format(cents / 100);
}

export function parseBrlToCents(text: string): number | null {
  const raw = text.trim();
  if (!raw || !/^[0-9.,]+$/.test(raw)) {
    return null;
  }

  let normalized: string;
  if (raw.includes(",")) {
    normalized = raw.replace(/\./g, "").replace(",", ".");
  } else if (raw.includes(".")) {
    const parts = raw.split(".");
    const lastSegment = parts[parts.length - 1];
    const isDecimal = parts.length === 2 && lastSegment.length <= 2;
    normalized = isDecimal ? raw : raw.replace(/\./g, "");
  } else {
    normalized = raw;
  }

  const value = Number(normalized);
  if (Number.isNaN(value) || value < 0) {
    return null;
  }
  return Math.round(value * 100);
}

export function centsToDecimalString(cents: number): string {
  return `${Math.floor(cents / 100)}.${String(cents % 100).padStart(2, "0")}`;
}

export function formatSignedCents(cents: number): string {
  const sign = cents > 0 ? "+ " : cents < 0 ? "− " : "";
  return sign + formatCents(Math.abs(cents));
}
