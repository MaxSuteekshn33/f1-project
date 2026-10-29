/* Suteekshn Mahajan — PlaceCom pitch deck
   Mirrors the F1 driver-card web page (placecom.html).
   Run: node build.js                                            */

const path = require("path");
const PptxGenJS = require("pptxgenjs");
const SKILL = "/Users/suteekshnmahajan/Library/Application Support/Claude/local-agent-mode-sessions/skills-plugin/2c5e2df2-c411-431d-9a0a-9855f5b3ed40/eb63135f-2876-4c94-98e2-25e7c97def2a/skills/pptx";
const { applyTheme } = require(SKILL + "/scripts/apply_theme.js");

const OUT = path.join(__dirname, "..", "Suteekshn Mahajan - PlaceCom Pitch.pptx");
const PHOTO = path.join(__dirname, "..", "placecom-assets", "driver.png");

/* ---------- theme ---------------------------------------------------- */
const THEME = {
  name: "Grid Entry",
  headFontFace: "Arial",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "EAF1F8", // text1  — light ink on a dark deck
    lt1: "06080B", // background1 — carbon
    dk2: "92A6BA", // text2  — muted
    lt2: "111A26", // background2 — panel
    accent1: "E8303A", // F1 red
    accent2: "15E0D0", // telemetry cyan
    accent3: "FFC14D", // amber
    accent4: "B14DFF", // purple
    accent5: "2FD16D", // green
    accent6: "6EA8FF", // blue
    hlink: "15E0D0",
    folHlink: "B14DFF",
  },
};
const HEX = THEME.colors;

const pres = new PptxGenJS();
pres.layout = "LAYOUT_WIDE"; // 13.3 x 7.5
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.author = "Suteekshn Mahajan";
pres.company = "Indian Institute of Foreign Trade, Kolkata";
pres.subject = "Placement Committee candidacy";
pres.title = "Suteekshn Mahajan — Grid Entry";

const C = pres.SchemeColor;
const RARITY = { LEGENDARY: "FFC14D", EPIC: "B14DFF", RARE: "15E0D0" };
const W = 13.3, H = 7.5;

/* ---------- layouts --------------------------------------------------- */
const FOOT = [
  { rect: { x: 0, y: H - 0.5, w: W, h: 0.5, fill: { color: C.background1 }, line: { color: C.background1 } } },
  {
    text: {
      text: "SUTEEKSHN MAHAJAN  ·  MBA (IB) 2026–28  ·  IIFT KOLKATA",
      options: { x: 0.55, y: H - 0.48, w: 8, h: 0.3, fontSize: 9, color: C.text2,
        charSpacing: 2, isTextBox: true, margin: 0, valign: "middle" },
    },
  },
];
const SLIDE_NO = { x: W - 1.05, y: H - 0.48, w: 0.5, h: 0.3, fontSize: 10,
  color: HEX.accent1, bold: true, align: "right", fontFace: THEME.headFontFace };

pres.defineSlideMaster({
  title: "TITLE_DARK",
  background: { color: C.background1 },
  objects: [],
});

pres.defineSlideMaster({
  title: "SECTION_DARK",
  background: { color: C.background1 },
  objects: [
    { placeholder: { options: { name: "kicker", type: "body",
      x: 1.0, y: 2.45, w: 10, h: 0.4, fontSize: 13, bold: true, color: HEX.accent1,
      charSpacing: 5, margin: 0, align: "left", valign: "middle" }, text: "" } },
    { placeholder: { options: { name: "title", type: "title",
      x: 0.95, y: 2.9, w: 11.4, h: 1.3, fontSize: 48, bold: true, color: HEX.dk1,
      fontFace: THEME.headFontFace, charSpacing: -1, margin: 0, align: "left",
      valign: "middle" }, text: "" } },
    { placeholder: { options: { name: "body", type: "body",
      x: 1.0, y: 4.3, w: 9.5, h: 0.6, fontSize: 16, color: HEX.dk2,
      margin: 0, align: "left", valign: "middle" }, text: "" } },
  ],
});

pres.defineSlideMaster({
  title: "CONTENT_DARK",
  background: { color: C.background1 },
  slideNumber: { ...SLIDE_NO },
  objects: [
    { placeholder: { options: { name: "kicker", type: "body",
      x: 0.55, y: 0.36, w: 10, h: 0.3, fontSize: 11, bold: true, color: HEX.accent1,
      charSpacing: 4, margin: 0, align: "left", valign: "middle" }, text: "" } },
    { placeholder: { options: { name: "title", type: "title",
      x: 0.5, y: 0.68, w: 12.3, h: 0.8, fontSize: 36, bold: true, color: HEX.dk1,
      fontFace: THEME.headFontFace, charSpacing: -0.5, margin: 0, align: "left",
      valign: "middle" }, text: "" } },
    ...FOOT,
  ],
});

