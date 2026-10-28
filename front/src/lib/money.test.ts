import { describe, expect, it } from "vitest";
import {
  centsToDecimalString,
  formatCents,
  formatSignedCents,
  parseBrlToCents,
} from "./money";

describe("parseBrlToCents", () => {
  it("aceita inteiros sem separador", () => {
    expect(parseBrlToCents("50")).toBe(5000);
    expect(parseBrlToCents("0")).toBe(0);
  });

  it("trata vírgula como decimal no padrão pt-BR", () => {
    expect(parseBrlToCents("50,5")).toBe(5050);
    expect(parseBrlToCents("50,00")).toBe(5000);
    expect(parseBrlToCents("1.234,56")).toBe(123456);
  });

  it("trata ponto com uma ou duas casas como decimal", () => {
    expect(parseBrlToCents("50.5")).toBe(5050);
    expect(parseBrlToCents("50.25")).toBe(5025);
  });

  it("trata ponto com três casas ou agrupamento como milhar", () => {
    expect(parseBrlToCents("1.000")).toBe(100000);
    expect(parseBrlToCents("1.234.567")).toBe(123456700);
  });

  it("rejeita entradas inválidas", () => {
    expect(parseBrlToCents("")).toBeNull();
    expect(parseBrlToCents("   ")).toBeNull();
    expect(parseBrlToCents("abc")).toBeNull();
    expect(parseBrlToCents("-5")).toBeNull();
    expect(parseBrlToCents("R$ 10")).toBeNull();
    expect(parseBrlToCents(".")).toBeNull();
  });
});

describe("centsToDecimalString", () => {
  it("converte centavos para decimal sem ponto flutuante", () => {
    expect(centsToDecimalString(1050)).toBe("10.50");
    expect(centsToDecimalString(5)).toBe("0.05");
    expect(centsToDecimalString(100000)).toBe("1000.00");
    expect(centsToDecimalString(0)).toBe("0.00");
  });
});

describe("formatCents", () => {
  it("formata em BRL com a vírgula de centavos", () => {
    expect(formatCents(123456)).toBe("R$ 1.234,56");
    expect(formatCents(0)).toBe("R$ 0,00");
  });
});

describe("formatSignedCents", () => {
  it("sinaliza entradas e saídas", () => {
    expect(formatSignedCents(1000)).toBe("+ R$ 10,00");
    expect(formatSignedCents(-1000)).toBe("− R$ 10,00");
    expect(formatSignedCents(0)).toBe("R$ 0,00");
  });
});
