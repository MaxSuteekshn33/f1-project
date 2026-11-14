"use client";
import { CartesianGrid, Legend, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { useApi, useRace } from "@/lib/api";
import { COMPOUND, ChartTip, Driver, GRID, Notes, Panel, Stat, State, Tag, Tyre, fmtLap, num, pct, signed } from "@/components/ui";

function Stints({ stints, total, lap, plan }: { stints: any[]; total: number; lap: number; plan?: any[] }) {
  const w = (a: number, b: number) => `${((b - a + 1) / total) * 100}%`;
  return (
    <div className="relative h-5 w-full rounded-sm bg-[#1c1f25]">
      {stints.map((s, i) => (
        <div key={i} className="absolute top-0 flex h-5 items-center justify-center rounded-sm text-[9px] font-bold text-black" title={`${s.compound} laps ${s.from}–${s.to}`}
          style={{ left: `${((s.from - 1) / total) * 100}%`, width: `calc(${w(s.from, s.to)} - 2px)`, background: COMPOUND[s.compound]?.c || "#6b717d", opacity: s.future ? 0.45 : 1 }}>{COMPOUND[s.compound]?.l}</div>
      ))}
      <div className="absolute top-[-3px] h-[26px] w-px bg-white" style={{ left: `${(lap / total) * 100}%` }} />
    </div>
  );
}

export default function Strategy() {
  const r = useRace();
  const { data: s, loading, error } = useApi<any>(r.sessionKey && r.driver ? `/api/strategy?${r.q}&driver=${r.driver}` : null, r.tick);
  if (!s) return <State loading={loading} error={error} />;
  const tm = s.tyre_model;
  const mine = s.stints.filter((x: any) => x.driver_number === s.focus);
  const rec = s.strategies.find((x: any) => x.recommended);
  const degBy: Record<string, any[]> = {};
  for (const p of s.deg_points) (degBy[p.compound] = degBy[p.compound] || []).push(p);
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        <Stat label="Focus driver" value={s.focus_code ?? "—"} sub={`lap ${s.lap} of ${s.total_laps}`} />
        <Stat label="Pit loss (green)" value={<>{s.pit_loss.seconds}<span className="text-sm text-faint"> s</span></>} sub={s.pit_loss.source} tag={s.pit_loss.source.startsWith("measured") ? "OBSERVED" : "HISTORICAL"} />
        <Stat label="Pit loss SC / VSC" value={<>{s.pit_loss.under_sc} <span className="text-faint">/</span> {s.pit_loss.under_vsc}<span className="text-sm text-faint"> s</span></>} sub="assumed 45% / 62% of green" tag="ASSUMPTION" />
        <Stat label="Optimal pit window" tag="MODEL" value={s.window ? `L${s.window.open}–${s.window.close}` : "—"} sub={s.window ? `best lap ${s.window.optimal} (±${s.window.tolerance_s} s band)` : "no stop planned / wet running"} />
        <Stat label="Clean laps in fit" value={tm.n_clean_laps} sub={`prior: ${tm.prior}`} />
        <Stat label="Lap-time trend" value={<>{signed(tm.lap_trend_s_per_lap, 3)}<span className="text-sm text-faint"> s/lap</span></>} sub="fuel burn + track evolution" tag="MODEL" />
      </div>
      {s.note && <State empty={s.note} />}

      <Panel title={`Strategy options for ${s.focus_code ?? "—"} from lap ${s.lap}`} tags={["MODEL"]} pad={false} note={<>{s.method} {s.n_sims ? `${s.n_sims} simulations per option, same random futures for each.` : ""} “Model Δ” is the optimiser's deterministic time; “Sim Δ” includes traffic, incidents and rivals' stops.</>}>
        <div className="overflow-auto"><table className="grid-t">
          <thead><tr><th></th><th>Strategy</th><th>Stops (lap → tyre)</th><th style={{ minWidth: 260 }}>Stints</th><th className="r">Next stop</th><th className="r">Pit time lost</th><th className="r">Tyre wear cost</th><th className="r">Model Δ</th><th className="r">Sim Δ</th><th className="r">Exp. finish</th><th className="r">P10–P90</th><th className="r">Win</th><th className="r">Podium</th><th className="r">Laps in traffic</th></tr></thead>
          <tbody>{s.strategies.map((x: any) => (
            <tr key={x.label} className={x.recommended ? "!bg-[#141a14]" : ""} style={{ opacity: x.rule_ok ? 1 : 0.5 }}>
              <td className="num font-bold">{x.label}</td>
              <td className="font-semibold">{x.name}{x.recommended && <span className="ml-2 rounded bg-good px-1.5 py-[1px] text-[9px] font-bold text-black">RECOMMENDED</span>}{!x.rule_ok && <span className="ml-2 text-[10px] text-bad">breaks 2-compound rule</span>}</td>
              <td>{x.plan.length ? x.plan.map((p: any, i: number) => <span key={i} className="mr-2 inline-flex items-center gap-1"><span className="num">L{p.lap}</span><Tyre compound={p.compound} /></span>) : <span className="text-faint">none</span>}</td>
              <td><Stints total={s.total_laps} lap={s.lap} stints={[...mine.map((m: any) => ({ ...m })), ...x.stints.filter((t: any) => t.from_lap > s.lap || t.to_lap > s.lap).map((t: any) => ({ compound: t.compound, from: Math.max(t.from_lap, s.lap + 1), to: t.to_lap, future: true }))]} /></td>
              <td className="r num">{x.recommended_pit_lap ? `L${x.recommended_pit_lap}` : "—"}</td><td className="r num">{num(x.pit_time_lost)} s</td><td className="r num">{num(x.deg_time)} s</td>
              <td className="r num text-dim">{x.deterministic_delta === null || x.deterministic_delta === undefined ? "—" : signed(x.deterministic_delta)}</td><td className="r num">{x.exp_time_delta === null || x.exp_time_delta === undefined ? "—" : signed(x.exp_time_delta)}</td>
              <td className="r num font-semibold">{x.exp_pos ? `P${num(x.exp_pos)}` : "—"}</td><td className="r num text-dim">{x.pos_p10 ? `P${x.pos_p10}–P${x.pos_p90}` : "—"}</td><td className="r num">{pct(x.p_win)}</td><td className="r num">{pct(x.p_podium)}</td><td className="r num">{num(x.traffic_laps)}</td>
            </tr>))}</tbody>
        </table></div>
      </Panel>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Pit-window sensitivity" tags={["MODEL"]} note="Time lost versus the best first-stop lap, later stops held fixed. The shaded band is the window (within 1 s of optimal).">
          <State empty={!s.window ? "No pit window at this lap (no further stop planned, or the car is on wet-weather tyres)." : null}>
            {s.window && <ResponsiveContainer width="100%" height={230}>
              <LineChart data={s.window.curve} margin={{ top: 6, right: 10, bottom: 0, left: -16 }}>
                <CartesianGrid stroke={GRID} vertical={false} /><XAxis dataKey="lap" type="number" domain={["dataMin", "dataMax"]} tickLine={false} axisLine={{ stroke: GRID }} tickFormatter={(v) => `L${v}`} />
                <YAxis tickLine={false} axisLine={false} width={52} tickFormatter={(v) => `+${v}s`} domain={[0, (m: number) => Math.min(m, 15)]} allowDataOverflow />
                <ReferenceArea x1={s.window.open} x2={s.window.close} fill="#2fbf71" fillOpacity={0.12} /><ReferenceLine x={s.window.optimal} stroke="#2fbf71" strokeDasharray="3 3" />
                <Tooltip content={<ChartTip title={(l: number) => `Stop on lap ${l}`} fmt={(v: number) => `+${v.toFixed(2)} s`} />} />
                <Line dataKey="delta" name="Time lost vs optimum" stroke="#f2f3f5" strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart></ResponsiveContainer>}
          </State>
        </Panel>
        <Panel title="Tyre degradation — observed laps" tags={["OBSERVED"]} note="Median green-flag lap time of the field at each tyre age (in/out laps and neutralised laps excluded). Raw medians still contain fuel and track evolution; the fitted wear rates in the table below remove both.">
          <ResponsiveContainer width="100%" height={230}>
            <ScatterChart margin={{ top: 6, right: 10, bottom: 0, left: -6 }}>
              <CartesianGrid stroke={GRID} vertical={false} /><XAxis dataKey="age" type="number" name="Tyre age" tickLine={false} axisLine={{ stroke: GRID }} tickFormatter={(v) => `${v}`} />
              <YAxis dataKey="lap_time" type="number" name="Lap time" domain={["dataMin - 0.3", "dataMax + 0.3"]} tickFormatter={(v) => fmtLap(v)} tickLine={false} axisLine={false} width={64} /><ZAxis range={[28, 28]} />
              <Tooltip content={<ChartTip title={() => "Tyre age / median lap"} fmt={(v: number, n: string) => (n === "Lap time" ? fmtLap(v) : `${v} laps`)} />} /><Legend />
              {Object.entries(degBy).map(([c, pts]) => <Scatter key={c} name={c} data={pts} fill={COMPOUND[c]?.c} isAnimationActive={false} />)}
            </ScatterChart></ResponsiveContainer>
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel title="Fitted tyre model" tags={["MODEL"]} pad={false} note={tm.base_source}>
          <table className="grid-t"><thead><tr><th>Compound</th><th className="r">Wear</th><th className="r">Pace offset</th><th className="r">Laps</th><th>Basis</th></tr></thead>
            <tbody>{["SOFT", "MEDIUM", "HARD"].map((c) => { const x = tm.compounds[c]; return <tr key={c}><td><Tyre compound={c} /> <span className="ml-1">{c}</span></td><td className="r num">{signed(x.deg, 3)} s/lap</td><td className="r num">{signed(x.offset, 2)} s</td><td className="r num">{x.n_laps}</td><td className="whitespace-normal text-[11px] text-dim">{x.source}</td></tr>; })}</tbody></table>
        </Panel>
        <Panel title="Undercut / overcut screen" tags={["OBSERVED", "MODEL"]} pad={false} note="Pairs of cars within 4 s on slick tyres. Margin = modelled two-lap fresh-tyre gain minus the gap.">
          <State empty={!s.undercuts.length ? "No pairs within undercut range on slick tyres at this lap." : null}>
            <div className="max-h-[260px] overflow-auto"><table className="grid-t"><thead><tr><th>Attacker</th><th>Ahead</th><th className="r">Gap</th><th className="r">Gain/lap</th><th className="r">Margin</th><th>Undercut</th></tr></thead>
              <tbody>{s.undercuts.map((u: any, i: number) => <tr key={i}><td className="font-semibold">{u.driver}</td><td>{u.ahead}</td><td className="r num">{u.gap_s} s</td><td className="r num">{signed(u.fresh_tyre_gain_per_lap, 2)}</td><td className="r num">{signed(u.undercut_margin, 2)}</td>
                <td>{u.undercut_on ? <span className="font-semibold text-good">ON</span> : <span className="text-faint">no</span>}</td></tr>)}</tbody></table></div>
          </State>
        </Panel>
        <Panel title="Competitor pit windows" tags={["MODEL"]} pad={false} note="Each rival's own time-optimal next stop from the same optimiser.">
          <div className="max-h-[260px] overflow-auto"><table className="grid-t"><thead><tr><th>Pos</th><th>Driver</th><th>Tyre · age</th><th className="r">Next stop</th><th>Onto</th></tr></thead>
            <tbody>{s.competitors.map((c: any) => <tr key={c.driver_number} className={c.driver_number === s.focus ? "!bg-[#16191e]" : ""}><td className="num">{c.position}</td><td className="font-semibold">{c.code}</td><td><Tyre compound={c.compound} age={c.tyre_age} /></td><td className="r num">{c.next_stop ? `L${c.next_stop}` : "—"}</td><td><Tyre compound={c.next_compound} /></td></tr>)}</tbody></table></div>
        </Panel>
      </div>

      <Panel title="Stint history — all cars" tags={["OBSERVED"]}>
        <div className="space-y-1">{s.drivers.map((d: any) => (
          <div key={d.driver_number} className="grid grid-cols-[28px_44px_minmax(0,1fr)] items-center gap-2 text-xs"><span className="num text-faint">{d.position}</span><Driver code={d.code} colour={d.team_colour} />
            <Stints total={s.total_laps} lap={s.lap} stints={s.stints.filter((x: any) => x.driver_number === d.driver_number)} /></div>))}</div>
      </Panel>
      <Notes title="Assumptions" items={[...s.assumptions, s.pit_loss.neutralised_note]} />
    </div>
  );
}