/* ---------- helpers --------------------------------------------------- */
let z = 0;
const nm = (s) => `${s}-${++z}`;

/** rounded panel used for every card/column in the deck */
function panel(slide, x, y, w, h, accent) {
  slide.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.06,
    fill: { color: C.background2 },
    line: { color: accent, width: 0.75, transparency: 55 },
    shadow: { type: "outer", angle: 90, blur: 10, offset: 2, opacity: 0.45, color: "000000" },
    objectName: nm("panel"),
  });
}

/** the deck's one repeated motif: a number or code inside a coloured ring */
function badge(slide, x, y, d, label, accent, fontSize) {
  slide.addShape(pres.ShapeType.ellipse, {
    x, y, w: d, h: d,
    fill: { color: C.background1 }, line: { color: accent, width: 1.75 },
    objectName: nm("ring"),
  });
  slide.addText(label, {
    x, y, w: d, h: d, align: "center", valign: "middle",
    fontSize: fontSize || 14, bold: true, color: accent,
    fontFace: THEME.headFontFace, isTextBox: true, margin: 0,
    objectName: nm("ring-label"),
  });
}

/* ====================================================================== */
/* 1 · TITLE                                                              */
/* ====================================================================== */
pres.addSection({ title: "Grid entry" });
let s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Grid entry" });

s.addText("26", {
  x: 7.0, y: 0.42, w: 2.85, h: 2.3, fontSize: 150, bold: true,
  color: "161F2B", fontFace: THEME.headFontFace, align: "right",
  isTextBox: true, margin: 0, objectName: "ghost-number",
});
s.addImage({ path: PHOTO, x: 9.95, y: 1.0, w: 1.95, h: 6.3, objectName: "driver" });

s.addText("GRID ENTRY  ·  PLACEMENT COMMITTEE 2026", {
  x: 0.82, y: 1.45, w: 8, h: 0.35, fontSize: 13, bold: true,
  color: HEX.accent2, charSpacing: 5, isTextBox: true, margin: 0,
  objectName: "eyebrow",
});
s.addText("SUTEEKSHN", {
  x: 0.82, y: 1.95, w: 9, h: 1.15, fontSize: 72, bold: true, color: C.text1,
  fontFace: THEME.headFontFace, charSpacing: -2, isTextBox: true, margin: 0,
  objectName: "name-1",
});
s.addText("MAHAJAN", {
  x: 0.82, y: 3.0, w: 9, h: 1.15, fontSize: 72, bold: true, color: HEX.accent1,
  fontFace: THEME.headFontFace, charSpacing: -2, isTextBox: true, margin: 0,
  objectName: "name-2",
});
s.addText(
  "MBA (International Business) 2026–28, IIFT Kolkata.  Corporate Support Committee member.\nEx–Marketing Head, Team Knox, IIT Roorkee.",
  { x: 0.82, y: 4.35, w: 8.2, h: 0.9, fontSize: 15, color: C.text2,
    lineSpacing: 22, isTextBox: true, margin: 0, objectName: "subtitle" }
);
s.addText("This is my driver card. Six strengths, one lap, zero fluff.", {
  x: 0.82, y: 5.35, w: 8.2, h: 0.4, fontSize: 16, bold: true, italic: true,
  color: HEX.accent3, isTextBox: true, margin: 0, objectName: "tagline",
});

[["94", "OVERALL", HEX.accent3], ["+81", "POSITIONS", HEX.accent5], ["400+", "STUDENTS", HEX.accent2]]
  .forEach(([v, k, col], i) => {
    const x = 0.82 + i * 2.3;
    s.addText(v, { x, y: 6.0, w: 2.0, h: 0.52, fontSize: 30, bold: true, color: col,
      fontFace: THEME.headFontFace, isTextBox: true, margin: 0, objectName: nm("ts-v") });
    s.addText(k, { x, y: 6.52, w: 2.0, h: 0.3, fontSize: 10, color: C.text2,
      charSpacing: 3, isTextBox: true, margin: 0, objectName: nm("ts-k") });
  });
