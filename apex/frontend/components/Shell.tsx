"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useRace } from "@/lib/api";

const NAV = [
  ["/", "Race Command Centre"], ["/telemetry", "Live Timing & Telemetry"], ["/predictor", "AI Race Predictor"],
  ["/strategy", "Pit Stop & Tyre Strategy"], ["/weather", "Weather Intelligence"], ["/lab", "Race Simulation Lab"],
  ["/history", "Historical Race Intelligence"], ["/analytics", "Driver & Constructor Analytics"],
  ["/advisor", "AI Strategic Recommendations"], ["/data", "Data Sources & Model Performance"],
];
const MODE: Record<string, string> = { LIVE: "bg-good text-black", DELAYED: "bg-warn text-black", HISTORICAL: "bg-[#2a2e36] text-ink" };
const STATUS: Record<string, [string, string]> = {
  GREEN: ["GREEN", "text-good border-good/40"], SC: ["SAFETY CAR", "text-warn border-warn/50"], SC_ENDING: ["SC IN THIS LAP", "text-warn border-warn/50"],
  VSC: ["VIRTUAL SC", "text-warn border-warn/50"], RED: ["RED FLAG", "text-bad border-bad/50"], FINISHED: ["CHEQUERED", "text-ink border-line"],
  UNKNOWN: ["NO DATA", "text-faint border-line"],
};

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const r = useRace();
  const cmd = r.cmd;
  const maxLap = cmd?.max_lap || 0;
  const lap = r.lap ?? maxLap;
  const [playing, setPlaying] = useState(false);
  const lapRef = useRef(lap);
  lapRef.current = lap;
  useEffect(() => {   // race replay: advance one lap every 2.5 s
    if (!playing) return;
    const t = setInterval(() => {
      if (lapRef.current >= maxLap) { setPlaying(false); return; }
      r.setLap(lapRef.current + 1);
    }, 2500);
    return () => clearInterval(t);
  }, [playing, maxLap]); // eslint-disable-line
  const mode = cmd?.mode?.mode || "HISTORICAL";
  const st = STATUS[cmd?.track_status || "UNKNOWN"] || STATUS.UNKNOWN;
  const replaying = r.lap !== null && r.lap < maxLap;
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-[232px] shrink-0 flex-col border-r border-line bg-[#0d0e11] md:flex">
        <div className="border-b border-line px-4 py-4">
          <div className="flex items-center gap-2"><span className="h-5 w-1.5 -skew-x-12 bg-f1" /><span className="text-[15px] font-bold tracking-[.18em]">APEX</span></div>
          <div className="mt-0.5 text-[10px] uppercase tracking-[.2em] text-faint">F1 Intelligence</div>
        </div>
        <nav className="flex-1 overflow-y-auto py-2">
          {NAV.map(([href, label], i) => {
            const on = path === href;
            return (
              <Link key={href} href={href} className={`flex items-center gap-3 border-l-2 px-4 py-2 text-[12.5px] transition-colors ${on ? "border-f1 bg-panel text-ink" : "border-transparent text-dim hover:bg-panel hover:text-ink"}`}>
                <span className="num w-4 text-[10px] text-faint">{String(i + 1).padStart(2, "0")}</span>{label}
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-line px-4 py-3 text-[10px] leading-relaxed text-faint">
          Feed socket: <span className={r.wsState === "open" ? "text-good" : "text-dim"}>{r.wsState}</span><br />
          Data: OpenF1 · F1DB · Jolpica · Open-Meteo
        </div>
      </aside>
      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-20 border-b border-line bg-[#0d0e11]/95 backdrop-blur">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2">
            <select className="md:hidden" value={path} onChange={(e) => (location.href = e.target.value)} aria-label="Section">
              {NAV.map(([h, l]) => <option key={h} value={h}>{l}</option>)}
            </select>
            <span className={`rounded px-2 py-0.5 text-[10px] font-bold tracking-[.14em] ${MODE[mode]}`} title={cmd?.mode?.reason}>{mode}</span>
            <select value={r.sessionKey ?? ""} onChange={(e) => r.setSessionKey(Number(e.target.value))} aria-label="Race" className="max-w-[230px]">
              {r.sessions.map((s) => <option key={s.session_key} value={s.session_key}>{s.year} · {s.location} ({s.circuit_short_name})</option>)}
            </select>
            <div className="flex items-center gap-2">
              <span className="text-[10px] uppercase tracking-[.12em] text-faint">As of lap</span>
              <input type="range" min={1} max={Math.max(1, maxLap)} value={lap} onChange={(e) => { setPlaying(false); r.setLap(Number(e.target.value) >= maxLap ? null : Number(e.target.value)); }}
                className="w-40 lg:w-64" aria-label="As-of lap" />
              <span className="num w-14 text-sm font-semibold">{lap}<span className="text-faint">/{cmd?.total_laps ?? "—"}</span></span>
              <button className="btn" onClick={() => { if (!playing && lap >= maxLap) r.setLap(1); setPlaying(!playing); }}>{playing ? "Pause" : "Replay ▶"}</button>
              <button className="btn" disabled={!replaying} onClick={() => { setPlaying(false); r.setLap(null); }}>Latest</button>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] uppercase tracking-[.12em] text-faint">Focus</span>
              <select value={r.driver ?? ""} onChange={(e) => r.setDriver(Number(e.target.value))} aria-label="Focus driver">
                {(cmd?.rows || []).map((d: any) => <option key={d.driver_number} value={d.driver_number}>P{d.position} {d.code} · {d.team}</option>)}
              </select>
            </div>
            <span className={`ml-auto rounded border px-2 py-0.5 text-[10px] font-bold tracking-[.14em] ${st[1]}`}>{st[0]}</span>
          </div>
          {(mode !== "LIVE" || replaying) && (
            <div className="border-t border-line bg-[#101216] px-4 py-1 text-[11px] text-dim">
              {replaying ? <>REPLAY — every module shows only what was known at the end of lap {lap}. </> : null}{cmd?.mode?.reason}
            </div>
          )}
          {r.alert && <div className="flex items-center gap-3 border-t border-warn/40 bg-[#211a08] px-4 py-1.5 text-xs text-warn">{r.alert}<button className="btn ml-auto" onClick={r.clearAlert}>Dismiss</button></div>}
        </header>
        <main className="mx-auto max-w-[1700px] p-4">{children}</main>
      </div>
    </div>
  );
}
