"use client";
import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useApi, useRace } from "@/lib/api";
import { COMPOUND, ChartTip, Driver, GRID, Notes, Panel, SERIES, State, Stat, Tag, Tyre, fmtLap, num, teamColour } from "@/components/ui";

const SECTOR = ["#3987e5", "#c98500", "#199e70"];

function TrackMap({ data, focus }: { data: any; focus: number | null }) {
  const pts: number[][] = data.outline;
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const W = 520, H = 360, pad = 26;
  const s = Math.min((W - 2 * pad) / (maxX - minX || 1), (H - 2 * pad) / (maxY - minY || 1));
  const X = (x: number) => pad + (x - minX) * s + (W - 2 * pad - (maxX - minX) * s) / 2;
  const Y = (y: number) => H - pad - (y - minY) * s - (H - 2 * pad - (maxY - minY) * s) / 2;
  const seg = [1, 2, 3].map((k) => pts.filter((p, i) => p[2] === k || (pts[i - 1] && pts[i - 1][2] === k)).map((p) => `${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(" "));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Circuit map with car positions">
      {seg.map((d, i) => <polyline key={i} points={d} fill="none" stroke={SECTOR[i]} strokeWidth={5} strokeLinecap="round" strokeLinejoin="round" opacity={0.55} />)}
      <circle cx={X(pts[0][0])} cy={Y(pts[0][1])} r={4} fill="#f2f3f5" /><text x={X(pts[0][0]) + 7} y={Y(pts[0][1]) - 6} fontSize={9} fill="#a3a8b3">S/F</text>
      {data.cars.map((c: any) => (
        <g key={c.driver_number}>
          <circle cx={X(c.x)} cy={Y(c.y)} r={c.driver_number === focus ? 7 : 5} fill={teamColour(c.team_colour)} stroke="#0a0b0d" strokeWidth={2} />
          <text x={X(c.x) + 8} y={Y(c.y) + 3} fontSize={c.driver_number === focus ? 11 : 9} fontWeight={c.driver_number === focus ? 700 : 500} fill="#f2f3f5">{c.code}</text>
        </g>
      ))}
    </svg>
  );
}

function Trace({ pts, ch, title, traces, unit, domain, h = 130 }: any) {
  return (
    <div>
      <div className="mb-1 flex items-center gap-2 text-[10px] uppercase tracking-[.12em] text-faint">{title}{unit && <span className="normal-case tracking-normal">({unit})</span>}</div>
      <ResponsiveContainer width="100%" height={h}>
        <LineChart data={pts} syncId="tel" margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="d" type="number" domain={[0, "dataMax"]} tickFormatter={(v) => `${Math.round(v)}m`} tickLine={false} axisLine={{ stroke: GRID }} />
          <YAxis domain={domain || ["auto", "auto"]} tickLine={false} axisLine={false} width={52} allowDecimals={false} />
          <Tooltip content={<ChartTip title={(l: number) => `${Math.round(l)} m`} />} />
          {traces.map((t: any, i: number) => <Line key={t.key} type={ch === "gear" || ch === "drs" ? "stepAfter" : "monotone"} dataKey={`${ch}_${t.key}`} name={`${t.code} L${t.lap}`} stroke={SERIES[i]} strokeWidth={1.6} dot={false} isAnimationActive={false} />)}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function Telemetry() {
  const r = useRace();
  const { data: laps, error: lapErr } = useApi<any>(r.sessionKey ? `/api/telemetry/laps?${r.q}` : null, r.tick);
  const { data: map, loading: mapLoading, error: mapErr } = useApi<any>(r.sessionKey ? `/api/telemetry/track?${r.q}` : null, r.tick);
  const { data: pace } = useApi<any>(r.sessionKey ? `/api/telemetry/pace?${r.q}` : null, r.tick);
  const [sel, setSel] = useState<{ d1?: number; l1?: number; d2?: number; l2?: number }>({});
  const drivers: any[] = laps?.drivers || [];
  const byNum = useMemo(() => Object.fromEntries(drivers.map((d) => [d.driver_number, d])), [drivers]);
  const fastest = (d?: any) => d?.laps.filter((x: any) => x.t && !x.pit).reduce((a: any, b: any) => (!a || b.t < a.t ? b : a), null)?.lap;
  const latest = (d?: any) => d?.laps.filter((x: any) => x.t && !x.pit).slice(-1)[0]?.lap;
  const me = r.driver ? byNum[r.driver] : drivers[0];
  useEffect(() => {   // default: focus driver's fastest lap vs their latest lap
    if (me && (sel.d1 === undefined || !byNum[sel.d1])) setSel({ d1: me.driver_number, l1: fastest(me), d2: me.driver_number, l2: latest(me) });
  }, [me, byNum]); // eslint-disable-line
  const preset = (kind: string) => {
    if (!me) return;
    if (kind === "fast-current") setSel({ d1: me.driver_number, l1: fastest(me), d2: me.driver_number, l2: latest(me) });
    if (kind === "teammate") { const m = drivers.find((d) => d.team === me.team && d.driver_number !== me.driver_number); if (m) setSel({ d1: me.driver_number, l1: fastest(me), d2: m.driver_number, l2: fastest(m) }); }
    if (kind === "leader") { const l = drivers[0]; setSel({ d1: me.driver_number, l1: fastest(me), d2: l.driver_number, l2: fastest(l) }); }
    if (kind === "stints") { const st = Array.from(new Set(me.laps.map((x: any) => x.stint))).filter(Boolean) as number[]; if (st.length > 1) {
      const f = (s: number) => me.laps.filter((x: any) => x.stint === s && x.t && !x.pit).reduce((a: any, b: any) => (!a || b.t < a.t ? b : a), null)?.lap;
      setSel({ d1: me.driver_number, l1: f(st[0]), d2: me.driver_number, l2: f(st[st.length - 1]) }); } }
  };
  const ready = sel.d1 && sel.l1;
  const cq = ready ? `/api/telemetry/compare?session_key=${r.sessionKey}&d1=${sel.d1}&l1=${sel.l1}${sel.d2 && sel.l2 ? `&d2=${sel.d2}&l2=${sel.l2}` : ""}` : null;
  const { data: tel, loading: telLoading, error: telErr } = useApi<any>(cq);
  const other = sel.d2 ? byNum[sel.d2] : null;
  const lapSeries = useMemo(() => {
    const a = sel.d1 ? byNum[sel.d1] : null, b = sel.d2 && sel.d2 !== sel.d1 ? byNum[sel.d2] : null;
    if (!a) return [];
    const m: Record<number, any> = {};
    for (const [k, d] of [["a", a], ["b", b]] as any) for (const x of d?.laps || []) { m[x.lap] = m[x.lap] || { lap: x.lap }; if (x.t && !x.pit && x.status === "GREEN") m[x.lap][k] = x.t; m[x.lap][`p${k}`] = x.pos; }
    return Object.values(m).sort((x: any, y: any) => x.lap - y.lap);
  }, [sel, byNum]);
  const A = sel.d1 ? byNum[sel.d1] : null;
  const B = sel.d2 && sel.d2 !== sel.d1 ? byNum[sel.d2] : null;
  const lapOpts = (d?: any) => (d?.laps || []).filter((x: any) => x.t).map((x: any) => <option key={x.lap} value={x.lap}>L{x.lap} · {fmtLap(x.t)} · {x.compound?.[0] || "?"}{x.pit ? " · pit" : ""}</option>);
  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <Panel title="Circuit map & car positions" tags={["OBSERVED"]} note={map?.available ? <>Outline drawn from car #{map.outline_ref}. Sectors: <span style={{ color: SECTOR[0] }}>S1</span> · <span style={{ color: SECTOR[1] }}>S2</span> · <span style={{ color: SECTOR[2] }}>S3</span>. Positions at the end of lap {map.lap}. {map.limitations?.[0]}</> : undefined}>
          <State loading={mapLoading} error={mapErr} empty={map && !map.available ? map.reason : null}>{map?.available && <TrackMap data={map} focus={r.driver} />}</State>
          {map?.note && <div className="mt-2 text-[11px] text-warn">{map.note}</div>}
        </Panel>
        <Panel title="Sector times — last completed lap" tags={["OBSERVED"]} pad={false}>
          <State error={lapErr} empty={laps && !laps.available ? laps.reason : null}>
            <div className="max-h-[420px] overflow-auto">
              <table className="grid-t"><thead><tr><th>Pos</th><th>Driver</th><th className="r">S1</th><th className="r">S2</th><th className="r">S3</th><th className="r">Lap</th><th className="r">Speed trap</th><th>Tyre</th></tr></thead>
                <tbody>{drivers.map((d) => { const x = d.laps[d.laps.length - 1]; if (!x) return null; const b = laps.best; const cl = (v: number, best: number) => (v && Math.abs(v - best) < 1e-6 ? { color: "#c084fc" } : undefined);
                  return <tr key={d.driver_number}><td className="num">{d.position}</td><td><Driver code={d.code} colour={d.team_colour} /></td>
                    <td className="r num" style={cl(x.s1, b.duration_sector_1)}>{num(x.s1, 3)}</td><td className="r num" style={cl(x.s2, b.duration_sector_2)}>{num(x.s2, 3)}</td><td className="r num" style={cl(x.s3, b.duration_sector_3)}>{num(x.s3, 3)}</td>
                    <td className="r num">{fmtLap(x.t)}</td><td className="r num text-dim">{x.st ? `${x.st} km/h` : "—"}</td><td><Tyre compound={x.compound} /></td></tr>; })}</tbody></table>
            </div>
          </State>
        </Panel>
      </div>

      <Panel title="Telemetry comparison" tags={["OBSERVED"]}
        right={<>
          <span className="text-faint">Presets:</span>
          <button className="btn" onClick={() => preset("fast-current")}>Fastest vs latest lap</button>
          <button className="btn" onClick={() => preset("teammate")}>vs teammate</button>
          <button className="btn" onClick={() => preset("leader")}>vs leader</button>
          <button className="btn" onClick={() => preset("stints")}>First vs last stint</button>
        </>}>
        <div className="mb-3 flex flex-wrap items-center gap-3 text-xs">
          {(["1", "2"] as const).map((k, i) => (
            <div key={k} className="flex items-center gap-2">
              <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: SERIES[i] }} />
              <select value={(sel as any)[`d${k}`] ?? ""} onChange={(e) => { const d = byNum[Number(e.target.value)]; setSel({ ...sel, [`d${k}`]: d.driver_number, [`l${k}`]: fastest(d) }); }} aria-label={`Driver ${k}`}>
                {drivers.map((d) => <option key={d.driver_number} value={d.driver_number}>{d.code}</option>)}</select>
              <select value={(sel as any)[`l${k}`] ?? ""} onChange={(e) => setSel({ ...sel, [`l${k}`]: Number(e.target.value) })} aria-label={`Lap ${k}`}>{lapOpts(byNum[(sel as any)[`d${k}`]])}</select>
            </div>
          ))}
        </div>
        <State loading={telLoading} error={telErr} empty={tel && !tel.available ? tel.reason : null}>
          {tel?.available && (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                {tel.traces.map((t: any, i: number) => (
                  <div key={t.key} className="col-span-2 rounded-md border border-line bg-panel2 px-3 py-2">
                    <div className="flex items-center gap-2 text-xs"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: SERIES[i] }} /><b>{t.code}</b><span className="text-dim">lap {t.lap}</span><span className="num ml-auto text-sm font-semibold">{fmtLap(t.lap_time)}</span></div>
                    <div className="num mt-1 grid grid-cols-3 gap-x-3 text-[11px] text-dim xl:grid-cols-6">
                      <span>Top {t.top_speed} km/h</span><span>Full thr. {t.full_throttle_pct}%</span><span>Braking {t.brake_pct}%</span><span>{t.gear_changes} shifts</span><span>Max {t.max_rpm} rpm</span><span>DRS {t.drs_pct}%</span>
                    </div>
                  </div>
                ))}
              </div>
              <Trace pts={tel.points} ch="speed" title="Speed" unit="km/h" traces={tel.traces} h={190} />
              {tel.traces.length === 2 && (
                <div>
                  <div className="mb-1 text-[10px] uppercase tracking-[.12em] text-faint">Time delta ({tel.traces[1].code} L{tel.traces[1].lap} − {tel.traces[0].code} L{tel.traces[0].lap}, s) — above zero = second trace slower</div>
                  <ResponsiveContainer width="100%" height={110}>
                    <LineChart data={tel.points} syncId="tel" margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
                      <CartesianGrid stroke={GRID} vertical={false} /><XAxis dataKey="d" type="number" domain={[0, "dataMax"]} tickFormatter={(v) => `${Math.round(v)}m`} tickLine={false} axisLine={{ stroke: GRID }} />
                      <YAxis tickLine={false} axisLine={false} width={52} /><ReferenceLine y={0} stroke="#6b717d" />
                      <Tooltip content={<ChartTip title={(l: number) => `${Math.round(l)} m`} fmt={(v: number) => `${v > 0 ? "+" : ""}${v.toFixed(3)} s`} />} />
                      <Line dataKey="delta" name="Delta" stroke="#f2f3f5" strokeWidth={1.6} dot={false} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
              <div className="grid gap-3 lg:grid-cols-2">
                <Trace pts={tel.points} ch="throttle" title="Throttle" unit="%" traces={tel.traces} domain={[0, 100]} />
                <Trace pts={tel.points} ch="brake" title="Brake" unit="% / on-off" traces={tel.traces} domain={[0, 100]} />
                <Trace pts={tel.points} ch="gear" title="Gear" traces={tel.traces} domain={[0, 8]} />
                <Trace pts={tel.points} ch="rpm" title="Engine speed" unit="rpm" traces={tel.traces} />
                <Trace pts={tel.points} ch="drs" title="DRS / overtake aid open" unit="1 = open" traces={tel.traces} domain={[0, 1]} h={80} />
              </div>
              <Notes items={tel.limitations} />
            </div>
          )}
        </State>
      </Panel>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Lap progression (green-flag laps)" tags={["OBSERVED"]}>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={lapSeries} margin={{ top: 4, right: 8, bottom: 0, left: -10 }}>
              <CartesianGrid stroke={GRID} vertical={false} /><XAxis dataKey="lap" tickLine={false} axisLine={{ stroke: GRID }} />
              <YAxis domain={["dataMin - 0.5", "dataMax + 0.5"]} tickFormatter={(v) => fmtLap(v)} tickLine={false} axisLine={false} width={64} />
              <Tooltip content={<ChartTip title={(l: number) => `Lap ${l}`} fmt={(v: number) => fmtLap(v)} />} /><Legend iconType="plainline" />
              {A && <Line dataKey="a" name={A.code} stroke={SERIES[0]} strokeWidth={1.8} dot={{ r: 1.5 }} connectNulls={false} isAnimationActive={false} />}
              {B && <Line dataKey="b" name={B.code} stroke={SERIES[1]} strokeWidth={1.8} dot={{ r: 1.5 }} connectNulls={false} isAnimationActive={false} />}
            </LineChart>
          </ResponsiveContainer>
        </Panel>
        <Panel title="Position changes" tags={["OBSERVED"]} note="Position at each timing-line crossing. Lower is better.">
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={lapSeries} margin={{ top: 4, right: 8, bottom: 0, left: -24 }}>
              <CartesianGrid stroke={GRID} vertical={false} /><XAxis dataKey="lap" tickLine={false} axisLine={{ stroke: GRID }} />
              <YAxis reversed domain={[1, 22]} ticks={[1, 5, 10, 15, 20]} tickFormatter={(v) => `P${v}`} allowDecimals={false} tickLine={false} axisLine={false} width={52} />
              <Tooltip content={<ChartTip title={(l: number) => `Lap ${l}`} fmt={(v: number) => `P${v}`} />} /><Legend iconType="plainline" />
              {A && <Line type="stepAfter" dataKey="pa" name={A.code} stroke={SERIES[0]} strokeWidth={1.8} dot={false} isAnimationActive={false} />}
              {B && <Line type="stepAfter" dataKey="pb" name={B.code} stroke={SERIES[1]} strokeWidth={1.8} dot={false} isAnimationActive={false} />}
            </LineChart>
          </ResponsiveContainer>
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel title="Race pace by compound" tags={["OBSERVED"]} pad={false} className="xl:col-span-1">
          <div className="max-h-[340px] overflow-auto"><table className="grid-t"><thead><tr><th>Driver</th><th>Tyre</th><th className="r">Laps</th><th className="r">Median</th><th className="r">Best</th></tr></thead>
            <tbody>{(pace?.by_compound || []).map((x: any, i: number) => <tr key={i}><td><Driver code={x.code} colour={x.team_colour} /></td><td><Tyre compound={x.compound} /></td><td className="r num">{x.laps}</td><td className="r num">{fmtLap(x.median)}</td><td className="r num text-dim">{fmtLap(x.best)}</td></tr>)}</tbody></table></div>
        </Panel>
        <Panel title="Qualifying vs race pace" tags={["OBSERVED"]} pad={false} note={pace?.note || "Race median of dry green-flag laps divided by the best qualifying lap."}>
          <div className="max-h-[300px] overflow-auto"><table className="grid-t"><thead><tr><th>Driver</th><th className="r">Quali best</th><th className="r">Race median</th><th className="r">Ratio</th></tr></thead>
            <tbody>{(pace?.quali_vs_race || []).map((x: any) => <tr key={x.driver_number}><td><Driver code={x.code} colour={x.team_colour} /></td><td className="r num">{fmtLap(x.quali_best)}</td><td className="r num">{fmtLap(x.race_median)}</td><td className="r num">{x.ratio.toFixed(3)}</td></tr>)}</tbody></table></div>
        </Panel>
        <Panel title="Teammate comparison" tags={["OBSERVED"]} pad={false} note="Race-pace delta = first driver's median dry green-flag lap minus the second's (negative = first is faster).">
          <table className="grid-t"><thead><tr><th>Team</th><th>Pair</th><th className="r">Race pace Δ</th><th className="r">Quali Δ</th></tr></thead>
            <tbody>{(pace?.teammates || []).map((x: any) => <tr key={x.team}><td><span className="mr-2 inline-block h-3 w-1 rounded-sm align-middle" style={{ background: teamColour(x.team_colour) }} />{x.team}</td><td>{x.a} / {x.b}</td>
              <td className="r num">{x.race_pace_delta > 0 ? "+" : ""}{x.race_pace_delta.toFixed(3)}</td><td className="r num text-dim">{x.quali_delta === null ? "—" : `${x.quali_delta > 0 ? "+" : ""}${x.quali_delta.toFixed(3)}`}</td></tr>)}</tbody></table>
        </Panel>
      </div>
      <Notes title="Not available from the sources" items={["Driver performance across different circuits is shown under Driver & Constructor Analytics and Historical Race Intelligence (results-level).",
        "Live GPS positions during a session require OpenF1 real-time access; without it the map shows the most recent stored positions and the header reads DELAYED or HISTORICAL."]} />
    </div>
  );
}