s.addNotes("Opening. I'm Suteekshn, MBA IB 2026-28. I'm standing for the Placement Committee. Rather than a list of claims, I've built this as a driver card: every rating on the next slides has a number behind it.");

/* ====================================================================== */
/* 2 · THE PITCH                                                          */
/* ====================================================================== */
pres.addSection({ title: "The case" });
s = pres.addSlide({ masterName: "CONTENT_DARK", sectionTitle: "The case" });
s.addText("THE ONE-LINE PITCH", { placeholder: "kicker" });
s.addText("I have already done the job without the title", { placeholder: "title" });

const ROWS = [
  { n: "01", c: HEX.accent2, h: "Inside the placement process already",
    b: "Corporate Support Committee, IIFT Kolkata — 100+ avenues of recruiter interaction, the Summer Internship Process 2026, and internal coordination for 400+ students. I have conducted GDs and reviewed CVs for this batch." },
  { n: "02", c: HEX.accent1, h: "A team that climbed 81 places",
    b: "Marketing Head of Team Knox, IIT Roorkee. I built the marketing vertical from nothing and took the team from Rank 84 to Rank 7 amongst 150+ teams — then repeated it the following year." },
  { n: "03", c: HEX.accent3, h: "The data work nobody has to ask for",
    b: "A live F1 analytics platform with Monte Carlo race simulations, a world news tracker, dashboards — all built with Claude Code. If the committee needs a tracker, it exists the same week." },
];
ROWS.forEach((r, i) => {
  const y = 1.85 + i * 1.72;
  panel(s, 0.55, y, 12.2, 1.5, r.c);
  badge(s, 0.85, y + 0.37, 0.76, r.n, r.c, 16);
  s.addText(r.h, { x: 1.85, y: y + 0.22, w: 10.5, h: 0.38, fontSize: 19, bold: true,
    color: C.text1, isTextBox: true, margin: 0, objectName: nm("row-h") });
  s.addText(r.b, { x: 1.85, y: y + 0.62, w: 10.6, h: 0.72, fontSize: 14, color: C.text2,
    lineSpacing: 18, valign: "top", isTextBox: true, margin: 0, objectName: nm("row-b") });
});
s.addNotes("Three things I bring: exposure to the process, a track record of lifting a team, and the data skills to run placements on numbers instead of guesswork.");

/* ====================================================================== */
/* 3 · ATTRIBUTE SHEET                                                    */
/* ====================================================================== */
s = pres.addSlide({ masterName: "CONTENT_DARK", sectionTitle: "The case" });
s.addText("SECTION 01 — DRIVER RATING", { placeholder: "kicker" });
s.addText("The attribute sheet", { placeholder: "title" });

/* OVR dial */
s.addShape(pres.ShapeType.ellipse, { x: 0.75, y: 2.1, w: 3.0, h: 3.0,
  fill: { color: C.background2 }, line: { color: HEX.accent3, width: 3 },
  objectName: "ovr-ring" });
s.addText("94", { x: 0.75, y: 2.55, w: 3.0, h: 1.3, align: "center", fontSize: 76,
  bold: true, color: C.text1, fontFace: THEME.headFontFace, isTextBox: true, margin: 0,
  objectName: "ovr-num" });
s.addText("OVERALL", { x: 0.75, y: 3.78, w: 3.0, h: 0.3, align: "center", fontSize: 11,
  color: C.text2, charSpacing: 4, isTextBox: true, margin: 0, objectName: "ovr-lbl" });
s.addText("TIER · LEGENDARY", { x: 0.75, y: 4.15, w: 3.0, h: 0.3, align: "center",
  fontSize: 10, bold: true, color: HEX.accent3, charSpacing: 2, isTextBox: true,
  margin: 0, objectName: "ovr-tier" });
s.addText("Every rating is backed by\nsomething that happened.", {
  x: 0.75, y: 5.4, w: 3.0, h: 0.7, align: "center", fontSize: 12, italic: true,
  color: C.text2, lineSpacing: 16, isTextBox: true, margin: 0, objectName: "ovr-note" });

