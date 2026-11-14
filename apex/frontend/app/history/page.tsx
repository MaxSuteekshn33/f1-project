"use client";
import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useApi, useRace } from "@/lib/api";
import { ChartTip, GRID, Notes, Panel, SERIES, State, Tag, num, pct, teamColour } from "@/components/ui";

export default function History() {
  const r = useRace();
  const ov = useApi<any>("/api/history/overview");
  const [year, setYear] = useState<number | null>(null);
  const [circuit, setCircuit] = useState<string | null>(null);
  const [driver, setDriver] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => { if (ov.data && year === null) setYear(ov.data.seasons[0]); }, [ov.data, year]);
  useEffect(() => { if (r.cmd?.f1db?.circuit_id && circuit === null) setCircuit(r.cmd.f1db.circuit_id); }, [r.cmd, circuit]);
  useEffect(() => { const t = setTimeout(() => setQuery(text.trim()), 300); return () => clearTimeout(t); }, [text]);
  const sim = useApi<any>(r.sessionKey ? `/api/history/similar?${r.q}` : null, r.tick);
  const se = useApi<any>(year ? `/api/history/season/${year}` : null);
  const ci = useApi<any>(circuit ? `/api/history/circuit/${circuit}` : null);
  const dr = useApi<any>(driver ? `/api/history/driver/${driver}` : null);
  const sr = useApi<any>(query.length >= 2 ? `/api/history/search?q=${encodeURIComponent(query)}` : null);
  const s = sim.data;
  return (
    <div className="space-y-4">
      <Panel title="Search the database" tags={["OBSERVED"]} right={ov.data && <span>{ov.data.coverage.races} races · {ov.data.coverage.first}–{ov.data.coverage.last} · {ov.data.openf1_races} with lap-level data</span>}>
        <input type="text" className="w-full max-w-xl" placeholder="Driver, constructor, circuit or Grand Prix…" value={text} onChange={(e) => setText(e.target.value)} aria-label="Search" />
        {sr.data && (
          <div className="mt-3 grid gap-3 text-xs md:grid-cols-4">
            <div><div className="mb-1 text-[10px] uppercase tracking-[.12em] text-faint">Drivers</div>{sr.data.drivers.map((x: any) => <button key={x.id} className="btn mb-1 mr-1" onClick={() => setDriver(x.id)}>{x.name} <span className="text-faint">{x.wins}W/{x.starts}</span></button>)}{!sr.data.drivers.length && <span className="text-faint">none</span>}</div>
            <div><div className="mb-1 text-[10px] uppercase tracking-[.12em] text-faint">Circuits</div>{sr.data.circuits.map((x: any) => <button key={x.id} className="btn mb-1 mr-1" onClick={() => setCircuit(x.id)}>{x.name}</button>)}{!sr.data.circuits.length && <span className="text-faint">none</span>}</div>
            <div><div className="mb-1 text-[10px] uppercase tracking-[.12em] text-faint">Constructors</div>{sr.data.constructors.map((x: any) => <span key={x.id} className="mb-1 mr-2 inline-block text-dim">{x.name} <span className="text-faint">{x.wins}W</span></span>)}{!sr.data.constructors.length && <span className="text-faint">none</span>}</div>
            <div><div className="mb-1 text-[10px] uppercase tracking-[.12em] text-faint">Races</div>{sr.data.races.map((x: any) => <button key={x.id} className="btn mb-1 mr-1" onClick={() => setYear(x.year)}>{x.year} {x.name}</button>)}{!sr.data.races.length && <span className="text-faint">none</span>}</div>
          </div>
        )}
      </Panel>

      <Panel title={`Races resembling the current conditions${s?.lap ? ` (as of lap ${s.lap})` : ""}`} tags={["OBSERVED", "HISTORICAL"]} pad={false} note={s?.available ? <>{s.method} <b className="text-dim">{s.caveat}</b></> : undefined}>
        <State loading={sim.loading} error={sim.error} empty={s && !s.available ? s.reason : null}>
          {s?.available && (<>
            <div className="num flex flex-wrap gap-x-6 gap-y-1 border-b border-line px-3 py-2 text-xs text-dim">Current race so far: <span>track <b className="text-ink">{num(s.current.track_temp)}°C</b></span><span>air <b className="text-ink">{num(s.current.air_temp)}°C</b></span><span>humidity <b className="text-ink">{num(s.current.humidity, 0)}%</b></span><span>wind <b className="text-ink">{num(s.current.wind)} m/s</b></span><span>rain share <b className="text-ink">{pct(s.current.rain_share, 0)}</b></span></div>
            <div className="overflow-auto"><table className="grid-t"><thead><tr><th>Race</th><th>Same circuit</th><th className="r">Distance</th><th className="r">Track °C</th><th className="r">Air °C</th><th className="r">Rain share</th><th className="r">Grid overlap</th><th className="r">SC</th><th className="r">VSC</th><th className="r">Red</th><th className="r">Avg stops</th><th>Winner</th><th>Winning strategy</th><th className="r">Winner's 1st stop</th></tr></thead>
              <tbody>{s.similar.map((x: any) => <tr key={x.session_key}><td className="font-semibold"><button className="hover:underline" onClick={() => r.setSessionKey(x.session_key)} title="Open this race">{x.year} {x.location}</button></td><td>{x.same_circuit ? <span className="text-good">yes</span> : <span className="text-faint">no</span>}</td><td className="r num">{num(x.distance, 2)}</td>
                <td className="r num">{num(x.track_temp)}</td><td className="r num">{num(x.air_temp)}</td><td className="r num">{pct(x.rain_share, 0)}</td><td className="r num">{x.grid_overlap === null ? "—" : pct(x.grid_overlap, 0)}</td><td className="r num">{x.sc ?? 0}</td><td className="r num">{x.vsc ?? 0}</td><td className="r num">{x.red ?? 0}</td><td className="r num">{num(x.avg_stops)}</td>
                <td>{x.winner ?? "—"}</td><td className="num text-dim">{x.winner_strategy ?? "—"}</td><td className="r num">{x.winner_first_stop ? `L${x.winner_first_stop}` : "—"}</td></tr>)}</tbody></table></div>
            {s.previous_at_circuit_f1db.length > 0 && <div className="border-t border-line"><div className="px-3 pt-2 text-[10px] font-semibold uppercase tracking-[.12em] text-faint">Previous five races at this circuit (F1DB)</div>
              <table className="grid-t"><thead><tr><th>Year</th><th>Winner</th><th>Constructor</th><th className="r">Winner's grid</th><th className="r">Winner's stops</th><th className="r">Retirements</th></tr></thead>
                <tbody>{s.previous_at_circuit_f1db.map((x: any) => <tr key={x.year}><td className="num">{x.year}</td><td>{x.winner}</td><td className="text-dim">{x.constructor}</td><td className="r num">{x.winner_grid ?? "—"}</td><td className="r num">{x.winner_stops ?? "—"}</td><td className="r num">{x.dnfs}</td></tr>)}</tbody></table></div>}
          </>)}
        </State>
      </Panel>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Season" tags={["OBSERVED"]} pad={false} right={<select value={year ?? ""} onChange={(e) => setYear(Number(e.target.value))} aria-label="Season">{(ov.data?.seasons || []).map((y: number) => <option key={y}>{y}</option>)}</select>}>
          <State loading={se.loading} error={se.error}>
            {se.data && (<>
              {se.data.progression.length > 1 && <div className="px-2 pt-3"><ResponsiveContainer width="100%" height={220}>
                <LineChart data={se.data.progression} margin={{ top: 4, right: 10, bottom: 0, left: -14 }}><CartesianGrid stroke={GRID} vertical={false} /><XAxis dataKey="round" tickFormatter={(v) => `R${v}`} tickLine={false} axisLine={{ stroke: GRID }} /><YAxis tickLine={false} axisLine={false} width={52} />
                  <Tooltip content={<ChartTip title={(l: number) => `After round ${l}`} fmt={(v: number) => `${v} pts`} />} /><Legend iconType="plainline" />
                  {se.data.progression_keys.map((k: any, i: number) => <Line key={k.driver_id} dataKey={k.driver_id} name={k.code} stroke={k.colour ? teamColour(k.colour) : SERIES[i % 4]} strokeDasharray={se.data.progression_keys.findIndex((z: any) => z.colour === k.colour) !== i ? "5 3" : undefined} strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />)}
                </LineChart></ResponsiveContainer><div className="px-1 pb-1 text-[10px] text-faint">Championship points, top six. Teammates share a team colour; the second is dashed.</div></div>}
              <div className="max-h-[300px] overflow-auto"><table className="grid-t"><thead><tr><th>Rd</th><th>Grand Prix</th><th>Winner</th><th>Constructor</th><th className="r">From grid</th><th className="r">Stops</th><th className="r">DNFs</th></tr></thead>
                <tbody>{se.data.races.map((x: any) => <tr key={x.race_id}><td className="num">{x.round}</td><td><button className="hover:underline" onClick={() => setCircuit(x.circuit_id)}>{x.gp}</button></td><td>{x.winner ? <button className="hover:underline" onClick={() => setDriver(x.winner_id)}>{x.winner}</button> : <span className="text-faint">not yet run</span>}</td><td className="text-dim">{x.constructor}</td><td className="r num">{x.winner_grid ?? "—"}</td><td className="r num">{x.winner_stops ?? "—"}</td><td className="r num">{x.winner ? x.dnfs : "—"}</td></tr>)}</tbody></table></div>
              <div className="grid grid-cols-2 border-t border-line">
                <div className="max-h-[220px] overflow-auto border-r border-line"><table className="grid-t"><thead><tr><th>#</th><th>Driver</th><th className="r">Pts</th></tr></thead><tbody>{se.data.drivers.map((x: any) => <tr key={x.driver_id}><td className="num">{x.pos}</td><td><button className="hover:underline" onClick={() => setDriver(x.driver_id)}>{x.name}</button></td><td className="r num">{x.points}</td></tr>)}</tbody></table></div>
                <div className="max-h-[220px] overflow-auto"><table className="grid-t"><thead><tr><th>#</th><th>Constructor</th><th className="r">Pts</th></tr></thead><tbody>{se.data.constructors.map((x: any) => <tr key={x.constructor_id}><td className="num">{x.pos}</td><td>{x.name}</td><td className="r num">{x.points}</td></tr>)}</tbody></table></div>
              </div>
            </>)}
          </State>
        </Panel>

        <Panel title={`Circuit${ci.data?.circuit ? ` — ${ci.data.circuit.full_name}` : ""}`} tags={["OBSERVED"]} pad={false}
          right={<select value={circuit ?? ""} onChange={(e) => setCircuit(e.target.value)} aria-label="Circuit" className="max-w-[220px]">{(ov.data?.circuits || []).map((c: any) => <option key={c.id} value={c.id}>{c.name} ({c.races})</option>)}</select>}
          note={ci.data?.notes?.join(" ")}>
          <State loading={ci.loading} error={ci.error} empty={ci.data && !ci.data.available ? ci.data.reason : null}>
            {ci.data?.available && (<>
              <div className="grid gap-2 px-2 pt-3 md:grid-cols-2">
                <div><div className="px-1 text-[10px] uppercase tracking-[.12em] text-faint">Wins by grid position</div><ResponsiveContainer width="100%" height={170}><BarChart data={ci.data.wins_by_grid.filter((x: any) => x.grid <= 12)} margin={{ top: 4, right: 6, bottom: 0, left: -26 }}><CartesianGrid stroke={GRID} vertical={false} /><XAxis dataKey="grid" tickFormatter={(v) => `P${v}`} tickLine={false} axisLine={{ stroke: GRID }} /><YAxis allowDecimals={false} tickLine={false} axisLine={false} width={52} /><Tooltip cursor={{ fill: "#ffffff08" }} content={<ChartTip title={(l: number) => `Started P${l}`} />} /><Bar dataKey="wins" name="Wins" fill={SERIES[0]} radius={[3, 3, 0, 0]} isAnimationActive={false} /></BarChart></ResponsiveContainer></div>
                <div><div className="px-1 text-[10px] uppercase tracking-[.12em] text-faint">Average first-stop lap by year</div><ResponsiveContainer width="100%" height={170}><BarChart data={[...ci.data.first_stop].reverse()} margin={{ top: 4, right: 6, bottom: 0, left: -26 }}><CartesianGrid stroke={GRID} vertical={false} /><XAxis dataKey="year" tickLine={false} axisLine={{ stroke: GRID }} /><YAxis tickLine={false} axisLine={false} width={52} /><Tooltip cursor={{ fill: "#ffffff08" }} content={<ChartTip fmt={(v: number) => `lap ${v.toFixed(1)}`} />} /><Bar dataKey="first_stop_lap" name="First stop" fill={SERIES[2]} radius={[3, 3, 0, 0]} isAnimationActive={false} /></BarChart></ResponsiveContainer></div>
              </div>
              <div className="max-h-[330px] overflow-auto"><table className="grid-t"><thead><tr><th>Year</th><th>Winner</th><th>Constructor</th><th className="r">Grid</th><th className="r">Stops</th><th className="r">Field avg stops</th><th className="r">DNFs</th><th className="r">Fastest lap</th><th className="r">Race time</th></tr></thead>
                <tbody>{ci.data.races.map((x: any) => <tr key={x.race_id}><td className="num">{x.year}</td><td>{x.winner}</td><td className="text-dim">{x.constructor}</td><td className="r num">{x.winner_grid ?? "—"}</td><td className="r num">{x.winner_stops ?? "—"}</td><td className="r num">{num(x.avg_stops)}</td><td className="r num">{x.dnfs}</td><td className="r num">{x.fastest_ms ? `${Math.floor(x.fastest_ms / 60000)}:${((x.fastest_ms % 60000) / 1000).toFixed(3).padStart(6, "0")}` : "—"}</td><td className="r num text-dim">{x.race_time ?? "—"}</td></tr>)}</tbody></table></div>
              <div className="num flex flex-wrap gap-x-5 gap-y-1 border-t border-line px-3 py-2 text-[11px] text-dim">Most wins: {ci.data.most_wins.map((x: any) => <span key={x.name}>{x.name} <b className="text-ink">{x.wins}</b></span>)}</div>
              <div className="num flex flex-wrap gap-x-5 gap-y-1 border-t border-line px-3 py-2 text-[11px] text-dim">Avg positions changed per car: {ci.data.position_change.slice(0, 8).map((x: any) => <span key={x.year}>{x.year} <b className="text-ink">{num(x.avg_abs_change)}</b></span>)}</div>
            </>)}
          </State>
        </Panel>
      </div>

      {driver && (
        <Panel title={`Driver — ${dr.data?.driver?.name ?? driver}`} tags={["OBSERVED"]} pad={false} right={<button className="btn" onClick={() => setDriver(null)}>Close</button>}>
          <State loading={dr.loading} error={dr.error}>
            {dr.data?.available && (
              <div className="grid xl:grid-cols-2">
                <div className="max-h-[360px] overflow-auto border-r border-line"><table className="grid-t"><thead><tr><th>Season</th><th className="r">Starts</th><th className="r">Wins</th><th className="r">Podiums</th><th className="r">Points</th><th className="r">Avg grid</th><th className="r">Avg finish</th><th className="r">Avg gain</th><th className="r">DNFs</th></tr></thead>
                  <tbody>{[...dr.data.seasons].reverse().map((x: any) => <tr key={x.year}><td className="num">{x.year}</td><td className="r num">{x.starts}</td><td className="r num">{x.wins}</td><td className="r num">{x.podiums}</td><td className="r num">{x.points}</td><td className="r num">{num(x.avg_grid)}</td><td className="r num">{num(x.avg_finish)}</td><td className="r num">{num(x.avg_gain)}</td><td className="r num">{x.dnfs}</td></tr>)}</tbody></table></div>
                <div className="max-h-[360px] overflow-auto"><table className="grid-t"><thead><tr><th>Circuit (best average finish first)</th><th className="r">Starts</th><th className="r">Wins</th><th className="r">Avg grid</th><th className="r">Avg finish</th></tr></thead>
                  <tbody>{dr.data.circuits.map((x: any) => <tr key={x.circuit_id}><td><button className="hover:underline" onClick={() => setCircuit(x.circuit_id)}>{x.name}</button></td><td className="r num">{x.starts}</td><td className="r num">{x.wins}</td><td className="r num">{num(x.avg_grid)}</td><td className="r num">{num(x.avg_finish)}</td></tr>)}</tbody></table></div>
              </div>
            )}
          </State>
        </Panel>
      )}
      <Notes items={["Weather, tyre compounds, Safety Car periods and lap times exist only for races from 2023 (OpenF1). Earlier seasons are results-level (F1DB): grids, results, pit stops from 1994, retirements.",
        "“Overtaking” is approximated by grid-to-finish position change; true on-track passes are not recorded in these sources."]} />
    </div>
  );
}
