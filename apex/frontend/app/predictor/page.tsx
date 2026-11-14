"use client";
import { useState } from "react";
import { Bar as RBar, BarChart, CartesianGrid, Cell, ErrorBar, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useApi, useRace } from "@/lib/api";
import { Bar, ChartTip, Driver, GRID, Notes, Panel, State, Tag, Tyre, num, pct, signed, teamColour } from "@/components/ui";

function Explain({ items }: { items: any[] }) {
  if (!items?.length) return <span className="text-faint">—</span>;
  const max = Math.max(...items.map((x) => Math.abs(x.shap)), 0.01);
  return (
    <div className="space-y-1">
      {items.map((x, i) => (
        <div key={i} className="grid grid-cols-[minmax(0,1fr)_90px_44px] items-center gap-2 text-[11px]">
          <span className="truncate text-dim" title={x.label}>{x.label}{x.value !== null && <span className="num text-faint"> = {x.value}</span>}</span>
          <div className="relative h-2 rounded-sm bg-[#1c1f25]">
            <div className="absolute top-0 h-2 rounded-sm" style={{ left: x.shap >= 0 ? "50%" : `${50 - (Math.abs(x.shap) / max) * 50}%`, width: `${(Math.abs(x.shap) / max) * 50}%`, background: x.shap >= 0 ? "#3987e5" : "#d95926" }} />
            <div className="absolute left-1/2 top-[-2px] h-3 w-px bg-faint" />
          </div>
          <span className="num text-right">{signed(x.shap, 2)}</span>
        </div>
      ))}
    </div>
  );
}