/* attribute bars — composed, to match the web page's stat panel */
const ATTR = [
  ["AI & DATA CRAFT", 94, HEX.accent3, "F1 analytics platform, Monte Carlo sims, live news tracker"],
  ["TEAM BUILDING", 96, HEX.accent1, "Built a marketing vertical from zero inside Team Knox"],
  ["PLACEMENT OPS IQ", 92, HEX.accent4, "100+ recruiter avenues, SIP 2026, 400+ students"],
  ["CONSISTENCY", 95, HEX.accent2, "95.0% · 92.8% · 91.40% / 8.635 CGPA, four roles at once"],
  ["MARKETING & OUTREACH", 93, HEX.accent5, "7,000+ community at HIPPOS, 2,000 LinkedIn for Team Knox"],
  ["PRESSURE MANAGEMENT", 91, HEX.accent6, "Rank 58 of 5,276 at the Bajaj Finserv Atom CEO Challenge"],
];
const BX = 4.4, BW = 8.35;
ATTR.forEach(([label, val, col, note], i) => {
  const y = 1.95 + i * 0.84;
  s.addText(label, { x: BX, y, w: 5.6, h: 0.28, fontSize: 13, bold: true, color: C.text1,
    charSpacing: 1, isTextBox: true, margin: 0, objectName: nm("at-l") });
  s.addText(String(val), { x: BX + BW - 0.9, y: y - 0.04, w: 0.9, h: 0.34, align: "right",
    fontSize: 19, bold: true, color: col, fontFace: THEME.headFontFace,
    isTextBox: true, margin: 0, objectName: nm("at-v") });
  s.addShape(pres.ShapeType.rect, { x: BX, y: y + 0.32, w: BW, h: 0.13,
    fill: { color: C.background2 }, line: { color: C.background2 }, objectName: nm("at-tr") });
  s.addShape(pres.ShapeType.rect, { x: BX, y: y + 0.32, w: BW * val / 100, h: 0.13,
    fill: { color: col }, line: { color: col }, objectName: nm("at-fl") });
  s.addText(note, { x: BX, y: y + 0.48, w: BW, h: 0.26, fontSize: 11, color: C.text2,
    isTextBox: true, margin: 0, objectName: nm("at-n") });
});
s.addNotes("Six attributes. The bars are the claim; the line under each is the evidence. Overall 94 — the weakest is pressure management at 91, and even that has a national ranking behind it.");

/* ====================================================================== */
/* 4 · SECTION DIVIDER                                                    */
/* ====================================================================== */
pres.addSection({ title: "The deck" });
s = pres.addSlide({ masterName: "SECTION_DARK", sectionTitle: "The deck" });
s.addText("SECTION 02", { placeholder: "kicker" });
s.addText("Six cards, six strengths", { placeholder: "title" });
s.addText("The front is the claim. The back is the receipt.", { placeholder: "body" });
[HEX.accent3, HEX.accent1, HEX.accent4, HEX.accent2, HEX.accent5, HEX.accent6]
  .forEach((col, i) => {
    s.addShape(pres.ShapeType.roundRect, {
      x: 1.0 + i * 0.62, y: 5.85, w: 0.46, h: 0.62, rectRadius: 0.08,
      fill: { color: C.background2 }, line: { color: col, width: 1.5 },
      objectName: nm("mini-card"),
    });
  });
s.addNotes("Six cards. Two legendary, three epic, one rare — same grammar as an F1 game driver card.");

/* ====================================================================== */
/* 5 & 6 · THE CARDS                                                      */
/* ====================================================================== */
const CARDS = [
  { t: "VIBE CODE", ovr: 94, r: "LEGENDARY", c: HEX.accent3, sub: "AI & DATA · SPECIAL ABILITY",
    stat: "LIVE", statk: "PRODUCTS SHIPPED WITH AI",
    pts: ["Built a live F1 analytics platform with Claude Code — race strategy, performance and driver insights.",
          "Monte Carlo simulations for outcome modelling, plus a world news tracker on an interactive map."] },
  { t: "TEAM ARCHITECT", ovr: 96, r: "LEGENDARY", c: HEX.accent1, sub: "LEADERSHIP · BUILD FROM ZERO",
    stat: "P84 → P7", statk: "POSITIONS CLIMBED",
    pts: ["Marketing Head, Team Knox, IIT Roorkee. There was no marketing vertical — I built it.",
          "Rank 84 to the Top 10 amongst 150+ teams, and Rank 7 twice over — 2021 and 2022."] },
  { t: "PODIUM MAKER", ovr: 95, r: "EPIC", c: HEX.accent4, sub: "MENTORSHIP · LEGACY",
    stat: "P3", statk: "WITHOUT ME IN THE CAR",
    pts: ["After graduating I kept mentoring the junior Team Knox squad through the handover.",
          "They took 3rd in Cost Evaluation at BAJA SAE India 2023 — with me off the roster."] },
  { t: "CONSISTENCY ENGINE", ovr: 95, r: "EPIC", c: HEX.accent2, sub: "ACADEMICS UNDER LOAD",
    stat: "90%+", statk: "ACROSS X, XII AND UG",
    pts: ["95.00% in Class X, 92.80% in Class XII, and 91.40% / 8.635 CGPA at IIT Roorkee.",
          "First Division with Distinction — while running marketing, a subsystem and a tutoring programme."] },
  { t: "RECRUITER RADAR", ovr: 92, r: "EPIC", c: HEX.accent5, sub: "PLACEMENT OPERATIONS",
    stat: "100+", statk: "RECRUITER AVENUES",
    pts: ["Corporate Support Committee, IIFT Kolkata — 100+ avenues of recruiter interaction executed.",
          "Bridged the Placement Committee and the MBA-IB batch through the Summer Internship Process 2026."] },
  { t: "PIT WALL COMMS", ovr: 93, r: "RARE", c: HEX.accent6, sub: "OUTREACH & COMMUNITY",
    stat: "7,000+", statk: "COMMUNITY BUILT",
    pts: ["Founded HIPPOS — 7,000+ followers, 10+ writers and a weekly policy newsletter.",
          "Took Team Knox to 2,000 LinkedIn followers; tutored 50+ juniors under IIT Roorkee's ARP."] },
];

