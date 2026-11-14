"use client";
import { useEffect, useState } from "react";
import { api, useRace } from "@/lib/api";
import { Driver, Notes, Panel, State, Tag, Tyre, num, pct, signed, fmtDur } from "@/components/ui";
import { OptionTable, PositionDist } from "@/components/Options";

type Scn = { name: string; mode: "plan" | "pit"; pit_lap?: number; compound: string; second_lap?: number; second_compound?: string; rain: boolean; rain_in_min: number; rain_intensity: number;
  rain_duration_min: number; sc: boolean; sc_lap?: number; sc_type: string; track_temp_delta: number; pit_duration_delta: number; ov_position?: number; ov_compound?: string; ov_age?: number;
  rival?: number; rival_mode: "none" | "stay" | "pit"; rival_lap?: number; rival_compound: string; incidents: boolean };
const blank = (name: string): Scn => ({ name, mode: "plan", compound: "MEDIUM", rain: false, rain_in_min: 10, rain_intensity: 0.5, rain_duration_min: 20, sc: false, sc_type: "SC",
  track_temp_delta: 0, pit_duration_delta: 0, rival_mode: "none", rival_compound: "MEDIUM", incidents: true });
const CMP = ["SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"];

function N({ label, value, onChange, min, max, step = 1, w = "w-16" }: any) {
  return <label className="flex items-center gap-1.5 text-faint">{label}<input type="number" className={w} value={value ?? ""} min={min} max={max} step={step} onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))} /></label>;
}
function C({ value, onChange }: any) { return <select value={value} onChange={(e) => onChange(e.target.value)}>{CMP.map((c) => <option key={c}>{c}</option>)}</select>; }

