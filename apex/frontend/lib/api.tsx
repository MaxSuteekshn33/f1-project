"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

export async function api<T = any>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, body === undefined ? { cache: "no-store" } :
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) {
    let msg = `${r.status}`;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}

/** GET with loading/error state. Pass null to skip. Keeps the previous data visible while refetching. */
export function useApi<T = any>(path: string | null, tick: number = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const seq = useRef(0);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!path) return;
    const id = ++seq.current;
    setLoading(true);
    api<T>(path).then((d) => { if (id === seq.current) { setData(d); setError(null); } })
      .catch((e) => { if (id === seq.current) setError(String(e.message || e)); })
      .finally(() => { if (id === seq.current) setLoading(false); });
  }, [path, tick, n]);
  return { data, error, loading, reload: useCallback(() => setN((x) => x + 1), []) };
}

type Race = {
  sessions: any[]; sessionKey: number | null; setSessionKey: (k: number) => void;
  lap: number | null; setLap: (l: number | null) => void; driver: number | null; setDriver: (d: number | null) => void;
  cmd: any | null; cmdError: string | null; cmdLoading: boolean; status: any | null; tick: number; alert: string | null; clearAlert: () => void;
  q: string; wsState: "connecting" | "open" | "closed";
};
const Ctx = createContext<Race>(null as any);
export const useRace = () => useContext(Ctx);

export function RaceProvider({ children }: { children: React.ReactNode }) {
  const [sessionKey, setKey] = useState<number | null>(null);
  const [lap, setLap] = useState<number | null>(null);
  const [driver, setDriver] = useState<number | null>(null);
  const [tick, setTick] = useState(0);
  const [alert, setAlert] = useState<string | null>(null);
  const [wsState, setWs] = useState<"connecting" | "open" | "closed">("connecting");
  const { data: status } = useApi<any>("/api/status", tick);
  const { data: sessions } = useApi<any[]>("/api/sessions", 0);
  useEffect(() => { if (status && sessionKey === null) setKey(status.default_session); }, [status, sessionKey]);
  const setSessionKey = useCallback((k: number) => { setKey(k); setLap(null); setDriver(null); }, []);
  const q = useMemo(() => {
    const p = new URLSearchParams();
    if (sessionKey) p.set("session_key", String(sessionKey));
    if (lap) p.set("lap", String(lap));
    return p.toString();
  }, [sessionKey, lap]);
  const { data: cmd, error: cmdError, loading: cmdLoading } = useApi<any>(sessionKey ? `/api/command?${q}` : null, tick);
  useEffect(() => {
    if (cmd && driver === null && cmd.rows?.length) setDriver(cmd.rows[0].driver_number);
  }, [cmd, driver]);
  // WebSocket: the backend pushes an update whenever new timing data is stored
  useEffect(() => {
    let ws: WebSocket | null = null, timer: any, stop = false;
    const url = process.env.NEXT_PUBLIC_WS_URL || `${location.protocol === "https:" ? "wss" : "ws"}://${location.hostname}:8000/ws/live`;
    const open = () => {
      if (stop) return;
      try { ws = new WebSocket(url); } catch { setWs("closed"); return; }
      ws.onopen = () => setWs("open");
      ws.onmessage = (e) => {
        try {
          const m = JSON.parse(e.data);
          if (m.type === "update") setTick((t) => t + 1);
          if (m.type === "weather_alert") { setAlert(m.message); setTick((t) => t + 1); }
        } catch {}
      };
      ws.onclose = () => { setWs("closed"); timer = setTimeout(open, 10000); };
      ws.onerror = () => ws?.close();
    };
    open();
    const poll = setInterval(() => setTick((t) => t + 1), 60000);   // fallback refresh when the socket is unavailable
    return () => { stop = true; clearTimeout(timer); clearInterval(poll); ws?.close(); };
  }, []);
  const value: Race = { sessions: sessions || [], sessionKey, setSessionKey, lap, setLap, driver, setDriver, cmd, cmdError, cmdLoading, status, tick,
    alert, clearAlert: () => setAlert(null), q, wsState };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