function cardSlide(group, kicker, title, note) {
  const sl = pres.addSlide({ masterName: "CONTENT_DARK", sectionTitle: "The deck" });
  sl.addText(kicker, { placeholder: "kicker" });
  sl.addText(title, { placeholder: "title" });
  group.forEach((c, i) => {
    const x = 0.85 + i * 4.0, y = 1.72, w = 3.6, h = 5.0;
    panel(sl, x, y, w, h, c.c);

    const rc = RARITY[c.r];
    sl.addShape(pres.ShapeType.roundRect, { x: x + 0.22, y: y + 0.24, w: 1.3, h: 0.3,
      rectRadius: 0.04, fill: { color: rc }, line: { color: rc }, objectName: nm("rar") });
    sl.addText(c.r, { x: x + 0.22, y: y + 0.24, w: 1.3, h: 0.3, align: "center",
      valign: "middle", fontSize: 9, bold: true, color: "0A0D12", charSpacing: 1,
      isTextBox: true, margin: 0, objectName: nm("rar-t") });

    sl.addText(String(c.ovr), { x: x + w - 1.3, y: y + 0.14, w: 1.1, h: 0.5, align: "right",
      fontSize: 30, bold: true, color: C.text1, fontFace: THEME.headFontFace,
      isTextBox: true, margin: 0, objectName: nm("c-ovr") });
    sl.addText("RATING", { x: x + w - 1.3, y: y + 0.62, w: 1.1, h: 0.22, align: "right",
      fontSize: 8, color: C.text2, charSpacing: 2, isTextBox: true, margin: 0,
      objectName: nm("c-ovrk") });

    badge(sl, x + w / 2 - 0.45, y + 1.0, 0.9, String(c.ovr), c.c, 20);

    sl.addText(c.t, { x: x + 0.22, y: y + 2.05, w: w - 0.44, h: 0.34, align: "center",
      fontSize: 17, bold: true, color: C.text1, fontFace: THEME.headFontFace,
      charSpacing: -0.3, isTextBox: true, margin: 0, objectName: nm("c-t") });
    sl.addText(c.sub, { x: x + 0.22, y: y + 2.4, w: w - 0.44, h: 0.26, align: "center",
      fontSize: 9, color: C.text2, charSpacing: 1.5, isTextBox: true, margin: 0,
      objectName: nm("c-s") });

    sl.addText(c.pts.map((p, k) => ({ text: p, options: { bullet: { indent: 11 }, breakLine: k < c.pts.length - 1 } })), {
      x: x + 0.24, y: y + 2.66, w: w - 0.48, h: 1.74, fontSize: 11.5, color: C.text2,
      lineSpacing: 14, paraSpaceAfter: 8, valign: "top", isTextBox: true, margin: 0,
      objectName: nm("c-p"),
    });

    sl.addText([
      { text: c.stat, options: { fontSize: 17, bold: true, color: c.c, fontFace: THEME.headFontFace } },
      { text: "   " + c.statk, options: { fontSize: 9, color: C.text2, charSpacing: 1 } },
    ], { x: x + 0.24, y: y + h - 0.6, w: w - 0.48, h: 0.42, valign: "middle",
      isTextBox: true, margin: 0, objectName: nm("c-stat") });
  });
  sl.addNotes(note);
  return sl;
}

