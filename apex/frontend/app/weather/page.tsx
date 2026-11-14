"use client";
import { useEffect, useState } from "react";
import { Area, AreaChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, useApi, useRace } from "@/lib/api";
import { ChartTip, Confidence, GRID, Notes, Panel, SERIES, Stat, State, Tag, num, pct, dt } from "@/components/ui";
import { OptionTable, PositionDist } from "@/components/Options";

const hm = (t: number) => new Date(t * 1000).toISOString().slice(11, 16);
const PRESETS: { key: string; label: string; what_if: any; group: string }[] = [
  { key: "a1", group: "A · Dry → Wet", label: "Rain in 10 min (moderate, 20 min)", what_if: { rain_in_min: 10, rain_intensity: 0.5, rain_duration_min: 20 } },
  { key: "a2", group: "A · Dry → Wet", label: "Light shower in 5 min", what_if: { rain_in_min: 5, rain_intensity: 0.25, rain_duration_min: 12 } },
  { key: "b1", group: "B · Wet → Dry", label: "Rain stops now, track damp", what_if: { rain_stops: true, wetness: 0.45 } },
  { key: "c1", group: "C · Disruption", label: "Sudden heavy rain now", what_if: { rain_in_min: 0, rain_intensity: 1, rain_duration_min: 15 } },
  { key: "c2", group: "C · Disruption", label: "Track temperature +10°C", what_if: { track_temp_delta: 10 } },
  { key: "c3", group: "C · Disruption", label: "Strong / shifting crosswind", what_if: { crosswind: true } },
];

