import { describe, expect, it } from "vitest";
import { supersedingBid } from "./bids";

const you = { is_you: true, bidder_pseudonym: "Licitante #você" };
const other = { is_you: false, bidder_pseudonym: "Licitante #4821" };

describe("supersedingBid", () => {
  it("retorna null quando não há lances", () => {
    expect(supersedingBid([])).toBeNull();
  });

  it("retorna null quando você está na frente", () => {
    expect(supersedingBid([you, other])).toBeNull();
  });

  it("retorna null para quem nunca deu lance (observador)", () => {
    const observerView = [
      other,
      { is_you: false, bidder_pseudonym: "Licitante #1" },
    ];

    expect(supersedingBid(observerView)).toBeNull();
  });

  it("retorna o lance de topo quando você foi superado", () => {
    const top = { ...other, amount_cents: 12_000 };

    expect(supersedingBid([top, you])).toBe(top);
  });

  it("continua sinalizando superação depois de vários lances", () => {
    const top = { ...other, amount_cents: 15_000 };
    const middle = { ...other, amount_cents: 13_000 };

    expect(supersedingBid([top, middle, you])).toBe(top);
  });
});