cardSlide(CARDS.slice(0, 3), "SECTION 02 — THE DECK  ·  1 OF 2",
  "What I build, and what I build with people",
  "Vibe Code: I ship the data work myself. Team Architect: 81 places, twice over. Podium Maker: the result came after I left — that is what a committee seat should leave behind.");
cardSlide(CARDS.slice(3, 6), "SECTION 02 — THE DECK  ·  2 OF 2",
  "What I hold steady, and who I hold it for",
  "Consistency under load, the recruiter-side view from the CSC, and the comms work — 7,000 people who follow something I built because it is useful.");

/* ====================================================================== */
/* 7 · RACE TRACE                                                         */
/* ====================================================================== */
pres.addSection({ title: "Evidence" });
s = pres.addSlide({ masterName: "CONTENT_DARK", sectionTitle: "Evidence" });
s.addText("SECTION 03 — RACE TRACE", { placeholder: "kicker" });
s.addText("P84 → P7 → P3", { placeholder: "title" });

s.addChart(pres.ChartType.line,
  [{ name: "National rank", labels: ["2020", "2021", "2022", "2023"], values: [84, 7, 7, 3] }],
  { x: 0.55, y: 1.85, w: 8.5, h: 4.75,
    chartColors: [HEX.accent1], lineSize: 4, lineSmooth: false,
    lineDataSymbol: "circle", lineDataSymbolSize: 11,
    lineDataSymbolLineColor: HEX.accent1, lineDataSymbolLineSize: 2,
    showValue: true, dataLabelPosition: "t", dataLabelColor: C.text1,
    dataLabelFontSize: 15, dataLabelFontBold: true, dataLabelFontFace: "+mn-lt",
    valAxisLogScaleBase: 10, valAxisMaxVal: 100, valAxisMinVal: 1,
    valAxisTitle: "National rank  (lower is better)", showValAxisTitle: true,
    valAxisTitleColor: HEX.accent2, valAxisTitleFontSize: 11, valAxisTitleFontFace: "+mn-lt",
    catAxisLabelColor: C.text2, catAxisLabelFontSize: 12, catAxisLabelFontFace: "+mn-lt",
    valAxisLabelColor: C.text2, valAxisLabelFontSize: 11, valAxisLabelFontFace: "+mn-lt",
    valGridLine: { color: "1E2A38", size: 1 }, catGridLine: { style: "none" },
    catAxisLineColor: "2A3A4C", valAxisLineColor: "2A3A4C",
    showLegend: false, showTitle: false,
    plotArea: { fill: { color: HEX.lt2 } }, chartArea: { fill: { color: HEX.lt1 } },
    objectName: "race-trace",
  });

panel(s, 9.35, 1.85, 3.4, 4.75, HEX.accent5);
s.addText("+81", { x: 9.6, y: 2.1, w: 2.9, h: 1.0, fontSize: 62, bold: true,
  color: HEX.accent5, fontFace: THEME.headFontFace, isTextBox: true, margin: 0,
  objectName: "delta-num" });
s.addText("POSITIONS GAINED", { x: 9.6, y: 3.1, w: 2.9, h: 0.28, fontSize: 10,
  color: C.text2, charSpacing: 3, isTextBox: true, margin: 0, objectName: "delta-k" });
s.addText(
  "Team Knox entered the Sales Evaluation event at Rank 84. I built the marketing function around it and we finished Rank 7 — then did it again the next year, so nobody could call it luck.\n\nAfter I graduated, the junior team I mentored took 3rd place in Cost Evaluation at BAJA SAE India 2023.",
  { x: 9.6, y: 3.55, w: 2.9, h: 2.8, fontSize: 12.5, color: C.text2, lineSpacing: 17,
    valign: "top", isTextBox: true, margin: 0, objectName: "delta-body" });
s.addNotes("BAJA SAE India, a national field of 150+ teams. Note the axis is logarithmic — the jump from 84 to 7 is the big one, but holding 7 and then taking the junior team to 3 is the part that says it was systematic.");

/* ====================================================================== */
/* 8 · SECTOR TIMES                                                       */
/* ====================================================================== */
s = pres.addSlide({ masterName: "CONTENT_DARK", sectionTitle: "Evidence" });
s.addText("SECTION 04 — SECTOR TIMES", { placeholder: "kicker" });
s.addText("Why the PlaceCom seat", { placeholder: "title" });