export default function Weather() {
  const r = useRace();
  const base = useApi<any>(r.sessionKey && r.driver ? `/api/weather?${r.q}&driver=${r.driver}` : null, r.tick);
  const next = useApi<any>("/api/weather/next");
  const [wi, setWi] = useState<any | null>(null);
  const [custom, setCustom] = useState({ rain_in_min: 10, rain_intensity: 0.5, rain_duration_min: 20 });
  const [scn, setScn] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {   // any change of lap / driver / new data / rain-sensor alert re-runs the active scenario
    if (!wi || !r.sessionKey) { setScn(null); return; }
    let live = true;
    setBusy(true); setErr(null);
    api("/api/weather/scenario", { session_key: r.sessionKey, lap: r.lap, driver: r.driver, what_if: wi })
      .then((d) => live && setScn(d)).catch((e) => live && setErr(String(e.message))).finally(() => live && setBusy(false));
    return () => { live = false; };
  }, [wi, r.sessionKey, r.lap, r.driver, r.tick]);
  const d = scn || base.data;
  if (!d) return <State loading={base.loading} error={base.error} />;
  const w = d.current.observed, px = d.current.wetness_proxy, fc = d.forecast, rec = d.recommendation;
  const best = rec?.recommended;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <Stat label="Track temp" tag="OBSERVED" value={w ? `${num(w.track_temperature)}°C` : "—"} sub={w?.track_temp_trend_15min !== null && w ? `${w.track_temp_trend_15min > 0 ? "+" : ""}${w.track_temp_trend_15min}° in 15 min` : ""} />
        <Stat label="Air temp" tag="OBSERVED" value={w ? `${num(w.air_temperature)}°C` : "—"} sub={w ? `humidity ${num(w.humidity, 0)}%` : ""} />
        <Stat label="Rain sensor" tag="OBSERVED" value={w ? (w.rainfall ? "RAIN" : "DRY") : "—"} accent={w?.rainfall ? "#3d8bf2" : undefined} sub={w ? `${Math.round((w.rain_share_15min ?? 0) * 100)}% of last 15 min` : ""} />
        <Stat label="Wind" tag="OBSERVED" value={w ? `${num(w.wind_speed)} m/s` : "—"} sub={w ? `direction ${num(w.wind_direction, 0)}°` : ""} />
        <Stat label="Track wetness" tag="MODEL" value={num(px.wetness, 2)} sub={`${Math.round(px.share_on_inters * 100)}% of field on inters`} />
        <Stat label="Precip. probability" tag="FORECAST" value={fc.summary?.max_prob !== null && fc.summary?.max_prob !== undefined ? `${fc.summary.max_prob}%` : "—"} sub="max over remaining window" />
        <Stat label="Forecast rain" tag="FORECAST" value={fc.summary?.total_mm !== null && fc.summary?.total_mm !== undefined ? `${fc.summary.total_mm} mm` : "—"} sub={fc.summary?.first_rain_min !== null && fc.summary?.first_rain_min !== undefined ? `first rain in ~${fc.summary.first_rain_min} min` : "none in window"} />
        <Stat label="Tyre crossover" tag="ASSUMPTION" value={`${d.crossover.slick_to_inter} / ${d.crossover.inter_to_wet}`} sub="wetness: slick→inter / inter→wet" />
      </div>
      {d.forecast_observation_mismatch && <div className="rounded border border-warn/40 bg-[#211a08] px-3 py-2 text-xs text-warn"><b>Forecast ≠ track.</b> {d.forecast_observation_mismatch}</div>}
      {fc.caveat && <div className="rounded border border-line bg-panel2 px-3 py-2 text-[11px] text-dim"><Tag kind="FORECAST" /> <span className="ml-1">{fc.caveat}</span> {fc.available === false && <b className="text-warn">{fc.reason}</b>}</div>}

      <Panel title="Scenario engine" tags={["ASSUMPTION"]}
        right={<>{wi ? <button className="btn" onClick={() => setWi(null)}>Back to forecast-driven view</button> : <span>Showing the forecast-driven evaluation</span>}{busy && <span className="animate-pulse text-faint">recalculating…</span>}</>}
        note="Pick a what-if or define your own. The scenario is recalculated automatically whenever the lap, focus driver, stored data or the track rain sensor changes.">
        <div className="grid gap-3 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <div className="grid gap-2 sm:grid-cols-3">
            {["A · Dry → Wet", "B · Wet → Dry", "C · Disruption"].map((g) => (
              <div key={g}><div className="mb-1 text-[10px] font-semibold uppercase tracking-[.12em] text-faint">{g}</div>
                <div className="flex flex-col gap-1.5">{PRESETS.filter((p) => p.group === g).map((p) => <button key={p.key} className={`btn text-left ${wi === p.what_if ? "!border-f1" : ""}`} onClick={() => setWi(p.what_if)}>{p.label}</button>)}</div></div>))}
          </div>
          <div className="rounded border border-line bg-panel2 p-2.5 text-xs">
            <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-[.12em] text-faint">Custom rain</div>
            <div className="grid grid-cols-3 gap-2">
              <label className="flex flex-col gap-1 text-faint">Starts in (min)<input type="number" min={0} max={90} value={custom.rain_in_min} onChange={(e) => setCustom({ ...custom, rain_in_min: Number(e.target.value) })} /></label>
              <label className="flex flex-col gap-1 text-faint">Intensity 0–1<input type="number" min={0} max={1} step={0.05} value={custom.rain_intensity} onChange={(e) => setCustom({ ...custom, rain_intensity: Number(e.target.value) })} /></label>
              <label className="flex flex-col gap-1 text-faint">Duration (min)<input type="number" min={1} max={120} value={custom.rain_duration_min} onChange={(e) => setCustom({ ...custom, rain_duration_min: Number(e.target.value) })} /></label>
            </div>
            <button className="btn primary mt-2 w-full" onClick={() => setWi({ ...custom })}>Run scenario</button>
          </div>
        </div>
        {err && <div className="mt-2"><State error={err} /></div>}
      </Panel>

      <Panel title={`Adaptive recommendation — ${d.focus_code ?? "—"}, lap ${d.lap}/${d.total_laps}${d.scenario_type ? ` · Scenario ${d.scenario_type[0]}` : ""}`} tags={d.what_if ? ["ASSUMPTION", "MODEL"] : ["FORECAST", "MODEL"]}>
        {rec ? (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <div className="space-y-3">
              <p className="text-[13px] leading-relaxed">{rec.text}</p>
              <div className="grid gap-2 sm:grid-cols-2">
                <div className="rounded border border-good/40 bg-[#101a13] px-3 py-2"><div className="text-[10px] uppercase tracking-[.12em] text-good">Recommended action</div><div className="mt-0.5 text-sm font-semibold">{rec.recommended}</div></div>
                <div className="rounded border border-line bg-panel2 px-3 py-2"><div className="text-[10px] uppercase tracking-[.12em] text-faint">Alternative</div><div className="mt-0.5 text-sm">{rec.alternative}</div></div>
              </div>
              <div className="num flex flex-wrap gap-x-6 gap-y-1 text-xs text-dim">
                {rec.expected_gain_s !== undefined && <span>Expected gain vs alternative: <b className="text-ink">{rec.expected_gain_s > 0 ? "+" : ""}{rec.expected_gain_s} s</b> · <b className="text-ink">{rec.expected_gain_positions > 0 ? "+" : ""}{rec.expected_gain_positions}</b> positions</span>}
                {rec.crossover_lap && <span>Modelled crossover: <b className="text-ink">lap {rec.crossover_lap}</b></span>}
                {rec.time_lost_per_lap_on_slicks_at_peak_s ? <span>Slicks at peak wetness: <b className="text-ink">+{rec.time_lost_per_lap_on_slicks_at_peak_s} s/lap</b></span> : null}
                <span>Confidence: <Confidence c={rec.confidence} /></span>
              </div>
              {rec.confidence?.basis && <div className="text-[11px] text-faint">Confidence basis: {rec.confidence.basis}.</div>}
            </div>
            <div className="space-y-2 text-xs">
              <div className="text-[10px] font-semibold uppercase tracking-[.12em] text-faint">Main risks</div>
              <ul className="space-y-1 text-dim">{rec.risks.map((x: string, i: number) => <li key={i}>• {x}</li>)}</ul>
              {rec.aquaplaning_risk_index !== undefined && <div className="text-dim">Aquaplaning risk index <Tag kind="MODEL" />: <b className="num text-ink">{rec.aquaplaning_risk_index}</b> <span className="text-faint">— {rec.aquaplaning_note}</span></div>}
              {rec.competitor_reaction && <div className="text-dim">Rival reaction: <span className="text-faint">{rec.competitor_reaction}</span></div>}
            </div>
          </div>
        ) : <State empty={d.lap >= d.total_laps - 2 ? "The race is over at this lap — no weather decision to make. Move the lap control back to replay one." : "No tyre-class change is indicated: the modelled wetness stays on the current tyre's side of the crossover for the remaining laps. Use the scenario engine to test a what-if."} />}
      </Panel>

      {d.options?.length > 0 && (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
          <Panel title="Decision comparison" tags={["MODEL"]} pad={false} note={`${d.options[0].n_sims} simulated races per option with identical random futures; rivals switch tyres one lap after the crossover. ± is 1.96 simulation standard errors.`}>
            <OptionTable options={d.options} best={best} />
          </Panel>
          <Panel title="Finishing-position distribution" tags={["MODEL"]} note="First four options shown."><PositionDist options={d.options} /></Panel>
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel title="Track weather this session" tags={["OBSERVED"]} note="OpenF1 track-side station, about one reading per minute. Rain is an on/off sensor.">
          <ResponsiveContainer width="100%" height={210}>
            <LineChart data={d.series} margin={{ top: 6, right: 8, bottom: 0, left: -22 }}>
              <CartesianGrid stroke={GRID} vertical={false} /><XAxis dataKey="t" tickFormatter={hm} tickLine={false} axisLine={{ stroke: GRID }} minTickGap={40} /><YAxis tickLine={false} axisLine={false} width={52} unit="°" domain={["auto", "auto"]} />
              <Tooltip content={<ChartTip title={(l: number) => `${hm(l)} UTC`} fmt={(v: number) => `${v}°C`} />} /><Legend iconType="plainline" />
              <Line dataKey="track" name="Track" stroke={SERIES[1]} strokeWidth={2} dot={false} isAnimationActive={false} /><Line dataKey="air" name="Air" stroke={SERIES[0]} strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart></ResponsiveContainer>
          <div className="mt-2 flex h-3 w-full overflow-hidden rounded-sm bg-[#1c1f25]" title="Rain sensor timeline">{d.series.map((x: any, i: number) => <div key={i} className="h-3 flex-1" style={{ background: x.rain ? "#3d8bf2" : "transparent" }} />)}</div>
          <div className="mt-1 text-[10px] text-faint">Rain sensor timeline (blue = rain reported)</div>
        </Panel>
        <Panel title="Modelled track wetness — remaining laps" tags={["MODEL", "ASSUMPTION"]} note="Wetness 0–1 from the rain timeline (forecast or scenario). Dashed lines: slick→intermediate and intermediate→wet crossovers.">
          <ResponsiveContainer width="100%" height={230}>
            <AreaChart data={d.wetness_path} margin={{ top: 6, right: 8, bottom: 0, left: -22 }}>
              <CartesianGrid stroke={GRID} vertical={false} /><XAxis dataKey="lap" tickFormatter={(v) => `L${v}`} tickLine={false} axisLine={{ stroke: GRID }} /><YAxis domain={[0, 1]} tickLine={false} axisLine={false} width={52} />
              <ReferenceLine y={d.crossover.slick_to_inter} stroke="#3dbb61" strokeDasharray="4 3" /><ReferenceLine y={d.crossover.inter_to_wet} stroke="#3d8bf2" strokeDasharray="4 3" />
              <Tooltip content={<ChartTip title={(l: number) => `Lap ${l}`} fmt={(v: number) => v.toFixed(2)} />} />
              <Area type="monotone" dataKey="wetness" name="Wetness" stroke={SERIES[0]} fill={SERIES[0]} fillOpacity={0.18} strokeWidth={2} isAnimationActive={false} />
              <Line type="stepAfter" dataKey="rain" name="Rain intensity" stroke="#a3a8b3" strokeWidth={1} dot={false} isAnimationActive={false} />
            </AreaChart></ResponsiveContainer>
        </Panel>
        <Panel title="Tyre-class lap-time penalty" tags={["ASSUMPTION"]} note={`Penalty as a share of a dry lap by wetness. ${d.crossover.observed_inter_vs_slick !== null ? `Observed in this session: intermediate laps were ${(d.crossover.observed_inter_vs_slick * 100).toFixed(1)}% slower than slick laps (different track states).` : "No same-session intermediate vs slick comparison available."}`}>
          <ResponsiveContainer width="100%" height={230}>
            <LineChart data={d.crossover.curve} margin={{ top: 6, right: 8, bottom: 0, left: -18 }}>
              <CartesianGrid stroke={GRID} vertical={false} /><XAxis dataKey="wetness" type="number" domain={[0, 1]} tickLine={false} axisLine={{ stroke: GRID }} /><YAxis tickFormatter={(v) => `${Math.round(v * 100)}%`} domain={[0, 0.4]} allowDataOverflow tickLine={false} axisLine={false} width={52} />
              <Tooltip content={<ChartTip title={(l: number) => `Wetness ${l}`} fmt={(v: number) => `+${(v * 100).toFixed(1)}%`} />} /><Legend iconType="plainline" />
              <Line dataKey="slick" name="Slick" stroke="#ff4b3e" strokeWidth={2} dot={false} isAnimationActive={false} /><Line dataKey="inter" name="Intermediate" stroke="#3dbb61" strokeWidth={2} dot={false} isAnimationActive={false} /><Line dataKey="wet" name="Wet" stroke="#3d8bf2" strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart></ResponsiveContainer>
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Open-Meteo — session window" tags={["FORECAST"]} pad={false} note={fc.available ? `${fc.source}. Retrieved ${dt(fc.retrieved)}.` : fc.reason}>
          <div className="max-h-[260px] overflow-auto"><table className="grid-t"><thead><tr><th>UTC</th><th className="r">Precip (mm/15 min)</th><th className="r">Probability</th><th className="r">Temp</th><th className="r">Wind</th><th className="r">Gusts</th><th className="r">Dir</th></tr></thead>
            <tbody>{(fc.rows || []).map((x: any) => <tr key={x.t}><td className="num">{hm(x.t)}</td><td className="r num" style={x.precip_mm_15 > 0 ? { color: "#3d8bf2" } : undefined}>{num(x.precip_mm_15, 2)}</td><td className="r num">{x.precip_prob ?? "—"}%</td><td className="r num">{num(x.temp)}°</td><td className="r num">{num(x.wind)} m/s</td><td className="r num">{num(x.gusts)}</td><td className="r num">{num(x.wind_dir, 0)}°</td></tr>)}</tbody></table></div>
        </Panel>
        <Panel title={`Next race forecast${next.data?.race ? ` — ${next.data.race.gp_name}` : ""}`} tags={["FORECAST"]} pad={false}
          note={next.data?.available ? `Race start ${dt(next.data.start)} (${next.data.days_ahead} days ahead). ${next.data.caveat}` : next.data?.reason}>
          <State loading={next.loading} error={next.error}>
            <div className="max-h-[260px] overflow-auto"><table className="grid-t"><thead><tr><th>UTC</th><th className="r">Precip (mm/15 min)</th><th className="r">Probability</th><th className="r">Temp</th><th className="r">Wind</th><th className="r">Gusts</th></tr></thead>
              <tbody>{(next.data?.rows || []).filter((_: any, i: number) => i % 2 === 0).map((x: any) => <tr key={x.t}><td className="num">{hm(x.t)}</td><td className="r num">{num(x.precip_mm_15, 2)}</td><td className="r num">{x.precip_prob ?? "—"}%</td><td className="r num">{num(x.temp)}°</td><td className="r num">{num(x.wind)} m/s</td><td className="r num">{num(x.gusts)}</td></tr>)}</tbody></table></div>
          </State>
        </Panel>
      </div>
      <Notes title="Assumptions & limits" items={d.assumptions} />
    </div>
  );
}
