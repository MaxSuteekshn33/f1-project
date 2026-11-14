"use client";
import { useMemo, useState } from "react";
import { useApi, useRace } from "@/lib/api";
import { Driver, Notes, Panel, Stat, State, Tag, Tyre, fmtDur, fmtLap, num, pct, dt } from "@/components/ui";

const compass = (d?: number | null) => (d === null || d === undefined ? "" : ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Math.round(d / 45) % 8]);

export default function CommandCentre() {
  const r = useRace();
  const c = r.cmd;
  const [team, setTeam] = useState("");
  const [text, setText] = useState("");
  const [cont, setCont] = useState(false);
  const { data: wx } = useApi<any>(r.sessionKey ? `/api/weather?${r.q}` : null, r.tick);
  const teams = useMemo(() => Array.from(new Set((c?.rows || []).map((x: any) => x.team).filter(Boolean))).sort() as string[], [c]);
  const contenders: string[] = r.status?.contenders || [];
  const rows = (c?.rows || []).filter((x: any) => (!team || x.team === team) && (!cont || contenders.includes(x.code)) &&
    (!text || `${x.code} ${x.name}`.toLowerCase().includes(text.toLowerCase())));
  if (!c) return <State loading={r.cmdLoading} error={r.cmdError} />;
  const w = c.weather;
  const fs = wx?.forecast?.summary;
  const best = { lap: Math.min(...c.rows.map((x: any) => x.best_lap ?? 1e9)) };
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-1">
        <div>
          <div className="text-[10px] uppercase tracking-[.16em] text-faint">{c.session.year} · Round {c.f1db?.round ?? "—"} · {c.session.session_name}</div>
          <h1 className="text-2xl font-semibold tracking-tight">{c.title}</h1>
          <div className="text-xs text-dim">{c.circuit} · {c.session.location}, {c.session.country_name}</div>
        </div>
        <div className="ml-auto text-right text-[11px] text-faint">Timing as of {dt(c.as_of)} · source {c.source} <Tag kind="OBSERVED" /></div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <Stat label="Lap" value={<>{c.lap}<span className="text-faint"> / {c.total_laps ?? "—"}</span></>} sub={c.total_laps ? `${c.total_laps - c.lap} to go` : "distance unknown"} />
        <Stat label="Est. remaining" value={c.est_remaining_s ? fmtDur(c.est_remaining_s) : "—"} sub="laps left × leader's recent pace" tag="MODEL" />
        <Stat label="Fastest lap" value={fmtLap(c.fastest_lap?.time)} sub={c.fastest_lap ? `${c.fastest_lap.code} · lap ${c.fastest_lap.lap}` : "—"} />
        <Stat label="Neutralisations" value={<>{c.neutralisations.SC}<span className="text-faint text-sm"> SC</span> {c.neutralisations.VSC}<span className="text-faint text-sm"> VSC</span> {c.neutralisations.RED}<span className="text-faint text-sm"> RED</span></>} sub="so far this race" />
        <Stat label="Track / Air" value={w ? <>{num(w.track_temperature)}° <span className="text-faint">/</span> {num(w.air_temperature)}°</> : "—"} sub={w ? `humidity ${num(w.humidity, 0)}%` : "no track weather"} />
        <Stat label="Rain (track sensor)" value={w ? (w.rainfall ? "RAIN" : "DRY") : "—"} accent={w?.rainfall ? "#3d8bf2" : undefined} sub={w ? `${Math.round((w.rain_share_15min ?? 0) * 100)}% of last 15 min` : ""} />
        <Stat label="Precip. probability" tag="FORECAST" value={fs?.max_prob !== null && fs?.max_prob !== undefined ? `${fs.max_prob}%` : "—"}
          sub={wx?.forecast?.available === false ? "forecast unavailable" : wx ? `Open-Meteo, session window${wx.forecast?.kind === "analysis" ? " (hindsight)" : ""}` : "loading…"} />
        <Stat label="Wind" value={w ? <>{num(w.wind_speed)}<span className="text-sm text-faint"> m/s</span></> : "—"} sub={w ? `from ${compass(w.wind_direction)} (${num(w.wind_direction, 0)}°)` : ""} />
      </div>

      <Panel title="Timing tower" tags={["OBSERVED"]} pad={false}
        right={<>
          <input type="text" placeholder="Driver…" value={text} onChange={(e) => setText(e.target.value)} className="w-24" aria-label="Filter driver" />
          <select value={team} onChange={(e) => setTeam(e.target.value)} aria-label="Filter team"><option value="">All teams</option>{teams.map((t) => <option key={t}>{t}</option>)}</select>
          <label className="flex cursor-pointer items-center gap-1.5"><input type="checkbox" checked={cont} onChange={(e) => setCont(e.target.checked)} />Title contenders</label>
        </>}
        note={<>{c.prediction_note} Gaps are measured at each car's last timing-line crossing. Positions gained are relative to the first position record of the session (grid). {r.wsState === "open" ? "Updates are pushed over the WebSocket as new laps are stored." : "WebSocket not connected — refreshing every 60 s."}</>}>
        <div className="max-h-[640px] overflow-auto">
          <table className="grid-t">
            <thead><tr>
              <th>Pos</th><th>Driver</th><th>Team</th><th className="r">Lap</th><th className="r">Last lap</th><th className="r">Best</th><th className="r">Gap</th><th className="r">Int</th>
              <th>Tyre · age</th><th className="r">Stint</th><th className="r">Pits</th><th className="r">+/−</th><th className="r">Pred. finish <Tag kind="MODEL" /></th>
            </tr></thead>
            <tbody>
              {rows.map((x: any) => (
                <tr key={x.driver_number} className={x.driver_number === r.driver ? "bg-[#16191e]" : ""} onClick={() => r.setDriver(x.driver_number)} style={{ cursor: "pointer", opacity: x.status === "OUT" ? 0.45 : 1 }}>
                  <td className="num font-semibold">{x.position}</td>
                  <td><Driver code={x.code} colour={x.team_colour} name={x.name} /> <span className="ml-1 hidden text-dim xl:inline">{x.name}</span></td>
                  <td className="text-dim">{x.team}</td>
                  <td className="r num">{x.laps_done}</td>
                  <td className="r num">{fmtLap(x.last_lap)}</td>
                  <td className="r num" style={x.best_lap === best.lap ? { color: "#c084fc" } : undefined}>{fmtLap(x.best_lap)}</td>
                  <td className="r num">{x.gap ?? "—"}</td>
                  <td className="r num text-dim">{x.interval_s !== null && x.interval_s !== undefined && x.position > 1 ? `+${x.interval_s.toFixed(3)}` : "—"}</td>
                  <td><Tyre compound={x.compound} age={x.tyre_age} /></td>
                  <td className="r num">{x.stint ?? "—"}</td>
                  <td className="r num">{x.pit_stops}</td>
                  <td className="r num" style={{ color: x.gained > 0 ? "#2fbf71" : x.gained < 0 ? "#ff5a52" : "#6b717d" }}>{x.gained === null ? "—" : x.gained > 0 ? `▲${x.gained}` : x.gained < 0 ? `▼${-x.gained}` : "–"}</td>
                  <td className="r num">{x.pred_pos ? <>P{x.pred_pos}{x.p_win !== null && x.p_win > 0.005 ? <span className="ml-2 text-faint">{pct(x.p_win, 0)} win</span> : null}</> : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <Notes items={c.limitations} />
    </div>
  );
}
