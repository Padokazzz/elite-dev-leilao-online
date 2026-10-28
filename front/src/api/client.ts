import type { ApiErrorBody } from "./types";

const BASE = (
  import.meta.env.VITE_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

const TOKEN_KEY = "token";

let onUnauthorized: (() => void) | null = null;

export function apiUrl(path: string): string {
  return `${BASE}${path}`;
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

function formatDetail(body: ApiErrorBody, status: number): string {
  if (Array.isArray(body.detail)) {
    return body.detail.join(" ");
  }
  if (typeof body.detail === "string") {
    return body.detail;
  }

  const fieldErrors = Object.entries(body)
    .filter(([, value]) => Array.isArray(value))
    .map(([field, value]) => `${field}: ${(value as string[]).join(", ")}`);

  if (fieldErrors.length > 0) {
    return fieldErrors.join("; ");
  }
  if (status === 429) {
    return "Muitas tentativas. Aguarde um minuto e tente de novo.";
  }
  return `Falha inesperada (HTTP ${status}).`;
}

export class ApiError extends Error {
  status: number;
  code: string | null;

  constructor(status: number, body: ApiErrorBody) {
    super(formatDetail(body, status));
    this.status = status;
    this.code = typeof body.code === "string" ? body.code : null;
  }
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  auth?: boolean;
};

async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { method = "GET", body, auth = true } = options;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const token = getToken();
  if (auth && token) {
    headers.Authorization = `Token ${token}`;
  }

  const response = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    if (response.status === 401 && auth) {
      clearToken();
      onUnauthorized?.();
    }
    throw new ApiError(response.status, data as ApiErrorBody);
  }

  return data as T;
}

export const api = {
  get: <T>(path: string, auth = true) => request<T>(path, { auth }),
  post: <T>(path: string, body?: unknown, auth = true) =>
    request<T>(path, { method: "POST", body, auth }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body }),
};
