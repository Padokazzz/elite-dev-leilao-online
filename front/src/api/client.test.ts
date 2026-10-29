import { describe, expect, it } from "vitest";
import { ApiError } from "./client";

describe("ApiError", () => {
  it("prefere a mensagem de detalhe do servidor", () => {
    expect(
      new ApiError(400, { detail: "Mensagem do servidor." }).message,
    ).toBe("Mensagem do servidor.");
  });

  it("junta um array de detalhes", () => {
    expect(
      new ApiError(400, { detail: ["Erro um.", "Erro dois."] }).message,
    ).toBe("Erro um. Erro dois.");
  });

  it("rotula campos conhecidos em português", () => {
    expect(
      new ApiError(400, {
        email: ["Insira um endereço de e-mail válido."],
      }).message,
    ).toBe("e-mail: Insira um endereço de e-mail válido.");
  });

  it("mantém o nome cru quando o campo é desconhecido", () => {
    expect(
      new ApiError(400, { campo_x: ["Inválido."] }).message,
    ).toBe("campo_x: Inválido.");
  });

  it("cai em uma mensagem amigável por status quando não há corpo", () => {
    expect(new ApiError(403, {}).message).toBe(
      "Você não tem permissão para esta ação.",
    );
    expect(new ApiError(404, {}).message).toBe(
      "Não encontrei o que você pediu.",
    );
    expect(new ApiError(503, {}).message).toContain("acordando");
  });

  it("expõe o status e o code quando presentes", () => {
    const error = new ApiError(400, {
      detail: "ok",
      code: "below_minimum",
    });

    expect(error.status).toBe(400);
    expect(error.code).toBe("below_minimum");
  });
});