const SECT = [
  { n: "S1", t: "27.4", name: "EXPOSURE", c: HEX.accent4, tag: "PERSONAL BEST",
    b: "On the Corporate Support Committee I sat inside the Summer Internship Process 2026 — conducting GDs, reviewing CVs, bridging the Placement Committee and the MBA-IB batch. I have watched ICICI Bank, Accel, Philips and D. E. Shaw run a process from the floor, not from a recap email." },
  { n: "S2", t: "31.9", name: "EXECUTION", c: HEX.accent5, tag: "FASTEST",
    b: "Rank 84 to Rank 7, twice. 100+ recruiter interaction avenues executed. Two internships shipped — a 7-supplier sourcing plan at >95% QC, and a full-funnel GTM that hit 48% GM/SKU at a CAC of ₹285. I close loops and document them." },
  { n: "S3", t: "24.8", name: "EMPATHY", c: HEX.accent2, tag: "PERSONAL BEST",
    b: "400+ students, each with a different profile and a different fear. I have assisted batchmates on CVs and mock GDs, tutored 50+ juniors, and run a 7,000-person community where the only currency is being useful. Placements are a people problem first." },
];
SECT.forEach((r, i) => {
  const x = 0.55 + i * 4.15, y = 1.85, w = 3.75, h = 4.5;
  panel(s, x, y, w, h, r.c);
  badge(s, x + 0.28, y + 0.3, 0.62, r.n, r.c, 13);
  s.addText(r.tag, { x: x + w - 1.65, y: y + 0.42, w: 1.4, h: 0.26, align: "right",
    fontSize: 8.5, bold: true, color: r.c, charSpacing: 1.5, isTextBox: true, margin: 0,
    objectName: nm("sec-tag") });
  s.addText(r.t, { x: x + 0.28, y: y + 1.1, w: w - 0.56, h: 0.72, fontSize: 44, bold: true,
    color: r.c, fontFace: THEME.headFontFace, isTextBox: true, margin: 0,
    objectName: nm("sec-time") });
  s.addText(r.name, { x: x + 0.28, y: y + 1.78, w: w - 0.56, h: 0.3, fontSize: 14, bold: true,
    color: C.text1, charSpacing: 3, isTextBox: true, margin: 0, objectName: nm("sec-name") });
  s.addText(r.b, { x: x + 0.28, y: y + 2.16, w: w - 0.56, h: 2.1, fontSize: 12.5,
    color: C.text2, lineSpacing: 17, valign: "top", isTextBox: true, margin: 0, objectName: nm("sec-b") });
});
s.addNotes("Three sectors. Exposure — I already know the process. Execution — I finish things. Empathy — the 200th person on the shortlist is the one who needs the committee most.");

/* ====================================================================== */
/* 9 · THE LAP SO FAR                                                     */
/* ====================================================================== */
s = pres.addSlide({ masterName: "CONTENT_DARK", sectionTitle: "Evidence" });
s.addText("SECTION 05 — CIRCUIT MAP", { placeholder: "kicker" });
s.addText("The lap so far", { placeholder: "title" });

const MILE = [
  ["S/F", "2018", "IIT Roorkee — B.Tech begins", HEX.accent2],
  ["T1", "2019", "Best Aesthetics, Srishti’19", HEX.accent6],
  ["T2", "2020", "Team Knox — Suspension Engineer", HEX.accent6],
  ["T3", "2021", "Rank 7 national — BAJA SAE", HEX.accent1],
  ["T4", "2022", "Marketing Head — Rank 7 again", HEX.accent1],
  ["T5", "2022", "Graduated — 8.635 CGPA", HEX.accent3],
  ["T6", "2023", "Mentored team → 3rd place", HEX.accent4],
  ["T7", "2025", "Soul Mirage — GTM & sourcing", HEX.accent5],
  ["T8", "2026", "Escorts Kubota — Mgmt Trainee", HEX.accent5],
  ["T9", "2026", "IIFT Kolkata — CSC member", HEX.accent2],
];
MILE.forEach(([code, yr, txt, col], i) => {
  const col_i = i % 5, row = Math.floor(i / 5);
  const x = 0.45 + col_i * 2.52, y = 2.0 + row * 2.4;
  panel(s, x, y, 2.3, 2.05, col);
  badge(s, x + 0.2, y + 0.2, 0.6, code, col, 12);
  s.addText(yr, { x: x + 0.2, y: y + 0.92, w: 1.9, h: 0.34, fontSize: 20, bold: true,
    color: col, fontFace: THEME.headFontFace, isTextBox: true, margin: 0, objectName: nm("ml-y") });
  s.addText(txt, { x: x + 0.2, y: y + 1.28, w: 1.95, h: 0.68, fontSize: 11.5, color: C.text2,
    lineSpacing: 14, valign: "top", isTextBox: true, margin: 0, objectName: nm("ml-t") });
});
s.addNotes("Ten corners, 2018 to today. The through-line is that every role was one I built or lifted rather than inherited.");

