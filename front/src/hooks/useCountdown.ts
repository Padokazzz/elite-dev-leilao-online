import { useEffect, useState } from "react";

export function endsInMs(endsAt: string | null): number | null {
  if (!endsAt) {
    return null;
  }
  return new Date(endsAt).getTime() - Date.now();
}

export default function useCountdown(
  target: string | null,
  active: boolean,
): number | null {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!active || !target) {
      return;
    }
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active, target]);

  if (!target) {
    return null;
  }
  return new Date(target).getTime() - now;
}
