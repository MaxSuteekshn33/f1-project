"use client";
import { useState } from "react";
import { CartesianGrid, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis, Cell, LabelList } from "recharts";
import { useApi } from "@/lib/api";
import { Bar, GRID, Notes, Panel, State, num, pct, teamColour } from "@/components/ui";

export default function Analytics() {
  const ov = useApi<any>("/api/history/overview");
  const [year, setYear] = useState<number | null>(null);
  const { data: d, loading, error } = useApi<any>(`/api/analytics${year ? `?year=${year}` : ""}`);
  if (!d) return <State loading={loading} error={error} />;
  const maxPts = Math.max(...d.constructors.map((c: any) => c.points), 1);
  const qr = d.drivers.filter((x: any) => x.starts >= 3 && x.avg_quali && x.avg_finish);
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3"><h1 className="text-xl font-semibold">{d.year} season</h1>
        <select value={year ?? d.year} onChange={(e) => setYear(Number(e.target.value))} aria-label="Season">{(ov.data?.seasons || [d.year]).map((y: number) => <option key={y}>{y}</option>)}</select>{loading && <span className="animate-pulse text-xs text-faint">loading…</span>}</div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <Panel title="Constructors" tags={["OBSERVED"]} pad={false}>
          <div className="overflow-auto"><table className="grid-t"><thead><tr><th>Constructor</th><th style={{ width: 170 }}>Points</th><th className="r">Wins</th><th className="r">Podiums</th><th className="r">Avg quali</th><th className="r">Avg finish</th><th className="r">DNF rate</th><th className="r">Mechanical DNF</th><th className="r">Pit lane (median)</th><th className="r">Speed trap</th></tr></thead>
            <tbody>{d.constructors.map((c: any) => <tr key={c.constructor_id}><td><span className="mr-2 inline-block h-3 w-1 rounded-sm align-middle" style={{ background: teamColour(c.colour) }} />{c.name}</td><td><Bar value={c.points} max={maxPts} colour={teamColour(c.colour)} label={String(c.points)} /></td>
              <td className="r num">{c.wins}</td><td className="r num">{c.podiums}</td><td className="r num">{num(c.avg_quali)}</td><td className="r num">{num(c.avg_finish)}</td><td className="r num">{pct(c.dnf_rate, 0)}</td><td className="r num">{pct(c.mech_dnf_rate, 0)}</td>
              <td className="r num">{c.pit_median_s ? `${c.pit_median_s.toFixed(2)} s` : "—"}<span className="text-faint"> ({c.pit_stops_n})</span></td><td className="r num">{c.speed_trap_kmh ? `${c.speed_trap_kmh} km/h` : "—"}</td></tr>)}</tbody></table></div>
        </Panel>
        <Panel title="Qualifying vs race — average position" tags={["OBSERVED"]} note="Each dot is a driver. Below the diagonal: finishes better than they qualify on average.">
          <ResponsiveContainer width="100%" height={330}>
            <ScatterChart margin={{ top: 10, right: 16, bottom: 18, left: -8 }}>
              <CartesianGrid stroke={GRID} /><XAxis type="number" dataKey="avg_quali" name="Avg qualifying" domain={[0, 22]} tickLine={false} axisLine={{ stroke: GRID }} label={{ value: "Average qualifying position", position: "insideBottom", offset: -10, fill: "#6b717d", fontSize: 10 }} />
              <YAxis type="number" dataKey="avg_finish" name="Avg finish" domain={[0, 22]} tickLine={false} axisLine={false} width={52} label={{ value: "Average finish", angle: -90, position: "insideLeft", offset: 22, fill: "#6b717d", fontSize: 10 }} /><ZAxis range={[70, 70]} />
              <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 22, y: 22 }]} stroke="#3a3f48" strokeDasharray="4 4" />
              <Tooltip cursor={{ strokeDasharray: "3 3" }} content={({ active, payload }: any) => active && payload?.length ? <div className="rounded border border-line bg-[#0d0f12] px-2.5 py-1.5 text-[11px]"><b>{payload[0].payload.name}</b><div className="num text-dim">quali {num(payload[0].payload.avg_quali)} · finish {num(payload[0].payload.avg_finish)}</div></div> : null} />
              <Scatter data={qr} isAnimationActive={false}>{qr.map((x: any, i: number) => <Cell key={i} fill={teamColour(x.colour)} stroke="#0a0b0d" strokeWidth={2} />)}<LabelList dataKey="code" position="top" fill="#a3a8b3" fontSize={9} /></Scatter>
            </ScatterChart></ResponsiveContainer>
        </Panel>
      </div>
      <Panel title="Drivers" tags={["OBSERVED"]} pad={false}>
        <div className="overflow-auto"><table className="grid-t"><thead><tr><th>Driver</th><th>Team</th><th className="r">Starts</th><th className="r">Points</th><th className="r">Wins</th><th className="r">Podiums</th><th className="r">Avg quali</th><th className="r">Avg grid</th><th className="r">Avg finish</th><th className="r">Positions gained / race</th><th className="r">Consistency (finish SD)</th><th className="r">DNFs</th><th className="r">Quali vs teammate</th><th className="r">Race vs teammate</th></tr></thead>
          <tbody>{d.drivers.map((x: any) => <tr key={x.driver_id}><td><span className="mr-2 inline-block h-3 w-1 rounded-sm align-middle" style={{ background: teamColour(x.colour) }} /><b>{x.code}</b> <span className="ml-1 text-dim">{x.name}</span></td><td className="text-dim">{x.constructor}</td><td className="r num">{x.starts}</td><td className="r num font-semibold">{x.points}</td><td className="r num">{x.wins}</td><td className="r num">{x.podiums}</td>
            <td className="r num">{num(x.avg_quali)}</td><td className="r num">{num(x.avg_grid)}</td><td className="r num">{num(x.avg_finish)}</td><td className="r num" style={{ color: x.avg_gain > 0.3 ? "#2fbf71" : x.avg_gain < -0.3 ? "#ff5a52" : undefined }}>{x.avg_gain === null ? "—" : `${x.avg_gain > 0 ? "+" : ""}${num(x.avg_gain)}`}</td><td className="r num">{num(x.finish_sd)}</td><td className="r num">{x.dnfs}</td><td className="r num">{x.quali_h2h ?? "—"}</td><td className="r num">{x.race_h2h ?? "—"}</td></tr>)}</tbody></table></div>
      </Panel>
      <Notes title="Notes & limits" items={d.notes} />
    </div>
  );
}