function TopFive({ rows, colourKey, ci }: { rows: any[]; colourKey: string; ci: (d: any) => [number, number] | null }) {
  const data = rows.map((d) => { const c = ci(d); return { code: `${d.code}  ${(d.p_win * 100).toFixed(1)}%`, p: d.p_win * 100, colour: teamColour(d[colourKey]), err: c ? [Math.max(0, d.p_win - c[0]) * 100, Math.max(0, c[1] - d.p_win) * 100] : [0, 0] }; });
  return (
    <ResponsiveContainer width="100%" height={210}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 40, bottom: 0, left: 0 }} barCategoryGap={8}>
        <CartesianGrid stroke={GRID} horizontal={false} />
        <XAxis type="number" domain={[0, (m: number) => Math.min(100, Math.ceil((m + 5) / 10) * 10)]} tickFormatter={(v) => `${v}%`} tickLine={false} axisLine={{ stroke: GRID }} />
        <YAxis type="category" dataKey="code" width={92} tickLine={false} axisLine={false} tick={{ fill: "#f2f3f5", fontSize: 12, fontWeight: 600 }} />
        <Tooltip cursor={{ fill: "#ffffff08" }} content={<ChartTip fmt={(v: number) => `${v.toFixed(1)}%`} />} />
        <RBar dataKey="p" name="Win probability" radius={[0, 4, 4, 0]} isAnimationActive={false}>
          {data.map((d, i) => <Cell key={i} fill={d.colour} />)}
          <ErrorBar dataKey="err" width={5} stroke="#f2f3f5" strokeWidth={1.2} direction="x" />
        </RBar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export default function Predictor() {
  const r = useRace();
  const [tab, setTab] = useState<"inrace" | "prerace">("inrace");
  const [open, setOpen] = useState<string | number | null>(null);
  const raceId = r.cmd?.f1db?.race_id;
  const [which, setWhich] = useState<"next" | "selected">("next");
  const { data: ir, loading: irL, error: irE } = useApi<any>(tab === "inrace" && r.sessionKey ? `/api/predict/inrace?${r.q}` : null, r.tick);
  const { data: pr, loading: prL, error: prE } = useApi<any>(tab === "prerace" ? `/api/predict/prerace${which === "selected" && raceId ? `?race_id=${raceId}` : ""}` : null, r.tick);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <button className={`btn ${tab === "inrace" ? "primary" : ""}`} onClick={() => setTab("inrace")}>In-race (as of lap {r.lap ?? r.cmd?.max_lap ?? "—"})</button>
        <button className={`btn ${tab === "prerace" ? "primary" : ""}`} onClick={() => setTab("prerace")}>Pre-race</button>
        {tab === "prerace" && <>
          <span className="ml-3 text-xs text-faint">Race:</span>
          <button className={`btn ${which === "next" ? "!border-dim" : ""}`} onClick={() => setWhich("next")}>Next Grand Prix</button>
          <button className={`btn ${which === "selected" ? "!border-dim" : ""}`} onClick={() => setWhich("selected")} disabled={!raceId}>Selected race (backtest view)</button>
        </>}
      </div>

      {tab === "inrace" && (
        <State loading={irL} error={irE} empty={ir && !ir.available ? ir.reason : null}>
          {ir?.available && (
            <div className="space-y-4">
              <div className="grid gap-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
                <Panel title={`Five most likely winners — lap ${ir.lap}/${ir.total_laps}`} tags={["MODEL"]} note="Whiskers: range between the ML model and the Monte Carlo simulation ± 1.96 simulation standard errors (a model-disagreement range, not a frequentist interval).">
                  <TopFive rows={ir.top5} colourKey="team_colour" ci={(d) => [d.range_lo, d.range_hi]} />
                </Panel>
                <Panel title="How this is calculated" tags={["MODEL", "ASSUMPTION"]}>
                  <ul className="space-y-1.5 text-xs leading-relaxed text-dim">
                    <li><b className="text-ink">Win / podium:</b> {ir.method.p_win}.</li>
                    <li><b className="text-ink">Leakage control:</b> {ir.method.leakage}.</li>
                    <li><b className="text-ink">Simulation inputs:</b> {ir.n_sims} runs · pit loss {ir.sim_inputs.pit_loss_s} s ({ir.sim_inputs.pit_loss_source}) · SC {(ir.sim_inputs.sc_per_lap * 100).toFixed(1)}%/lap, VSC {(ir.sim_inputs.vsc_per_lap * 100).toFixed(1)}%/lap ({ir.sim_inputs.hazard_source}) · retirement {(ir.sim_inputs.dnf_per_race * 100).toFixed(0)}%/race.</li>
                    <li><b className="text-ink">Fastest lap:</b> {ir.method.fastest_lap}.</li>
                    <li><b className="text-ink">Model version:</b> <span className="num">{ir.model_version ?? "not trained"}</span>. Recalculated every time the lap or the stored timing data changes.</li>
                  </ul>
                </Panel>
              </div>
              <Panel title="All drivers" tags={["OBSERVED", "MODEL"]} pad={false} note="Click a row for the factors behind its win probability (SHAP values of the in-race XGBoost model, in log-odds).">
                <div className="overflow-auto"><table className="grid-t">
                  <thead><tr><th>Now</th><th>Driver</th><th>Tyre</th><th className="r">Gap</th><th style={{ width: 170 }}>Win</th><th className="r">ML</th><th className="r">Sim</th><th className="r">Range</th><th className="r">Podium</th><th className="r">Top 5</th><th className="r">Pred. finish</th><th className="r">Sim P10–P90</th><th className="r">Exp. points</th><th className="r">DNF risk</th></tr></thead>
                  <tbody>{ir.drivers.map((d: any) => (<>
                    <tr key={d.driver_number} onClick={() => setOpen(open === d.driver_number ? null : d.driver_number)} style={{ cursor: "pointer" }}>
                      <td className="num">P{d.position}</td><td><Driver code={d.code} colour={d.team_colour} name={d.name} /></td><td><Tyre compound={d.compound} age={d.tyre_age} /></td><td className="r num text-dim">{d.gap}</td>
                      <td><Bar value={d.p_win} colour={teamColour(d.team_colour)} label={pct(d.p_win)} /></td>
                      <td className="r num text-dim">{pct(d.ml_win)}</td><td className="r num text-dim">{pct(d.mc_win)}</td><td className="r num text-faint">{pct(d.range_lo, 0)}–{pct(d.range_hi, 0)}</td>
                      <td className="r num">{pct(d.p_podium)}</td><td className="r num">{pct(d.p_top5)}</td><td className="r num font-semibold">{d.pred_pos ? `P${d.pred_pos}` : "—"}</td>
                      <td className="r num text-dim">P{d.pos_p10}–P{d.pos_p90}</td><td className="r num">{num(d.exp_points)}</td><td className="r num text-dim">{pct(d.p_dnf, 0)}</td>
                    </tr>
                    {open === d.driver_number && <tr key={`${d.driver_number}x`}><td colSpan={14} className="!bg-panel2"><div className="max-w-xl py-1"><Explain items={d.explain} /></div></td></tr>}
                  </>))}</tbody>
                </table></div>
              </Panel>
            </div>
          )}
        </State>
      )}

      {tab === "prerace" && (
        <State loading={prL} error={prE} empty={pr && !pr.available ? pr.reason : null}>
          {pr?.available && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-baseline gap-3">
                <h1 className="text-xl font-semibold">{pr.race.year} {pr.race.gp_name}</h1>
                <span className="text-xs text-dim">Round {pr.race.round} · {pr.race.circuit_name} · {pr.race.date}</span>
                <span className="text-xs text-faint">Model: {pr.variant === "pre_race" ? "post-qualifying (uses the grid)" : "pre-qualifying (no grid yet)"} · v{pr.model_version} · trained through {pr.train_through}</span>
              </div>
              <div className="grid gap-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
                <Panel title="Five most likely winners" tags={["MODEL"]} note="Whiskers: 95% Wilson interval of how often drivers given a probability in this band actually won in the walk-forward backtest.">
                  <TopFive rows={pr.top5} colourKey="colour" ci={(d) => (d.ci ? [d.ci.lo, d.ci.hi] : null)} />
                </Panel>
                <Panel title="Constructors" tags={["MODEL"]} pad={false}>
                  <table className="grid-t"><thead><tr><th>Constructor</th><th style={{ width: 200 }}>Win (either car)</th><th className="r">≥1 podium</th><th className="r">Expected points</th></tr></thead>
                    <tbody>{pr.constructors.map((c: any) => <tr key={c.constructor}><td><span className="mr-2 inline-block h-3 w-1 rounded-sm align-middle" style={{ background: teamColour(c.colour) }} />{c.constructor}</td>
                      <td><Bar value={c.p_win} colour={teamColour(c.colour)} label={pct(c.p_win)} /></td><td className="r num">{pct(c.p_podium_any)}</td><td className="r num">{num(c.exp_points)}</td></tr>)}</tbody></table>
                </Panel>
              </div>
              <Panel title="Driver predictions & championship impact" tags={["MODEL", "OBSERVED"]} pad={false}
                note={<>{pr.method["win/podium"]}. Expected points: {pr.method.points}. Click a row for SHAP factors. {pr.grid_source ? `Grid: ${pr.grid_source}.` : "Grid: not yet available — the pre-qualifying model is used."}</>}>
                <div className="overflow-auto"><table className="grid-t">
                  <thead><tr><th>Driver</th><th>Team</th><th className="r">Grid</th><th style={{ width: 170 }}>Win</th><th className="r">95% band</th><th className="r">Podium</th><th className="r">Top 5</th><th className="r">Fastest lap</th><th className="r">Pred. finish</th>
                    {pr.completed && <th className="r">Actual</th>}<th className="r">Exp. points</th><th className="r">Points now</th><th className="r">Projected</th><th className="r">vs top scorer</th></tr></thead>
                  <tbody>{pr.drivers.map((d: any) => (<>
                    <tr key={d.driver_id} onClick={() => setOpen(open === d.driver_id ? null : d.driver_id)} style={{ cursor: "pointer" }}>
                      <td><Driver code={d.code} colour={d.colour} name={d.name} /> <span className="ml-1 text-dim">{d.name}</span></td><td className="text-dim">{d.constructor}</td><td className="r num">{d.grid ?? "—"}</td>
                      <td><Bar value={d.p_win} colour={teamColour(d.colour)} label={pct(d.p_win)} /></td>
                      <td className="r num text-faint">{d.ci ? `${pct(d.ci.lo, 0)}–${pct(d.ci.hi, 0)}` : "n/a"}</td>
                      <td className="r num">{pct(d.p_podium)}</td><td className="r num">{pct(d.p_top5)}</td><td className="r num">{pct(d.p_fastest_lap)}</td><td className="r num font-semibold">P{d.pred_pos}</td>
                      {pr.completed && <td className="r num" style={{ color: d.actual_pos === 1 ? "#2fbf71" : undefined }}>{d.actual_pos ? `P${d.actual_pos}` : d.actual_text}</td>}
                      <td className="r num">{num(d.exp_points)}</td><td className="r num text-dim">{num(d.points_before, 0)}</td><td className="r num">{num(d.projected_points)}</td><td className="r num text-dim">{signed(d.exp_points_vs_top)}</td>
                    </tr>
                    {open === d.driver_id && <tr key={`${d.driver_id}x`}><td colSpan={14} className="!bg-panel2"><div className="grid max-w-3xl gap-4 py-1 md:grid-cols-2"><Explain items={d.explain} />
                      <div className="text-[11px] text-dim">Per-model win probability:<div className="num mt-1 grid grid-cols-2 gap-x-4">{Object.entries(d.model_spread || {}).map(([k, v]: any) => <span key={k}>{k}: {pct(v)}</span>)}</div></div></div></td></tr>}
                  </>))}</tbody>
                </table></div>
              </Panel>
              <Notes title="Notes" items={[...pr.notes, `Confidence band: ${pr.method.ci}.`, "Wet-weather skill is not a model input: the results history has no weather field before 2023."]} />
            </div>
          )}
        </State>
      )}
    </div>
  );
}
