"use client";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartTip, GRID, SERIES, Tyre, num, pct, signed } from "@/components/ui";

/** Decision table shared by Weather, Safety Car and the Lab: one row per simulated option. */
export function OptionTable({ options, best, timeKey = "time_vs_best", timeLabel = "Time vs best" }: { options: any[]; best?: string; timeKey?: string; timeLabel?: string }) {
  return (
    <div className="overflow-auto"><table className="grid-t">
      <thead><tr><th>Option</th><th>Stops</th><th className="r">Exp. finish</th><th className="r">P10–P90</th><th className="r">Win</th><th className="r">Podium</th><th className="r">{timeLabel}</th><th className="r">Risk (pos. SD)</th><th className="r">Laps in traffic</th></tr></thead>
      <tbody>{options.map((o) => (
        <tr key={o.label} className={o.label === best ? "!bg-[#141a14]" : ""}>
          <td className="font-semibold">{o.label}{o.label === best && <span className="ml-2 rounded bg-good px-1.5 py-[1px] text-[9px] font-bold text-black">BEST</span>}</td>
          <td>{o.plan?.length ? o.plan.map((p: any, i: number) => <span key={i} className="mr-2 inline-flex items-center gap-1"><span className="num">L{p.lap}</span><Tyre compound={p.compound} /></span>) : <span className="text-faint">none</span>}</td>
          <td className="r num font-semibold">P{num(o.exp_pos)}</td><td className="r num text-dim">P{o.pos_p10}–P{o.pos_p90}</td><td className="r num">{pct(o.p_win)}<span className="text-faint"> ±{(o.p_win_se * 196).toFixed(1)}</span></td><td className="r num">{pct(o.p_podium)}</td>
          <td className="r num">{o[timeKey] === null || o[timeKey] === undefined ? "—" : `${signed(o[timeKey])} s`}</td><td className="r num text-dim">{num(o.risk_pos_sd, 2)}</td><td className="r num text-dim">{num(o.blocked_laps)}</td>
        </tr>))}</tbody>
    </table></div>
  );
}

/** Distribution of finishing positions for up to four options (grouped bars, fixed colour order). */
export function PositionDist({ options, maxPos = 12 }: { options: { label: string; pos_hist: number[] }[]; maxPos?: number }) {
  const opts = options.slice(0, 4);
  const data = Array.from({ length: maxPos }, (_, i) => { const row: any = { pos: `P${i + 1}` }; opts.forEach((o, k) => (row[`o${k}`] = (o.pos_hist?.[i] || 0) * 100)); return row; });
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: -18 }} barGap={2} barCategoryGap="18%">
        <CartesianGrid stroke={GRID} vertical={false} /><XAxis dataKey="pos" tickLine={false} axisLine={{ stroke: GRID }} /><YAxis tickFormatter={(v) => `${v}%`} tickLine={false} axisLine={false} width={52} />
        <Tooltip cursor={{ fill: "#ffffff08" }} content={<ChartTip fmt={(v: number) => `${v.toFixed(1)}%`} />} />{opts.length > 1 && <Legend />}
        {opts.map((o, k) => <Bar key={k} dataKey={`o${k}`} name={o.label} fill={SERIES[k]} radius={[3, 3, 0, 0]} isAnimationActive={false} />)}
      </BarChart>
    </ResponsiveContainer>
  );
}
