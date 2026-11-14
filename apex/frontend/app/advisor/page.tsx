"use client";
import { useApi, useRace } from "@/lib/api";
import { Confidence, Notes, Panel, State, Tag, pct, signed } from "@/components/ui";

const TYPE: Record<string, string> = { WEATHER: "#3d8bf2", "SAFETY CAR": "#e0a100", "PIT WINDOW": "#2fbf71", "TRACK POSITION": "#2fbf71", UNDERCUT: "#c084fc", "DEFEND UNDERCUT": "#c084fc", STRATEGY: "#f2f3f5", "TYRE LIFE": "#ff5a52", DATA: "#a3a8b3" };
const tagOf = (s: string) => (s.split(" · ")[0] || "").trim();

export default function Advisor() {
  const r = useRace();
  const { data: d, loading, error } = useApi<any>(r.sessionKey && r.driver ? `/api/advisor?${r.q}&driver=${r.driver}` : null, r.tick);
  if (!d) return <State loading={loading} error={error} />;
  const ex = d.win_explanation;
  const max = ex ? Math.max(...ex.factors.map((x: any) => Math.abs(x.shap)), 0.01) : 1;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-xl font-semibold">Race engineer brief — {d.focus_code ?? "—"}</h1>
        <span className="text-xs text-dim">lap {d.lap} of {d.total_laps}</span>{loading && <span className="animate-pulse text-xs text-faint">recalculating…</span>}
      </div>
      {d.note && <State empty={d.note} />}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,8fr)_minmax(0,4fr)]">
        <div className="space-y-3">
          {d.recommendations.length === 0 && !d.note && <State empty="No actionable situation detected at this lap for this driver." />}
          {d.recommendations.map((x: any, i: number) => (
            <article key={i} className="rounded-md border border-line bg-panel">
              <header className="flex flex-wrap items-center gap-3 border-b border-line px-3 py-2">
                <span className="rounded border px-1.5 py-[1px] text-[9px] font-bold tracking-[.14em]" style={{ borderColor: TYPE[x.type] || "#6b717d", color: TYPE[x.type] || "#a3a8b3" }}>{x.type}</span>
                <h2 className="text-sm font-semibold">{x.title}</h2><span className="ml-auto"><Confidence c={x.confidence} /></span>
              </header>
              <div className="grid gap-3 p-3 md:grid-cols-2">
                <div className="space-y-2">
                  <div><div className="text-[10px] uppercase tracking-[.12em] text-faint">Situation detected</div><p className="mt-0.5 text-[12.5px] leading-relaxed">{x.situation}</p></div>
                  <div><div className="text-[10px] uppercase tracking-[.12em] text-faint">Supporting data</div>
                    <ul className="mt-1 space-y-1 text-[11.5px] text-dim">{x.supporting.map((s: string, k: number) => <li key={k} className="flex gap-2"><span className="shrink-0"><Tag kind={tagOf(s)} /></span><span>{s.split(" · ").slice(1).join(" · ")}</span></li>)}</ul></div>
                </div>
                <div className="space-y-2">
                  <div className="rounded border border-good/40 bg-[#101a13] px-3 py-2"><div className="text-[10px] uppercase tracking-[.12em] text-good">Recommended decision</div><div className="mt-0.5 text-sm font-semibold">{x.decision}</div></div>
                  <div className="grid grid-cols-2 gap-2 text-[11.5px]">
                    <div className="rounded border border-line bg-panel2 px-2.5 py-1.5"><div className="text-[10px] uppercase tracking-[.12em] text-faint">Expected advantage</div><div className="mt-0.5 text-dim">{x.advantage}</div></div>
                    <div className="rounded border border-line bg-panel2 px-2.5 py-1.5"><div className="text-[10px] uppercase tracking-[.12em] text-faint">Risk</div><div className="mt-0.5 text-dim">{x.risk}</div></div>
                  </div>
                </div>
              </div>
            </article>
          ))}
        </div>
        <div className="space-y-4">
          <Panel title={`Why this win probability — ${d.focus_code ?? ""}`} tags={["MODEL"]} note={ex?.note}>
            {ex ? (<>
              <div className="num mb-2 text-2xl font-semibold">{pct(ex.p_win_ml)}<span className="ml-2 text-xs font-normal text-faint">in-race model</span></div>
              <div className="space-y-1.5">{ex.factors.map((f: any, i: number) => (
                <div key={i} className="text-[11.5px]"><div className="flex justify-between text-dim"><span>{f.label}{f.value !== null && <span className="num text-faint"> = {f.value}</span>}</span><span className="num">{signed(f.shap, 2)}</span></div>
                  <div className="relative mt-0.5 h-1.5 rounded-sm bg-[#1c1f25]"><div className="absolute top-0 h-1.5 rounded-sm" style={{ left: f.shap >= 0 ? "50%" : `${50 - (Math.abs(f.shap) / max) * 50}%`, width: `${(Math.abs(f.shap) / max) * 50}%`, background: f.shap >= 0 ? "#3987e5" : "#d95926" }} /></div></div>))}</div>
              <div className="mt-2 text-[10.5px] text-faint">Blue pushes the probability up, orange down.</div>
            </>) : <State empty="Explanation available while a race is in progress and the in-race model is trained." />}
          </Panel>
          <Notes title="Guardrails" items={[d.guardrails, ...(d.omitted || []), "This assistant is rule-based over the platform's own calculations; it does not use a language model and cannot answer free-text questions."]} />
        </div>
      </div>
    </div>
  );
}
