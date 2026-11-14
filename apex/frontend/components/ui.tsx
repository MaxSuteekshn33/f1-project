"use client";
import React from "react";

// Chart palette: categorical slots validated for the dark surface (dataviz reference palette, fixed order).
export const SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500"];
export const GRID = "#1f2329";
export const COMPOUND: Record<string, { c: string; l: string }> = {
  SOFT: { c: "#ff4b3e", l: "S" }, MEDIUM: { c: "#f2c230", l: "M" }, HARD: { c: "#e9eaec", l: "H" },
  INTERMEDIATE: { c: "#3dbb61", l: "I" }, WET: { c: "#3d8bf2", l: "W" },
};
export const teamColour = (c?: string | null) => (c ? `#${c.replace("#", "")}` : "#6b717d");

export function fmtLap(s?: number | null): string {
  if (s === null || s === undefined || !isFinite(s)) return "—";
  const m = Math.floor(s / 60), r = s - m * 60;
  return m > 0 ? `${m}:${r.toFixed(3).padStart(6, "0")}` : r.toFixed(3);
}
export const fmtDur = (s?: number | null) => {
  if (s === null || s === undefined) return "—";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m ${String(Math.round(s % 60)).padStart(2, "0")}s`;
};
export const pct = (p?: number | null, d = 1) => (p === null || p === undefined ? "—" : `${(p * 100).toFixed(p >= 0.995 || p < 0.0005 ? 0 : d)}%`);
export const num = (v?: number | null, d = 1) => (v === null || v === undefined || !isFinite(v) ? "—" : v.toFixed(d));
export const signed = (v?: number | null, d = 1) => (v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(d)}`);
export const ago = (ts?: number | null) => {
  if (!ts) return "never";
  const s = Date.now() / 1000 - ts;
  return s < 90 ? `${Math.round(s)}s ago` : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 172800 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`;
};
export const dt = (ts?: number | null) => (ts ? new Date(ts * 1000).toISOString().replace("T", " ").slice(0, 16) + " UTC" : "—");

const TAGS: Record<string, string> = {
  OBSERVED: "border-[#2b5a8f] text-[#7fb6f5]", HISTORICAL: "border-[#6a5a2a] text-[#d9b95a]", MODEL: "border-[#5a3f8a] text-[#b79cf0]",
  ASSUMPTION: "border-[#6b3a3a] text-[#f09a94]", FORECAST: "border-[#2a6a5a] text-[#6fd3b8]", UNAVAILABLE: "border-line text-faint",
};
/** Provenance label: where a number comes from. */
export function Tag({ kind, children }: { kind: keyof typeof TAGS | string; children?: React.ReactNode }) {
  return <span className={`inline-block rounded border px-1.5 py-[1px] text-[9px] font-semibold tracking-wider ${TAGS[kind] || TAGS.UNAVAILABLE}`}
    title={{ OBSERVED: "Recorded data from a provider", HISTORICAL: "Estimate from past races", MODEL: "Model prediction", ASSUMPTION: "Scenario or modelling assumption",
      FORECAST: "Weather-model forecast, not a track measurement" }[kind as string] || ""}>{children || kind}</span>;
}

export function Panel({ title, tags, right, children, className = "", note, pad = true }:
  { title?: React.ReactNode; tags?: string[]; right?: React.ReactNode; children: React.ReactNode; className?: string; note?: React.ReactNode; pad?: boolean }) {
  return (
    <section className={`rounded-md border border-line bg-panel ${className}`}>
      {(title || right) && (
        <header className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-[.12em] text-dim">{title}</h2>
          {tags?.map((t) => <Tag key={t} kind={t} />)}
          <div className="ml-auto flex items-center gap-2 text-xs text-dim">{right}</div>
        </header>
      )}
      <div className={pad ? "p-3" : ""}>{children}</div>
      {note && <footer className="border-t border-line px-3 py-2 text-[11px] leading-relaxed text-faint">{note}</footer>}
    </section>
  );
}

export function Stat({ label, value, sub, tag, accent }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tag?: string; accent?: string }) {
  return (
    <div className="rounded-md border border-line bg-panel px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-[.1em] text-faint">{label}{tag && <Tag kind={tag} />}</div>
      <div className="num mt-1 text-xl font-semibold leading-tight" style={accent ? { color: accent } : undefined}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-dim">{sub}</div>}
    </div>
  );
}

export function Tyre({ compound, age }: { compound?: string | null; age?: number | null }) {
  if (!compound) return <span className="text-faint">—</span>;
  const c = COMPOUND[compound] || { c: "#6b717d", l: "?" };
  return (
    <span className="inline-flex items-center gap-1.5" title={compound}>
      <span className="inline-flex h-[18px] w-[18px] items-center justify-center rounded-full border-2 text-[9px] font-bold" style={{ borderColor: c.c, color: c.c }}>{c.l}</span>
      {age !== undefined && age !== null && <span className="num text-dim">{age}</span>}
    </span>
  );
}

export function Driver({ code, colour, name }: { code?: string | null; colour?: string | null; name?: string }) {
  return (
    <span className="inline-flex items-center gap-2" title={name}>
      <span className="inline-block h-3.5 w-1 rounded-sm" style={{ background: teamColour(colour) }} />
      <span className="font-semibold tracking-wide">{code || "—"}</span>
    </span>
  );
}

export function Bar({ value, max = 1, colour = SERIES[0], label }: { value: number; max?: number; colour?: string; label?: string }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 flex-1 rounded-sm bg-[#1c1f25]"><div className="h-2 rounded-sm" style={{ width: `${Math.max(0, Math.min(1, value / max)) * 100}%`, background: colour }} /></div>
      {label && <span className="num w-12 text-right text-[11px]">{label}</span>}
    </div>
  );
}

export function State({ loading, error, empty, children }: { loading?: boolean; error?: string | null; empty?: string | null; children?: React.ReactNode }) {
  if (error) return <div className="rounded border border-[#6b3a3a] bg-[#1d1213] px-3 py-2 text-xs text-[#f09a94]"><b>Unavailable.</b> {error}</div>;
  if (empty) return <div className="rounded border border-line bg-panel2 px-3 py-2 text-xs text-dim">{empty}</div>;
  if (loading && !children) return <div className="animate-pulse px-1 py-6 text-center text-xs text-faint">Calculating…</div>;
  return <>{children}</>;
}

export function Notes({ items, title = "Limitations" }: { items?: (string | null | undefined)[]; title?: string }) {
  const list = (items || []).filter(Boolean) as string[];
  if (!list.length) return null;
  return (
    <div className="rounded-md border border-line bg-panel2 px-3 py-2">
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-[.12em] text-faint">{title}</div>
      <ul className="space-y-0.5 text-[11px] leading-relaxed text-dim">{list.map((x, i) => <li key={i}>• {x}</li>)}</ul>
    </div>
  );
}

export function ChartTip({ active, payload, label, fmt, title }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded border border-line bg-[#0d0f12] px-2.5 py-1.5 text-[11px] shadow-lg">
      <div className="mb-0.5 text-faint">{title ? title(label) : label}</div>
      {payload.map((p: any, i: number) => (
        <div key={i} className="flex items-center gap-2">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: p.color || p.stroke || p.fill }} />
          <span className="text-dim">{p.name}</span><span className="num ml-auto pl-3 text-ink">{fmt ? fmt(p.value, p.name) : p.value}</span>
        </div>
      ))}
    </div>
  );
}

export function Confidence({ c }: { c?: { score: number; level: string } | null }) {
  if (!c) return null;
  const col = c.level === "HIGH" ? "#2fbf71" : c.level === "MEDIUM" ? "#e0a100" : "#a3a8b3";
  return <span className="inline-flex items-center gap-1.5 text-[11px]"><span className="h-1.5 w-1.5 rounded-full" style={{ background: col }} />
    <span style={{ color: col }} className="font-semibold">{c.level}</span><span className="num text-faint">{(c.score * 100).toFixed(0)}%</span></span>;
}
