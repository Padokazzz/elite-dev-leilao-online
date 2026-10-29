import { useEffect, useState } from "react";
import { getToken } from "../api/client";
import type {
  AuctionClosedEvent,
  BidPlacedEvent,
  RoomEvent,
  RoomSnapshot,
} from "../api/types";

const WS_BASE = (import.meta.env.VITE_API_URL ?? "http://localhost:8000")
  .replace(/^http/, "ws")
  .replace(/\/$/, "");

const CLOSE_UNAUTHENTICATED = 4401;
const CLOSE_UNKNOWN_AUCTION = 4404;
// Backoff capado: um deploy no backend derruba os sockets e leva ~1 minuto
// para voltar — desistir cedo faria a sala ficar muda até o reload manual.
const MAX_BACKOFF_MS = 10000;

type RoomUnavailable =
  | "unauthenticated"
  | "unknown"
  | "offline"
  | null;

export type RoomLive = {
  connected: boolean;
  snapshot: RoomSnapshot | null;
  bidEvents: BidPlacedEvent[];
  closed: AuctionClosedEvent | null;
  cancelled: boolean;
  unavailable: RoomUnavailable;
};

const INITIAL: RoomLive = {
  connected: false,
  snapshot: null,
  bidEvents: [],
  closed: null,
  cancelled: false,
  unavailable: null,
};

export default function useAuctionRoom(
  auctionId: number,
  authenticated: boolean,
): RoomLive {
  const [live, setLive] = useState<RoomLive>(INITIAL);
  const token = authenticated ? getToken() : null;

  useEffect(() => {
    if (!token || !Number.isFinite(auctionId)) {
      return;
    }

    let disposed = false;
    let attempts = 0;
    let terminal = false;
    let timer: number | null = null;
    let socket: WebSocket | null = null;

    function scheduleReconnect() {
      if (disposed) {
        return;
      }
      setLive((prev) => ({ ...prev, unavailable: "offline" }));
      attempts += 1;
      const delay = Math.min(1000 * 2 ** Math.min(attempts, 3), MAX_BACKOFF_MS);
      timer = window.setTimeout(connect, delay);
    }

    function connect() {
      if (disposed) {
        return;
      }
      socket = new WebSocket(
        `${WS_BASE}/ws/auctions/${auctionId}/?token=${token}`,
      );

      socket.onopen = () => {
        attempts = 0;
        setLive((prev) => ({ ...prev, connected: true, unavailable: null }));
      };

      socket.onmessage = (event) => {
        let message: RoomEvent;
        try {
          message = JSON.parse(event.data as string) as RoomEvent;
        } catch {
          return;
        }
        if (message.type === "room.snapshot") {
          setLive((prev) => ({ ...prev, snapshot: message }));
        } else if (message.type === "bid.placed") {
          setLive((prev) => ({ ...prev, bidEvents: [...prev.bidEvents, message] }));
        } else if (message.type === "auction.closed") {
          setLive((prev) => ({ ...prev, closed: message }));
        } else if (message.type === "auction.cancelled") {
          setLive((prev) => ({ ...prev, cancelled: true }));
        }
      };

      socket.onclose = (event) => {
        setLive((prev) => ({ ...prev, connected: false }));
        if (disposed) {
          return;
        }
        if (event.code === CLOSE_UNAUTHENTICATED) {
          terminal = true;
          setLive((prev) => ({ ...prev, unavailable: "unauthenticated" }));
          return;
        }
        if (event.code === CLOSE_UNKNOWN_AUCTION) {
          terminal = true;
          setLive((prev) => ({ ...prev, unavailable: "unknown" }));
          return;
        }
        scheduleReconnect();
      };
    }

    connect();

    // Volta imediatamente quando a rede/aba volta (sem esperar o backoff).
    function reconnectNow() {
      if (disposed || terminal) {
        return;
      }
      const state = socket?.readyState;
      if (state === WebSocket.OPEN || state === WebSocket.CONNECTING) {
        return;
      }
      if (timer !== null) {
        window.clearTimeout(timer);
        timer = null;
      }
      attempts = 0;
      connect();
    }

    function onVisible() {
      if (document.visibilityState === "visible") {
        reconnectNow();
      }
    }

    window.addEventListener("online", reconnectNow);
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      disposed = true;
      if (timer !== null) {
        window.clearTimeout(timer);
      }
      window.removeEventListener("online", reconnectNow);
      document.removeEventListener("visibilitychange", onVisible);
      socket?.close();
    };
  }, [auctionId, token]);

  return live;
}