export default function Lab() {
  const r = useRace();
  const lap = r.lap ?? r.cmd?.max_lap ?? 1;
  const total = r.cmd?.total_laps ?? lap;
  const [scns, setScns] = useState<Scn[]>([blank("Baseline (optimal plan)"), { ...blank("Pit now"), mode: "pit" }]);
  const [res, setRes] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [nSims, setNSims] = useState(1000);
  const upd = (i: number, p: Partial<Scn>) => setScns(scns.map((s, k) => (k === i ? { ...s, ...p } : s)));
  const rows: any[] = r.cmd?.rows || [];
  const me = rows.find((x) => x.driver_number === r.driver);
  const body = () => ({ session_key: r.sessionKey, n_sims: nSims, scenarios: scns.map((s) => ({
    name: s.name, lap: r.lap, driver: r.driver, keep_plan: s.mode === "plan", random_incidents: s.incidents,
    pit_laps: s.mode === "pit" ? [{ lap: s.pit_lap ?? lap + 1, compound: s.compound }, ...(s.second_lap ? [{ lap: s.second_lap, compound: s.second_compound || "MEDIUM" }] : [])] : undefined,
    ...(s.rain ? { rain_in_min: s.rain_in_min, rain_intensity: s.rain_intensity, rain_duration_min: s.rain_duration_min } : {}),
    ...(s.sc ? { safety_car: { lap: s.sc_lap ?? lap + 1, type: s.sc_type } } : {}),
    track_temp_delta: s.track_temp_delta || undefined, pit_duration_delta: s.pit_duration_delta || undefined,
    overrides: s.ov_position || s.ov_compound || s.ov_age !== undefined ? { position: s.ov_position, compound: s.ov_compound, tyre_age: s.ov_age } : undefined,
    rival: s.rival && s.rival_mode !== "none" ? (s.rival_mode === "stay" ? { driver: s.rival, stay_out: true } : { driver: s.rival, pit_laps: [{ lap: s.rival_lap ?? lap + 1, compound: s.rival_compound }] }) : undefined })) });
  const run = () => { setBusy(true); setErr(null); api("/api/sim/run", body()).then(setRes).catch((e) => setErr(String(e.message))).finally(() => setBusy(false)); };
  useEffect(() => { setRes(null); }, [r.sessionKey, r.lap, r.driver]);
  const quick = (k: string) => {
    const p2 = rows.find((x) => x.position === 2), p1 = rows[0];
    if (k === "pit5") setScns([{ ...blank("Pit now"), mode: "pit", pit_lap: lap + 1 }, { ...blank("Pit five laps later"), mode: "pit", pit_lap: lap + 6 }]);
    if (k === "rain") setScns([blank("No rain"), { ...blank("Rain begins in 10 min"), rain: true }]);
    if (k === "sc") setScns([blank("No Safety Car"), { ...blank(`Safety Car, 15 laps to go`), sc: true, sc_lap: Math.max(lap + 1, total - 15), incidents: false }]);
    if (k === "hard") setScns([{ ...blank("Next stop: mediums"), mode: "pit", compound: "MEDIUM", pit_lap: lap + 1 }, { ...blank("Next stop: hards"), mode: "pit", compound: "HARD", pit_lap: lap + 1 }]);
    if (k === "lead" && p1 && p2) { r.setDriver(p2.driver_number); setScns([{ ...blank(`P2 pits, ${p1.code} covers`), mode: "pit", pit_lap: lap + 1 }, { ...blank(`P2 pits, ${p1.code} stays out`), mode: "pit", pit_lap: lap + 1, rival: p1.driver_number, rival_mode: "stay" }]); }
  };
  const good = (res?.results || []).filter((x: any) => !x.error);
  const best = good.find((x: any) => x.best);
  return (
    <div className="space-y-4">
      <Panel title={`Scenario builder — ${me?.code ?? "—"} from lap ${lap}/${total}`} tags={["ASSUMPTION"]}
        right={<><span className="text-faint">Quick questions:</span><button className="btn" onClick={() => quick("pit5")}>Pit now vs +5 laps</button><button className="btn" onClick={() => quick("rain")}>Rain in 10 min</button>
          <button className="btn" onClick={() => quick("sc")}>SC with 15 to go</button><button className="btn" onClick={() => quick("hard")}>Hards vs mediums</button><button className="btn" onClick={() => quick("lead")}>Leader stays out, P2 pits</button></>}
        note="Starting positions, gaps and tyres come from the recorded race at the chosen lap (change it with the lap control in the header). Everything you set here is a scenario assumption and is listed with the result.">
        <div className="grid gap-3 lg:grid-cols-2">
          {scns.map((s, i) => (
            <div key={i} className="space-y-2 rounded border border-line bg-panel2 p-2.5 text-xs">
              <div className="flex items-center gap-2"><span className="num text-faint">{i + 1}</span><input type="text" className="flex-1 font-semibold" value={s.name} onChange={(e) => upd(i, { name: e.target.value })} aria-label="Scenario name" />
                {scns.length > 1 && <button className="btn" onClick={() => setScns(scns.filter((_, k) => k !== i))} aria-label="Remove scenario">✕</button>}</div>
              <div className="flex flex-wrap items-center gap-2"><span className="w-16 text-faint">Strategy</span>
                <select value={s.mode} onChange={(e) => upd(i, { mode: e.target.value as any })}><option value="plan">Optimiser's plan</option><option value="pit">Forced stops</option></select>
                {s.mode === "pit" && <><N label="lap" value={s.pit_lap ?? lap + 1} min={lap + 1} max={total - 1} onChange={(v: number) => upd(i, { pit_lap: v })} /><C value={s.compound} onChange={(v: string) => upd(i, { compound: v })} /></>}</div>
              {s.mode === "pit" && <div className="flex flex-wrap items-center gap-2"><span className="w-16 text-faint">2nd stop</span><N label="lap" value={s.second_lap} min={lap + 2} max={total - 1} onChange={(v: number) => upd(i, { second_lap: v })} /><C value={s.second_compound || "MEDIUM"} onChange={(v: string) => upd(i, { second_compound: v })} /><span className="text-faint">(optional)</span></div>}
              <div className="flex flex-wrap items-center gap-2"><label className="flex w-16 items-center gap-1.5 text-faint"><input type="checkbox" checked={s.rain} onChange={(e) => upd(i, { rain: e.target.checked })} />Rain</label>
                {s.rain && <><N label="in (min)" value={s.rain_in_min} min={0} onChange={(v: number) => upd(i, { rain_in_min: v ?? 0 })} /><N label="intensity" value={s.rain_intensity} min={0} max={1} step={0.05} onChange={(v: number) => upd(i, { rain_intensity: v ?? 0 })} /><N label="for (min)" value={s.rain_duration_min} min={1} onChange={(v: number) => upd(i, { rain_duration_min: v ?? 1 })} /></>}</div>
              <div className="flex flex-wrap items-center gap-2"><label className="flex w-16 items-center gap-1.5 text-faint"><input type="checkbox" checked={s.sc} onChange={(e) => upd(i, { sc: e.target.checked })} />SC</label>
                {s.sc && <><N label="on lap" value={s.sc_lap ?? lap + 1} min={lap + 1} max={total} onChange={(v: number) => upd(i, { sc_lap: v })} /><select value={s.sc_type} onChange={(e) => upd(i, { sc_type: e.target.value })}><option value="SC">Safety Car</option><option value="VSC">Virtual SC</option></select></>}</div>
              <div className="flex flex-wrap items-center gap-2"><span className="w-16 text-faint">Track</span><N label="temp Δ°C" value={s.track_temp_delta} min={-20} max={20} onChange={(v: number) => upd(i, { track_temp_delta: v ?? 0 })} /><N label="pit stop Δs" value={s.pit_duration_delta} min={-3} max={20} step={0.5} onChange={(v: number) => upd(i, { pit_duration_delta: v ?? 0 })} /></div>
              <div className="flex flex-wrap items-center gap-2"><span className="w-16 text-faint">Car state</span><N label="position" value={s.ov_position} min={1} max={22} onChange={(v: number) => upd(i, { ov_position: v })} />
                <select value={s.ov_compound || ""} onChange={(e) => upd(i, { ov_compound: e.target.value || undefined })}><option value="">tyre: as is</option>{CMP.map((c) => <option key={c}>{c}</option>)}</select><N label="age" value={s.ov_age} min={0} max={60} onChange={(v: number) => upd(i, { ov_age: v })} /></div>
              <div className="flex flex-wrap items-center gap-2"><span className="w-16 text-faint">Rival</span>
                <select value={s.rival ?? ""} onChange={(e) => upd(i, { rival: e.target.value ? Number(e.target.value) : undefined })}><option value="">—</option>{rows.filter((x) => x.driver_number !== r.driver && x.status === "RUNNING").map((x) => <option key={x.driver_number} value={x.driver_number}>P{x.position} {x.code}</option>)}</select>
                <select value={s.rival_mode} onChange={(e) => upd(i, { rival_mode: e.target.value as any })}><option value="none">own plan</option><option value="stay">stays out</option><option value="pit">pits on lap…</option></select>
                {s.rival_mode === "pit" && <><N label="" value={s.rival_lap ?? lap + 1} min={lap + 1} max={total - 1} onChange={(v: number) => upd(i, { rival_lap: v })} /><C value={s.rival_compound} onChange={(v: string) => upd(i, { rival_compound: v })} /></>}</div>
              <label className="flex items-center gap-1.5 text-faint"><input type="checkbox" checked={s.incidents} onChange={(e) => upd(i, { incidents: e.target.checked })} />Random incidents (SC/VSC/retirements at historical base rates)</label>
            </div>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button className="btn primary" onClick={run} disabled={busy || !r.sessionKey}>{busy ? "Simulating…" : `Run ${scns.length} scenario${scns.length > 1 ? "s" : ""}`}</button>
          <button className="btn" disabled={scns.length >= 4} onClick={() => setScns([...scns, blank(`Scenario ${scns.length + 1}`)])}>+ Add scenario</button>
          <label className="flex items-center gap-1.5 text-xs text-faint">Simulations each<select value={nSims} onChange={(e) => setNSims(Number(e.target.value))}>{[500, 1000, 2000, 5000].map((n) => <option key={n}>{n}</option>)}</select></label>
        </div>
        {err && <div className="mt-2"><State error={err} /></div>}
      </Panel>

      {res && (<>
        {res.results.filter((x: any) => x.error).map((x: any) => <State key={x.name} empty={`${x.name}: ${x.error}`} />)}
        {good.length > 0 && (<>
          <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-4">
            {good.map((x: any) => (
              <div key={x.name} className={`rounded-md border bg-panel p-3 ${x.best ? "border-good/60" : "border-line"}`}>
                <div className="flex items-center gap-2"><span className="text-sm font-semibold">{x.name}</span>{x.best && <span className="rounded bg-good px-1.5 py-[1px] text-[9px] font-bold text-black">BEST</span>}</div>
                <div className="num mt-2 grid grid-cols-3 gap-2 text-center" title="Expected finish averages over all simulations, including retirements">
                  <div><div className="text-[10px] uppercase tracking-wider text-faint">Exp. finish</div><div className="text-xl font-semibold">P{num(x.exp_pos)}</div><div className="text-[10px] text-faint">P{x.pos_p10}–P{x.pos_p90}</div></div>
                  <div><div className="text-[10px] uppercase tracking-wider text-faint">Win</div><div className="text-xl font-semibold">{pct(x.p_win)}</div><div className="text-[10px] text-faint">±{(x.p_win_se * 196).toFixed(1)} pts</div></div>
                  <div><div className="text-[10px] uppercase tracking-wider text-faint">Podium</div><div className="text-xl font-semibold">{pct(x.p_podium)}</div><div className="text-[10px] text-faint">DNF {pct(x.p_dnf, 0)}</div></div>
                </div>
                <div className="num mt-2 space-y-0.5 text-[11px] text-dim">
                  <div>Remaining race time: <b className="text-ink">{fmtDur(x.exp_race_time_remaining)}</b> <span className="text-faint">(P10–P90 {fmtDur(x.time_p10)} – {fmtDur(x.time_p90)})</span></div>
                  <div>Time vs scenario 1: <b className="text-ink">{x.time_vs_first === null ? "n/a" : `${signed(x.time_vs_first)} s`}</b> · Strategy risk (position SD): <b className="text-ink">{x.risk_pos_sd}</b> · Traffic: {x.blocked_laps} laps</div>
                  <div className="flex flex-wrap items-center gap-1">Stops: {x.plan.length ? x.plan.map((p: any, i: number) => <span key={i} className="inline-flex items-center gap-1">L{p.lap}<Tyre compound={p.compound} /></span>) : "none"}</div>
                  {!x.best && x.best_alternative && <div>Best alternative decision: <b className="text-ink">{x.best_alternative}</b></div>}
                </div>
                {x.assumptions.length > 0 && <ul className="mt-2 space-y-0.5 border-t border-line pt-2 text-[10.5px] text-faint">{x.assumptions.map((a: string, i: number) => <li key={i}><Tag kind="ASSUMPTION" /> {a}</li>)}</ul>}
              </div>
            ))}
          </div>
          <div className="grid gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
            <Panel title="Distribution of finishing positions" tags={["MODEL"]} note={`${good[0].n_sims} Monte Carlo runs per scenario. Bars show how often the focus driver finished in each position.`}>
              <PositionDist options={good.map((x: any) => ({ label: x.name, pos_hist: x.pos_hist }))} />
            </Panel>
            <Panel title={`Simulated front of the field — ${best?.name ?? good[0].name}`} tags={["MODEL"]} pad={false}>
              <table className="grid-t"><thead><tr><th>Driver</th><th className="r">Exp. finish</th><th className="r">Win</th></tr></thead>
                <tbody>{(best || good[0]).field.map((d: any) => <tr key={d.code}><td><Driver code={d.code} colour={d.team_colour} /></td><td className="r num">P{d.exp_pos}</td><td className="r num">{pct(d.p_win)}</td></tr>)}</tbody></table>
            </Panel>
          </div>
          <Notes title="Simulation inputs" items={[res.note, `Pit loss ${good[0].inputs.pit_loss_s} s (${good[0].inputs.pit_loss_source}); pass threshold ${good[0].inputs.overtake_delta_s} s/lap pace advantage (assumption).`,
            `Incident base rates: SC ${(good[0].inputs.sc_per_lap * 100).toFixed(1)}%/lap, VSC ${(good[0].inputs.vsc_per_lap * 100).toFixed(1)}%/lap — ${good[0].inputs.hazard_source}; retirement ${(good[0].inputs.dnf_per_race * 100).toFixed(0)}% per car per race.`,
            "Exact incident timing is never predicted; random incidents are drawn from those base rates."]} />
        </>)}
      </>)}
      <SafetyCar />
    </div>
  );
}

function SafetyCar() {
  const r = useRace();
  const [d, setD] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [dur, setDur] = useState(4);
  const [closed, setClosed] = useState(false);
  useEffect(() => {
    if (!r.sessionKey || !r.driver) return;
    let live = true; setBusy(true); setErr(null);
    api("/api/safetycar", { session_key: r.sessionKey, lap: r.lap, driver: r.driver, duration: dur, pit_closed: closed })
      .then((x) => live && setD(x)).catch((e) => live && setErr(String(e.message))).finally(() => live && setBusy(false));
    return () => { live = false; };
  }, [r.sessionKey, r.lap, r.driver, dur, closed, r.tick]);
  if (!d) return <Panel title="Safety Car & incident simulator"><State loading={busy} error={err} /></Panel>;
  const hz = d.base_rates;
  return (
    <Panel title={`Safety Car & incident simulator — ${d.focus_code ?? "—"}, if neutralised on the next lap`} tags={["HISTORICAL", "MODEL", "ASSUMPTION"]}
      right={<><label className="flex items-center gap-1.5">SC length (laps)<select value={dur} onChange={(e) => setDur(Number(e.target.value))}>{[2, 3, 4, 5, 6].map((n) => <option key={n}>{n}</option>)}</select></label>
        <label className="flex items-center gap-1.5"><input type="checkbox" checked={closed} onChange={(e) => setClosed(e.target.checked)} />Pit lane closed on first lap</label>{busy && <span className="animate-pulse text-faint">recalculating…</span>}</>}
      note={d.disclaimer}>
      <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-5">
        {[["Races with a Safety Car", hz.share_races_with_sc], ["Races with a VSC", hz.share_races_with_vsc], ["Races red-flagged", hz.share_races_red_flag]].map(([l, v]: any) =>
          <div key={l} className="rounded border border-line bg-panel2 px-3 py-2"><div className="text-[10px] uppercase tracking-wider text-faint">{l}</div><div className="num text-lg font-semibold">{v === undefined ? "—" : pct(v, 0)}</div></div>)}
        <div className="rounded border border-line bg-panel2 px-3 py-2"><div className="text-[10px] uppercase tracking-wider text-faint">SC chance per lap</div><div className="num text-lg font-semibold">{(hz.sc_per_lap * 100).toFixed(1)}%</div></div>
        <div className="rounded border border-line bg-panel2 px-3 py-2"><div className="text-[10px] uppercase tracking-wider text-faint">Stop cost green / SC / VSC</div><div className="num text-lg font-semibold">{d.pit_loss ? `${d.pit_loss.green} / ${d.pit_loss.sc} / ${d.pit_loss.vsc} s` : "—"}</div></div>
      </div>
      <div className="mb-2 text-[11px] text-faint">Base rates: {hz.source}.</div>
      {d.note ? <State empty={d.note} /> : (<>
        <div className="mb-3 grid gap-2 md:grid-cols-3">{Object.entries(d.verdicts || {}).map(([k, v]: any) => (
          <div key={k} className="rounded border border-line bg-panel2 px-3 py-2 text-xs"><div className="text-[10px] uppercase tracking-wider text-faint">{k === "sc" ? "Under Safety Car" : k === "vsc" ? "Under VSC" : "Under green"}</div>
            <div className="mt-0.5 text-sm font-semibold" style={{ color: v.better === "PIT" ? "#2fbf71" : "#f2f3f5" }}>{v.better}</div>
            <div className="num text-dim">pitting changes expected finish by {signed(v.pit_minus_stay_positions, 2)} positions{k !== "green" && d.pit_loss ? ` · saves ${k === "sc" ? d.pit_loss.saved_sc : d.pit_loss.saved_vsc} s of pit loss` : ""}</div></div>))}</div>
        <OptionTable options={d.options || []} timeKey="time_vs_first" timeLabel="Time vs first row" />
        <div className="mt-2 text-[11px] text-faint">Times are comparable only between rows with the same neutralisation. {d.pit_loss?.factor_note}</div>
      </>)}
      <div className="mt-3"><Notes title="Red flags, restarts, closures, retirements" items={Object.values(d.extras || {}) as string[]} /></div>
    </Panel>
  );
}