/* ====================================================================== */
/* 10 · CLOSING                                                           */
/* ====================================================================== */
pres.addSection({ title: "The ask" });
s = pres.addSlide({ masterName: "CONTENT_DARK", sectionTitle: "The ask" });
s.addText("CHEQUERED FLAG", { placeholder: "kicker" });
s.addText("Give me the seat", { placeholder: "title" });

const CQ = 0.254, CQN = Math.round(12.2 / CQ);
for (let i = 0; i < CQN; i++) {
  const lit = i % 2 === 0 ? "E9EEF4" : "161F2B";
  const alt = i % 2 === 0 ? "161F2B" : "E9EEF4";
  s.addShape(pres.ShapeType.rect, { x: 0.55 + i * CQ, y: 1.68, w: CQ, h: 0.14,
    fill: { color: lit }, line: { color: lit, width: 0 }, objectName: nm("chq-a") });
  s.addShape(pres.ShapeType.rect, { x: 0.55 + i * CQ, y: 1.82, w: CQ, h: 0.14,
    fill: { color: alt }, line: { color: alt, width: 0 }, objectName: nm("chq-b") });
}

s.addText(
  "I have already done the job without the title — inside the Corporate Support Committee, inside a team that climbed 81 places, inside a community of 7,000.",
  { x: 0.55, y: 2.3, w: 12.2, h: 0.75, fontSize: 19, color: C.text1, lineSpacing: 26,
    isTextBox: true, margin: 0, objectName: "close-1" });
s.addText(
  "Put me on the Placement Committee and I will bring the same three things: the data to see the grid clearly, the discipline to run the process, and the patience to sit with the person who is 200th on the shortlist.",
  { x: 0.55, y: 3.1, w: 12.2, h: 0.8, fontSize: 15, color: C.text2, lineSpacing: 22,
    isTextBox: true, margin: 0, objectName: "close-2" });

const FIN = [["+81", "POSITIONS GAINED", HEX.accent5], ["400+", "STUDENTS SUPPORTED", HEX.accent2],
  ["100+", "RECRUITER AVENUES", HEX.accent3], ["7,000+", "COMMUNITY BUILT", HEX.accent4],
  ["90%+", "X · XII · UG", HEX.accent1]];
FIN.forEach(([v, k, col], i) => {
  const x = 0.55 + i * 2.5;
  panel(s, x, 4.2, 2.3, 1.3, col);
  s.addText(v, { x: x + 0.15, y: 4.42, w: 2.0, h: 0.55, align: "center", fontSize: 28,
    bold: true, color: col, fontFace: THEME.headFontFace, isTextBox: true, margin: 0,
    objectName: nm("fin-v") });
  s.addText(k, { x: x + 0.1, y: 4.98, w: 2.1, h: 0.3, align: "center", fontSize: 9,
    color: C.text2, charSpacing: 1.5, isTextBox: true, margin: 0, objectName: nm("fin-k") });
});

s.addText("LIGHTS OUT — LET'S GO", { x: 0.55, y: 5.85, w: 4.0, h: 0.52, align: "center",
  valign: "middle", fontSize: 15, bold: true, color: "FFFFFF", charSpacing: 2,
  fill: { color: HEX.accent1 }, isTextBox: true, margin: 0, objectName: "cta" });
s.addText("Full driver card:  suteekshn-mahajan-profile.vercel.app", {
  x: 4.85, y: 5.85, w: 7.9, h: 0.52, valign: "middle", fontSize: 13, color: HEX.accent2,
  isTextBox: true, margin: 0, objectName: "cta-url" });
s.addNotes("The ask. And the live version of this driver card is online — the URL is on the slide.");

/* ---------------------------------------------------------------------- */
pres.writeFile({ fileName: OUT })
  .then(() => applyTheme(OUT, THEME))
  .then(() => console.log("wrote " + OUT))
  .catch((e) => { console.error("FAILED:", e); process.exit(1); });
