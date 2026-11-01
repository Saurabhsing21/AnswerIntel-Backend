import React from "react";
import { Circle, Defs, Document, LinearGradient, Page, Path, Rect, Stop, Svg, Text, View } from "@react-pdf/renderer";
import type { Brand, Doc, QuestionRow, Stage } from "./types";
import { Bar, C, Callout, Card, CardTitle, Col, Donut, Gauge, H2, Legend, Pill, SectionHead, Table, pct } from "./ui";

const W = 515; // content width: A4 (595pt) minus 40pt margins
const FONT = ["Geist", "NotoDevanagari"];

function Logo({ size, light }: { size: number; light?: boolean }) {
  return (
    <Svg width={size * 2} height={size * 2}>
      <Circle cx={size} cy={size} r={size} fill={light ? C.white : C.head} />
      <Circle cx={size} cy={size} r={size * 0.45} fill={light ? C.navy : C.white} />
    </Svg>
  );
}

function Shell({ doc, children }: { doc: Doc; children: React.ReactNode }) {
  return (
    <Page size="A4" style={{ fontFamily: FONT, paddingTop: 54, paddingBottom: 48, paddingHorizontal: 40, color: C.ink, backgroundColor: C.white }}>
      <View fixed style={{ position: "absolute", top: 0, left: 0, right: 0, height: 6, backgroundColor: C.navy }} />
      <View fixed style={{ position: "absolute", top: 20, left: 40, right: 40, flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <View style={{ flexDirection: "row", alignItems: "center" }}>
          <Logo size={4.5} />
          <Text style={{ fontSize: 8, fontWeight: 700, marginLeft: 4 }}>SeenLens</Text>
          <Text style={{ fontSize: 7, color: C.muted, marginLeft: 5 }}>{doc.brand}  •  AI Visibility Report</Text>
        </View>
        <Text style={{ fontSize: 7, color: C.muted }}>Scan #{doc.scan_no}  •  {doc.scan_date}</Text>
      </View>
      {children}
      <View fixed style={{ position: "absolute", bottom: 20, left: 40, right: 40, flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <Text style={{ fontSize: 7, color: C.muted }}>Confidential. Prepared by SeenLens for {doc.brand}.</Text>
        <View style={{ backgroundColor: C.head, borderRadius: 7, paddingVertical: 2.5, paddingHorizontal: 8 }}>
          <Text style={{ fontSize: 6.5, fontWeight: 700, color: C.white }} render={({ pageNumber }) => `Page ${pageNumber}`} />
        </View>
      </View>
    </Page>
  );
}

/* ------------------------------------------------------------------ cover */

function Cover({ doc }: { doc: Doc }) {
  const tiles = [
    ["SCAN DATE", doc.scan_date],
    ["AI ENGINES", doc.engines.length > 2 ? `${doc.engines.length} engines` : doc.engines.join(", ")],
    ["BUYER QUESTIONS", String(doc.questions)],
    ["ANSWERS ANALYSED", `${doc.answers} of ${doc.answers_expected}`],
    ["COMPETITORS", `${doc.competitors} tracked`],
  ];
  const stats: [string, string, string][] = [[pct(doc.you.mention), `of AI answers name ${doc.brand}`, "#F08A8F"]];
  if (doc.leader) stats.push([pct(doc.leader.mention), `name ${doc.leader.name}, the leader`, C.white]);
  stats.push([String(doc.open_count), "buyer questions with no winner", "#F3C773"]);
  return (
    <Page size="A4" style={{ fontFamily: FONT, backgroundColor: C.navyDeep, padding: 0 }}>
      <Svg fixed width={595} height={841} style={{ position: "absolute", top: 0, left: 0 }}>
        <Defs>
          <LinearGradient id="bg" x1="0" y1="0" x2="0.4" y2="1">
            <Stop offset="0" stopColor="#2B3672" />
            <Stop offset="1" stopColor="#121838" />
          </LinearGradient>
        </Defs>
        <Rect x={0} y={0} width={595} height={842} fill="url(#bg)" />
        {[70, 115, 160, 205, 250, 295].map((r) => (
          <Circle key={r} cx={565} cy={150} r={r} stroke="#FFFFFF" strokeOpacity={0.09} strokeWidth={0.8} fill="none" />
        ))}
        <Circle cx={565} cy={150} r={34} fill="#4A5AAE" fillOpacity={0.85} />
        <Circle cx={565} cy={150} r={14} fill="#A9B4F0" />
        <Circle cx={0} cy={760} r={210} fill="#FFFFFF" fillOpacity={0.03} />
      </Svg>
      <View style={{ position: "absolute", top: 38, left: 48, flexDirection: "row", alignItems: "center" }}>
        <Logo size={9} light />
        <Text style={{ fontSize: 15, fontWeight: 700, color: C.white, marginLeft: 6 }}>SeenLens</Text>
        <Text style={{ fontSize: 8, color: C.lilac, marginLeft: 8 }}>AI Visibility Intelligence</Text>
      </View>
      <View style={{ position: "absolute", top: 240, left: 48, right: 48 }}>
        <View style={{ alignSelf: "flex-start", border: `0.8 solid ${C.lilac}`, borderRadius: 10, paddingVertical: 4, paddingHorizontal: 26 }}>
          <Text style={{ fontSize: 7, fontWeight: 700, color: C.white, letterSpacing: 0.4 }}>AI VISIBILITY REPORT</Text>
        </View>
        <Text style={{ fontSize: 52, fontWeight: 700, color: C.white, marginTop: 16, letterSpacing: -1 }}>{doc.brand}</Text>
        <Text style={{ fontSize: 15, color: "#C9CFEE", marginTop: 6, width: 380, lineHeight: 1.3 }}>
          How AI assistants answer your buyers' questions about {doc.category} in {doc.country}.
        </Text>
        <Text style={{ fontSize: 8, color: C.lilac, marginTop: 14 }}>
          {[doc.website, doc.category, `Market: ${doc.country}`, `Scan #${doc.scan_no}${doc.baseline ? " (baseline)" : ""}`].filter(Boolean).join("   •   ")}
        </Text>
      </View>
      <View style={{ position: "absolute", top: 588, left: 48, right: 48, flexDirection: "row", justifyContent: "space-between" }}>
        {tiles.map(([label, value]) => (
          <View key={label} style={{ width: 93, backgroundColor: "#FFFFFF14", borderRadius: 6, borderTop: `3 solid ${C.lilac}`, padding: 10 }}>
            <Text style={{ fontSize: 5.5, fontWeight: 700, color: "#C9CFEE" }}>{label}</Text>
            <Text style={{ fontSize: 11, fontWeight: 700, color: C.white, marginTop: 8 }}>{value}</Text>
          </View>
        ))}
      </View>
      <View style={{ position: "absolute", top: 673, left: 48, right: 48, flexDirection: "row", backgroundColor: "#FFFFFF12", borderRadius: 8, paddingVertical: 12 }}>
        {stats.map(([big, label, color], i) => (
          <View key={label} style={{ flex: 1, paddingHorizontal: 18, borderLeft: i ? "0.6 solid #FFFFFF30" : "none" }}>
            <Text style={{ fontSize: 22, fontWeight: 700, color }}>{big}</Text>
            <Text style={{ fontSize: 7.5, color: "#C9CFEE", marginTop: 2 }}>{label}</Text>
          </View>
        ))}
      </View>
      <View style={{ position: "absolute", bottom: 40, left: 48, right: 48, flexDirection: "row", justifyContent: "space-between" }}>
        <Text style={{ fontSize: 7, color: C.lilac }}>Confidential. Prepared by SeenLens for {doc.brand}.</Text>
        <Text style={{ fontSize: 7, color: C.lilac }}>Generated {doc.generated}</Text>
      </View>
    </Page>
  );
}

/* --------------------------------------------------------------- contents */

function Contents({ doc }: { doc: Doc }) {
  return (
    <Shell doc={doc}>
      <Text style={{ fontSize: 7.5, fontWeight: 700, color: C.head }}>INDEX</Text>
      <Text style={{ fontSize: 26, fontWeight: 700, marginTop: 2 }}>Contents</Text>
      <Text style={{ fontSize: 8.5, color: C.muted, marginTop: 3, marginBottom: 12 }}>
        Eleven sections, from a one-page summary to the full data and method.
      </Text>
      {doc.toc.map((t, i) => (
        <View key={t.n} style={{ flexDirection: "row", height: 46, marginBottom: 6, backgroundColor: C.softBlue, borderRadius: 6, overflow: "hidden" }}>
          <View style={{ width: 54, backgroundColor: i === doc.toc.length - 1 ? "#4C5470" : C.head, alignItems: "center", justifyContent: "center" }}>
            <Text style={{ fontSize: 17, fontWeight: 700, color: C.white }}>{t.n}</Text>
          </View>
          <View style={{ flex: 1, justifyContent: "center", paddingLeft: 16 }}>
            <Text style={{ fontSize: 11, fontWeight: 700 }}>{t.title}</Text>
            <Text style={{ fontSize: 7.5, color: C.ink2, marginTop: 2 }}>{t.desc}</Text>
          </View>
          <View style={{ width: 50, alignItems: "center", justifyContent: "center" }}>
            <View style={{ width: 26, height: 26, borderRadius: 13, backgroundColor: C.white, alignItems: "center", justifyContent: "center" }}>
              <Text style={{ fontSize: 8, fontWeight: 700, color: C.head }}>{t.page}</Text>
            </View>
          </View>
        </View>
      ))}
      <View style={{ flexDirection: "row", backgroundColor: C.navy, borderRadius: 6, paddingVertical: 12, marginTop: 14 }}>
        {[
          ["ENGINES", String(doc.engines.length)],
          ["QUESTIONS", String(doc.questions)],
          ["BRANDS TRACKED", String(doc.competitors + 1)],
          ["MARKET", doc.country],
          ["SCAN", `#${doc.scan_no}${doc.baseline ? " baseline" : ""}`],
        ].map(([k, v]) => (
          <View key={k} style={{ flex: 1, alignItems: "center" }}>
            <Text style={{ fontSize: 5.5, fontWeight: 700, color: C.lilac }}>{k}</Text>
            <Text style={{ fontSize: 11, fontWeight: 700, color: C.white, marginTop: 4 }}>{v}</Text>
          </View>
        ))}
      </View>
    </Shell>
  );
}

/* ------------------------------------------------------- 00 exec summary */

function ShareOfVoice({ brands, size }: { brands: Brand[]; size: number }) {
  const sorted = [...brands].sort((a, b) => b.sov - a.sov);
  const top = sorted[0];
  return (
    <View style={{ flexDirection: "row", alignItems: "center" }}>
      <Donut size={size} thickness={size * 0.17} segments={sorted.map((b) => ({ value: b.sov, color: b.color }))} center={pct(top?.sov)} sub={top?.name} />
      <View style={{ marginLeft: 14, flex: 1 }}>
        {sorted.map((b) => (
          <View key={b.name} style={{ flexDirection: "row", alignItems: "center", marginBottom: 5 }}>
            <View style={{ width: 7, height: 7, borderRadius: 2, backgroundColor: b.color, marginRight: 5 }} />
            <Text style={{ fontSize: 7.5, flex: 1, fontWeight: b.is_you ? 700 : 400 }}>{b.name}{b.is_you ? " (you)" : ""}</Text>
            <Text style={{ fontSize: 7.5, fontWeight: 700, color: b.color }}>{pct(b.sov)}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

function Summary({ doc }: { doc: Doc }) {
  const of = (rate: number) => `${Math.round(rate * doc.answers)} of ${doc.answers} answers`;
  const tiles = [
    { label: "MENTIONED", value: pct(doc.you.mention), sub: `${of(doc.you.mention)}\n95% range ${doc.metrics[0].range}`, color: C.you },
    { label: "RECOMMENDED", value: pct(doc.you.recommend), sub: `${of(doc.you.recommend)}\n95% range ${doc.metrics[1].range}`, color: C.head },
    doc.leader
      ? { label: `LEADER (${doc.leader.name.toUpperCase()})`, value: pct(doc.leader.recommend), sub: `recommended in\n${of(doc.leader.recommend)}`, color: C.good }
      : { label: "COMPETITORS", value: "0", sub: "none tracked", color: C.good },
    { label: "OPEN QUESTIONS", value: String(doc.open_count), sub: "questions where AI\nrecommended no one", color: C.amber },
  ];
  const maxScore = Math.max(1, ...doc.by_score.map((b) => b.score));
  return (
    <Shell doc={doc}>
      <SectionHead n="00" title="Executive summary" lead={`The short version for founders and marketing leads: where ${doc.brand} stands in AI answers today, and the single most valuable thing to fix first.`} />
      <Text style={{ fontSize: 7, color: C.muted, marginBottom: 8 }}>{doc.estimate_note}</Text>
      <View style={{ flexDirection: "row" }}>
        <Card dark style={{ width: 150, alignItems: "center", paddingVertical: 14 }}>
          <Text style={{ fontSize: 7, fontWeight: 700, color: "#C9CFEE" }}>AI VISIBILITY SCORE (ESTIMATE)</Text>
          <View style={{ marginTop: 10 }}><Gauge value={doc.score} size={120} /></View>
          <Text style={{ fontSize: 30, fontWeight: 700, color: C.white, marginTop: -30 }}>{doc.score}</Text>
          <Text style={{ fontSize: 7, color: "#C9CFEE" }}>out of 100</Text>
          <View style={{ marginTop: 6 }}>
            <Pill label={doc.score_label} color={doc.score < 10 ? C.you : doc.score < 30 ? C.amber : C.good} width={80} />
          </View>
        </Card>
        <View style={{ flex: 1, marginLeft: 14 }}>
          {doc.summary.map((s) => (
            <Text key={s.lead} style={{ fontSize: 8.5, color: C.ink2, lineHeight: 1.5, marginBottom: 6 }}>
              <Text style={{ fontWeight: 700, color: C.ink }}>{s.lead} </Text>{s.body}
            </Text>
          ))}
        </View>
      </View>
      <View style={{ flexDirection: "row", justifyContent: "space-between", marginTop: 10 }}>
        {tiles.map((t) => (
          <View key={t.label} style={{ width: 122, border: `0.75 solid ${C.line}`, borderTop: `3 solid ${t.color}`, borderRadius: 6, padding: 9 }}>
            <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
              <Text style={{ fontSize: 6, fontWeight: 700, color: C.ink2, width: 80 }}>{t.label}</Text>
              <View style={{ width: 12, height: 12, borderRadius: 6, backgroundColor: t.color }} />
            </View>
            <Text style={{ fontSize: 20, fontWeight: 700, color: t.color, marginTop: 6 }}>{t.value}</Text>
            <Text style={{ fontSize: 6.5, color: C.ink2, marginTop: 2, lineHeight: 1.35 }}>{t.sub}</Text>
          </View>
        ))}
      </View>
      <View style={{ flexDirection: "row", marginTop: 10 }}>
        <Card style={{ flex: 1, marginRight: 8 }}>
          <CardTitle title="Share of voice" sub="Each brand's slice of all brand picks" />
          <ShareOfVoice brands={doc.brands} size={92} />
        </Card>
        <Card style={{ flex: 1 }}>
          <CardTitle title="Visibility score by brand (estimate)" sub="0–100, higher means AI names and picks the brand more" />
          {doc.by_score.slice(0, 5).map((b) => (
            <View key={b.name} style={{ flexDirection: "row", alignItems: "center", marginBottom: 7 }}>
              <Text style={{ fontSize: 7.5, width: 62, textAlign: "right", marginRight: 8, color: b.is_you ? C.you : C.ink, fontWeight: b.is_you ? 700 : 400 }}>{b.name}</Text>
              <Bar value={b.score} max={maxScore} color={b.color} width={130} height={10} />
              <Text style={{ fontSize: 7.5, fontWeight: 700, color: b.color, marginLeft: 6 }}>{b.score}</Text>
            </View>
          ))}
        </Card>
      </View>
      <H2>Findings that matter</H2>
      {doc.findings.map((f) => (
        <View key={f.lead} style={{ flexDirection: "row", marginBottom: 4 }}>
          <Text style={{ fontSize: 8.5, width: 10 }}>•</Text>
          <Text style={{ fontSize: 8.5, color: C.ink2, lineHeight: 1.45, flex: 1 }}>
            <Text style={{ fontWeight: 700, color: C.ink }}>{f.lead} </Text>{f.body}
          </Text>
        </View>
      ))}
      {doc.do_first ? <Callout tone="good" title="Do this first">{`${doc.do_first.title}. ${doc.do_first.detail}`}</Callout> : null}
    </Shell>
  );
}

/* ------------------------------------------------------ 01 where you stand */

type Metric = Doc["metrics"][number];

function Standing({ doc }: { doc: Doc }) {
  const withDelta = doc.metrics.some((m) => m.delta != null);
  const cols: Col<Metric>[] = [
    { title: "Metric", width: "20%", render: (m) => m.name, style: { fontWeight: 700 } },
    { title: doc.brand, width: "13%", render: (m) => m.you, style: { color: C.you, fontWeight: 700 } },
    { title: "95% range", width: "13%", render: (m) => m.range },
    ...(withDelta ? [{ title: "Change", width: "11%", render: (m: Metric) => (m.delta == null ? "–" : `${m.delta > 0 ? "+" : ""}${Math.round(m.delta * 100)} pts`) }] : []),
    { title: "Leader", width: "17%", render: (m) => m.leader },
    { title: "What it measures", width: withDelta ? "26%" : "37%", render: (m) => m.measures, style: { color: C.ink2 } },
  ];
  return (
    <Shell doc={doc}>
      <SectionHead n="01" title="Where you stand" lead={`Each metric is a share of the ${doc.answers} answers collected. The 95% range is an estimate of how far the number could move by chance with a sample this size.`} />
      <Table cols={cols} rows={doc.metrics} />
      <Card style={{ marginTop: 12 }}>
        <View style={{ flexDirection: "row", justifyContent: "space-between", marginBottom: 8 }}>
          <Text style={{ fontSize: 10, fontWeight: 700 }}>Gap to the leader</Text>
          <Legend items={[{ label: doc.brand, color: C.you }, { label: doc.leader?.name ?? "Category leader", color: doc.leader?.color ?? C.good }]} />
        </View>
        {doc.gaps.map((g) => (
          <View key={g.name} style={{ flexDirection: "row", alignItems: "center", marginBottom: 9 }}>
            <Text style={{ fontSize: 8, width: 110, textAlign: "right", marginRight: 10 }}>{g.name}</Text>
            <View>
              <View style={{ flexDirection: "row", alignItems: "center" }}>
                <Bar value={g.leader} color={doc.leader?.color ?? C.good} width={300} height={8} track={C.soft} />
                <Text style={{ fontSize: 7, fontWeight: 700, color: doc.leader?.color ?? C.good, marginLeft: 5 }}>{pct(g.leader)}</Text>
              </View>
              <View style={{ flexDirection: "row", alignItems: "center", marginTop: 2 }}>
                <Bar value={g.you} color={C.you} width={300} height={8} track={C.soft} />
                <Text style={{ fontSize: 7, fontWeight: 700, color: C.you, marginLeft: 5 }}>{pct(g.you)}</Text>
              </View>
            </View>
          </View>
        ))}
      </Card>
      <Callout title="How to read the ranges">
        {`With ${doc.answers} answers, ${doc.brand}'s recommendation rate of ${pct(doc.you.recommend)} could truly be anywhere in ${doc.metrics[1].range}. A change smaller than that range between two scans may be normal variation.`}
      </Callout>
      <H2>Results by AI engine</H2>
      <Table
        cols={[
          { title: "Engine", width: "22%", render: (e) => e.name, style: { fontWeight: 700 } },
          { title: "Type", width: "26%", render: (e) => e.type, style: { color: C.ink2 } },
          { title: "Answers", width: "13%", render: (e) => (e.scanned ? String(e.answers) : <Text style={{ fontSize: 7, color: C.amberInk, fontWeight: 700 }}>Add next scan</Text>) },
          { title: "Mentioned", width: "13%", render: (e) => (e.scanned ? e.mention ?? "–" : "") },
          { title: "Recommended", width: "14%", render: (e) => (e.scanned ? e.recommend ?? "–" : "") },
          { title: "Cited", width: "12%", render: (e) => (e.scanned ? e.cited ?? "–" : "") },
        ]}
        rows={doc.engine_rows}
      />
      {doc.engine_rows.some((e) => !e.scanned) ? (
        <Text style={{ fontSize: 7, color: C.muted, marginTop: 4 }}>Engines marked "Add next scan" were not part of this scan. Web-search engines show which websites drive recommendations.</Text>
      ) : null}
    </Shell>
  );
}

/* ---------------------------------------------------- 02 who instead */

function Instead({ doc }: { doc: Doc }) {
  const brands = [...doc.brands.filter((b) => !b.is_you).slice(0, 5), doc.you];
  const chartH = 120;
  const slot = (W - 64) / brands.length;
  const rows = [...doc.brands].sort((a, b) => b.wins - a.wins).map((b) => ({ name: b.name, n: b.wins, color: b.color }));
  rows.push({ name: "No one (open)", n: doc.open_count, color: C.amber });
  const dots = Math.min(Math.max(doc.questions, 1), 40);
  return (
    <Shell doc={doc}>
      <SectionHead n="02" title="Who AI recommends instead" lead={`Every tracked brand across the same ${doc.answers} answers. Mentioned means the name appears; recommended means the answer suggests it as a pick.`} />
      <Card>
        <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
          <CardTitle title="Mentioned vs recommended, by brand" sub={`Share of ${doc.answers} answers`} />
          <Text style={{ fontSize: 7, color: C.muted }}>Solid = mentioned   Light = recommended</Text>
        </View>
        <Svg width={W - 26} height={chartH + 34}>
          {[0, 0.25, 0.5, 0.75, 1].map((t) => (
            <React.Fragment key={t}>
              <Path d={`M 30 ${10 + chartH * (1 - t)} L ${W - 30} ${10 + chartH * (1 - t)}`} stroke={C.line} strokeWidth={0.6} />
              <Text x={0} y={13 + chartH * (1 - t)} style={{ fontSize: 6, fill: C.muted }}>{`${t * 100}%`}</Text>
            </React.Fragment>
          ))}
          {brands.map((b, i) => {
            const x = 40 + i * slot + slot / 2 - 32;
            const h1 = Math.max(1.5, b.mention * chartH);
            const h2 = Math.max(1.5, b.recommend * chartH);
            return (
              <React.Fragment key={b.name}>
                <Rect x={x} y={10 + chartH - h1} width={30} height={h1} rx={3} fill={b.color} />
                <Rect x={x + 34} y={10 + chartH - h2} width={30} height={h2} rx={3} fill={b.color} fillOpacity={0.45} />
                <Text x={x + 15} y={6 + chartH - h1} textAnchor="middle" style={{ fontSize: 6.5, fontWeight: 700, fill: C.ink }}>{pct(b.mention)}</Text>
                <Text x={x + 49} y={6 + chartH - h2} textAnchor="middle" style={{ fontSize: 6.5, fontWeight: 700, fill: C.ink }}>{pct(b.recommend)}</Text>
                <Text x={x + 32} y={chartH + 26} textAnchor="middle" style={{ fontSize: 7.5, fill: b.is_you ? C.you : C.ink, fontWeight: b.is_you ? 700 : 400 }}>{b.is_you ? `${b.name} (you)` : b.name}</Text>
              </React.Fragment>
            );
          })}
        </Svg>
      </Card>
      <View style={{ marginTop: 10 }}>
        <Table
          cols={[
            { title: "Brand", width: "20%", render: (b: Brand) => (b.is_you ? `${b.name} (you)` : b.name), style: { fontWeight: 700 } },
            { title: "Mentioned", width: "13%", render: (b: Brand) => pct(b.mention) },
            { title: "Recommended", width: "15%", render: (b: Brand) => pct(b.recommend) },
            { title: "95% range", width: "14%", render: (b: Brand) => b.range },
            { title: "Avg. rank", width: "12%", render: (b: Brand) => (b.avg_rank ? b.avg_rank.toFixed(1) : "–") },
            { title: "Share of voice", width: "15%", render: (b: Brand) => pct(b.sov) },
            { title: "Score", width: "11%", render: (b: Brand) => String(b.score), style: { fontWeight: 700 } },
          ]}
          rows={doc.by_score}
          highlight={(b) => b.is_you}
        />
      </View>
      <View style={{ flexDirection: "row", marginTop: 10 }}>
        <Card style={{ flex: 1, marginRight: 8 }}>
          <CardTitle title={`Questions won (of ${doc.questions})`} sub="A question can have more than one winner" />
          {rows.slice(0, 6).map((r) => (
            <View key={r.name} style={{ flexDirection: "row", alignItems: "center", marginBottom: 6 }}>
              <Text style={{ fontSize: 7.5, width: 62, textAlign: "right", marginRight: 6 }}>{r.name}</Text>
              <Svg width={130} height={6}>
                {Array.from({ length: dots }, (_, i) => (
                  <Circle key={i} cx={3 + i * (127 / dots)} cy={3} r={2.2} fill={i < Math.round((r.n / Math.max(doc.questions, 1)) * dots) ? r.color : C.line} />
                ))}
              </Svg>
              <Text style={{ fontSize: 7.5, fontWeight: 700, color: r.color, marginLeft: 6 }}>{r.n}</Text>
            </View>
          ))}
        </Card>
        <Card style={{ flex: 1 }}>
          <CardTitle title="Share of voice" sub="Each brand's slice of all brand picks" />
          <ShareOfVoice brands={doc.brands} size={92} />
        </Card>
      </View>
    </Shell>
  );
}

/* ------------------------------------------------------- 03 buying stage */

function Stages({ doc }: { doc: Doc }) {
  const max = Math.max(1, ...doc.stages.map((s) => s.count));
  const names = Array.from(new Set(doc.stages.flatMap((s) => s.segments.map((x) => x.name))));
  const colorOf = Object.fromEntries(doc.stages.flatMap((s) => s.segments.map((x) => [x.name, x.color])));
  const locked = doc.stages.filter((s) => s.open === 0).map((s) => s.label);
  const mostOpen = [...doc.stages].sort((a, b) => b.open / b.count - a.open / a.count)[0];
  const cardW = (W - 8 * Math.max(doc.stages.length - 1, 0)) / Math.max(doc.stages.length, 1);
  return (
    <Shell doc={doc}>
      <SectionHead n="03" title="Results by buying stage" lead="Questions are grouped by where the buyer is in their journey. This shows where AI already has a favourite and where the answer is still open." />
      <Card>
        <CardTitle title="Who wins at each buying stage" sub="Each question counted once, under the first brand AI picked" />
        <Legend items={names.map((n) => ({ label: n === "Open" ? "No brand picked (open)" : n === doc.brand ? `${n} (you)` : n, color: colorOf[n] }))} />
        <View style={{ marginTop: 10 }}>
          {doc.stages.map((s) => (
            <View key={s.key} style={{ flexDirection: "row", alignItems: "center", marginBottom: 8 }}>
              <View style={{ width: 7, height: 7, borderRadius: 4, backgroundColor: s.color, marginRight: 5 }} />
              <Text style={{ fontSize: 8, width: 80 }}>{s.label} ({s.count})</Text>
              <View style={{ flexDirection: "row" }}>
                {s.segments.map((seg) => (
                  <View key={seg.name} style={{ width: (seg.count / max) * 360, height: 16, backgroundColor: seg.color, borderRadius: 3, marginRight: 2, alignItems: "center", justifyContent: "center" }}>
                    <Text style={{ fontSize: 7, fontWeight: 700, color: C.white }}>{seg.count}</Text>
                  </View>
                ))}
              </View>
            </View>
          ))}
        </View>
      </Card>
      <View style={{ flexDirection: "row", justifyContent: "space-between", marginTop: 10 }}>
        {doc.stages.map((s) => (
          <Card key={s.key} style={{ width: cardW, alignItems: "center", padding: 8 }}>
            <Text style={{ fontSize: 8, fontWeight: 700, marginBottom: 6 }}>{s.label}</Text>
            <Donut size={58} thickness={9} segments={[{ value: s.open, color: C.amber }, { value: s.count - s.open, color: s.color }]} center={`${s.open}/${s.count}`} sub="open" />
            <Text style={{ fontSize: 6.5, color: C.muted, marginTop: 6 }}>{pct(s.open / s.count)} unclaimed</Text>
          </Card>
        ))}
      </View>
      <View style={{ marginTop: 10 }}>
        <Table
          cols={[
            { title: "Stage", width: "16%", render: (s: Stage) => s.label, style: { fontWeight: 700 } },
            { title: "What the buyer asks", width: "48%", render: (s: Stage) => s.desc, style: { color: C.ink2 } },
            { title: "Questions", width: "12%", render: (s: Stage) => String(s.count) },
            { title: doc.brand, width: "12%", render: (s: Stage) => String(s.you), style: { color: C.you, fontWeight: 700 } },
            { title: "Open", width: "12%", render: (s: Stage) => String(s.open), style: { color: C.amberInk, fontWeight: 700 } },
          ]}
          rows={doc.stages}
        />
      </View>
      <Callout title="What this tells you">
        {(locked.length && locked.length < doc.stages.length ? `${locked.join(", ")} questions have a pick on every question. ` : "")
          + (mostOpen && mostOpen.open
            ? `${mostOpen.label} questions are the most open (${mostOpen.open} of ${mostOpen.count} have no pick). Start there: these buyers have not been told which option to choose yet.`
            : "Every stage has a favourite, so gains will come from displacing the brand AI picks today.")}
      </Callout>
    </Shell>
  );
}

/* --------------------------------------------------- 04 open opportunities */

function Opportunities({ doc }: { doc: Doc }) {
  const share = doc.questions ? doc.open_count / doc.questions : 0;
  return (
    <Shell doc={doc}>
      <SectionHead n="04" title="Open opportunities" lead={`In these ${doc.open_count} questions AI gave general advice but recommended no brand. Nobody owns them yet, so a clear, well-sourced answer from ${doc.brand} has the best chance of being picked up.`} />
      <View wrap={false} style={{ flexDirection: "row", alignItems: "center", backgroundColor: C.amberSoft, borderRadius: 8, padding: 16 }}>
        <Donut size={110} thickness={20} segments={[{ value: doc.open_count, color: C.amber }, { value: doc.questions - doc.open_count, color: "#CBD3E1" }]} center={String(doc.open_count)} sub={`of ${doc.questions} open`} track="#CBD3E1" />
        <View style={{ marginLeft: 20, flex: 1 }}>
          <Text style={{ fontSize: 7, fontWeight: 700, color: C.amberInk }}>UNCLAIMED QUESTIONS</Text>
          <Text style={{ fontSize: 16, fontWeight: 700, marginTop: 4, lineHeight: 1.2 }}>{pct(share)} of buyer questions have no recommended brand</Text>
          <Text style={{ fontSize: 8, color: C.ink2, marginTop: 6, lineHeight: 1.45 }}>
            {doc.open_count
              ? `These are the easiest questions for ${doc.brand} to win, because no competitor needs to be displaced.`
              : "AI picked a brand on every question in this scan, so each win means taking a pick from a competitor."}
          </Text>
        </View>
      </View>
      {doc.open_rows.length ? (
        <View style={{ marginTop: 10 }}>
          <Table
            cols={[
              { title: "Q#", width: "6%", render: (r: QuestionRow) => String(r.n), style: { fontWeight: 700 } },
              { title: "Open question", width: "44%", render: (r: QuestionRow) => r.text },
              { title: "Stage", width: "13%", render: (r: QuestionRow) => doc.stage_labels[r.stage] },
              { title: "Why it fits", width: "24%", render: (r: QuestionRow) => r.why ?? "", style: { color: C.ink2 } },
              { title: "Priority", width: "13%", render: (r: QuestionRow) => <Pill label={r.priority ?? ""} color={r.priority === "HIGH" ? C.good : C.amber} /> },
            ]}
            rows={doc.open_rows}
          />
          {doc.open_more ? <Text style={{ fontSize: 7, color: C.muted, marginTop: 4 }}>And {doc.open_more} more open questions, listed in Section 05.</Text> : null}
        </View>
      ) : null}
      <Callout tone="warn" title="Check before publishing">
        {`Fit is judged from the wording of each question. Confirm each one matches what ${doc.brand} actually offers before writing the page.`}
      </Callout>
    </Shell>
  );
}

/* ------------------------------------------------- 05 question by question */

function Questions({ doc }: { doc: Doc }) {
  const brands = doc.grid_brands;
  const qWidth = W - 20 - 56 - 50 * (brands.length + 1) - 8;
  return (
    <Shell doc={doc}>
      <SectionHead n="05" title="Question-by-question results" lead={`All ${doc.questions} buyer questions, each asked in a fresh chat. Coloured cells show which brands were picked.`} />
      <View fixed style={{ flexDirection: "row", backgroundColor: C.head, paddingVertical: 5, paddingHorizontal: 4 }}>
        <Text style={{ width: 20, fontSize: 6.5, fontWeight: 700, color: C.white }}>#</Text>
        <Text style={{ width: qWidth, fontSize: 6.5, fontWeight: 700, color: C.white }}>BUYER QUESTION</Text>
        <Text style={{ width: 56, fontSize: 6.5, fontWeight: 700, color: C.white }}>STAGE</Text>
        {[doc.brand, ...brands.map((b) => b.name)].map((n) => (
          <Text key={n} style={{ width: 50, fontSize: 6, fontWeight: 700, color: C.white, textAlign: "center" }}>{n.toUpperCase().slice(0, 11)}</Text>
        ))}
      </View>
      {doc.question_rows.map((r, i) => (
        <View key={r.n} wrap={false} style={{ flexDirection: "row", alignItems: "center", minHeight: 18, paddingRight: 4, borderBottom: `0.5 solid ${C.line}`, backgroundColor: i % 2 ? C.soft : C.white }}>
          <View style={{ width: 24, alignSelf: "stretch", justifyContent: "center", backgroundColor: r.open ? C.amber : "transparent", paddingLeft: 4 }}>
            <Text style={{ fontSize: 7, fontWeight: 700, color: r.open ? C.white : C.ink }}>{r.n}</Text>
          </View>
          <Text style={{ width: qWidth, fontSize: 6.8, lineHeight: 1.25, paddingVertical: 2, paddingRight: 6 }}>{r.text}</Text>
          <Text style={{ width: 56, fontSize: 6.5, color: C.ink2 }}>{doc.stage_labels[r.stage]}</Text>
          <View style={{ width: 50, paddingHorizontal: 2, alignSelf: "stretch", justifyContent: "center", backgroundColor: r.you === "PICKED" ? "transparent" : C.youSoft }}>
            {r.you === "PICKED" ? <Pill label="PICKED" color={C.you} />
              : <Text style={{ fontSize: 6.5, fontWeight: 700, color: C.you, textAlign: "center" }}>{r.you}</Text>}
          </View>
          {brands.map((b) => (
            <View key={b.name} style={{ width: 50, paddingHorizontal: 2 }}>
              {r.picked.includes(b.name) ? <Pill label="PICKED" color={b.color} /> : <Text style={{ fontSize: 7, color: C.muted, textAlign: "center" }}>–</Text>}
            </View>
          ))}
        </View>
      ))}
      <View style={{ marginTop: 6 }}>
        <Legend items={[{ label: "Picked by AI (brand colour)", color: C.head }, { label: `${doc.brand} missing or only named`, color: C.you }, { label: "Amber number = open question", color: C.amber }]} />
      </View>
    </Shell>
  );
}

/* ------------------------------------------------ 06 why competitors win */

type Claim = Doc["claims"][number];

function Why({ doc }: { doc: Doc }) {
  const rivals = doc.competitor_why;
  const chartW = 250;
  const chartH = 80;
  const maxWins = Math.max(1, ...doc.stages.flatMap((s) => rivals.map((r) => s.wins[r.name] ?? 0)));
  const group = (chartW - 20) / Math.max(doc.stages.length, 1);
  const barW = Math.min(12, (group - 8) / Math.max(rivals.length, 1));
  const [leader, ...others] = rivals;
  return (
    <Shell doc={doc}>
      <SectionHead n="06" title="Why AI picks your competitors" lead={`The reasons AI gave when it recommended a competitor. These are the claims ${doc.brand}'s pages need to match or beat, in plain, checkable words.`} />
      {!leader ? <Callout tone="good" title="No competitor was picked over you">AI did not recommend a tracked competitor on any question in this scan.</Callout> : null}
      {rivals.map((r) => (
        <View key={r.name} wrap={false} style={{ marginBottom: 8 }}>
          <View style={{ backgroundColor: r.color, paddingVertical: 5, paddingHorizontal: 8, flexDirection: "row", alignItems: "flex-end" }}>
            <Text style={{ fontSize: 11, fontWeight: 700, color: C.white }}>{r.name}</Text>
            <Text style={{ fontSize: 7.5, color: C.white, marginLeft: 5, marginBottom: 1 }}>{r.wins} wins</Text>
          </View>
          {r.items.map((it, i) => (
            <View key={it.title} style={{ flexDirection: "row", paddingVertical: 4, paddingHorizontal: 8, backgroundColor: i % 2 ? C.white : C.soft }}>
              <Text style={{ fontSize: 8, fontWeight: 700, width: "42%", paddingRight: 8 }}>{it.title}</Text>
              <Text style={{ fontSize: 8, color: C.ink2, flex: 1 }}>{it.detail}</Text>
            </View>
          ))}
          {r.quote ? (
            <View style={{ flexDirection: "row", paddingVertical: 4, paddingHorizontal: 8, backgroundColor: C.softBlue }}>
              <Text style={{ fontSize: 7, color: C.muted, width: "42%" }}>From the AI answer</Text>
              <Text style={{ fontSize: 8, color: C.ink2, flex: 1 }}>"{r.quote.slice(0, 220)}{r.quote.length > 220 ? "…" : ""}"</Text>
            </View>
          ) : null}
        </View>
      ))}
      {leader ? (
        <View wrap={false} style={{ flexDirection: "row", marginTop: 4 }}>
          <Card style={{ width: chartW + 24, marginRight: 8 }}>
            <CardTitle title="Where each competitor wins" />
            <Legend items={rivals.map((r) => ({ label: r.name, color: r.color }))} />
            <Svg width={chartW} height={chartH + 22} style={{ marginTop: 6 }}>
              <Path d={`M 10 ${chartH} L ${chartW} ${chartH}`} stroke={C.line} strokeWidth={0.6} />
              {doc.stages.map((s, gi) => (
                <React.Fragment key={s.key}>
                  {rivals.map((r, ri) => {
                    const v = s.wins[r.name] ?? 0;
                    const h = (v / maxWins) * (chartH - 12);
                    const x = 14 + gi * group + ri * (barW + 1);
                    return (
                      <React.Fragment key={r.name}>
                        <Rect x={x} y={chartH - h} width={barW} height={Math.max(h, 0.5)} rx={1.5} fill={r.color} />
                        {v ? <Text x={x + barW / 2} y={chartH - h - 2} textAnchor="middle" style={{ fontSize: 5.5, fontWeight: 700, fill: C.ink }}>{String(v)}</Text> : null}
                      </React.Fragment>
                    );
                  })}
                  <Text x={14 + gi * group + (rivals.length * (barW + 1)) / 2} y={chartH + 12} textAnchor="middle" style={{ fontSize: 6, fontWeight: 700, fill: s.color }}>{s.label}</Text>
                </React.Fragment>
              ))}
            </Svg>
          </Card>
          <Callout tone="good" title="Pattern to notice" style={{ flex: 1, marginTop: 0, alignSelf: "flex-start" }}>
            {`${leader.name} wins ${leader.wins} of ${doc.questions} questions. ${others.length ? `${others.map((r) => r.name).join(" and ")} win${others.length === 1 ? "s" : ""} where ${others.length === 1 ? "its" : "their"} specific features come up. ` : ""}A clear, repeated feature claim is what earns a pick.`}
          </Callout>
        </View>
      ) : null}
      <Callout tone="good" title={`What ${doc.brand} needs AI to learn`}>
        {`A one-line description AI can repeat, used the same way everywhere (website, app stores, press, social). For example: "${doc.brand} is a ${doc.category} that helps … do …". Fill it in with your real features and keep it identical on every page.`}
      </Callout>
      {doc.claims.length ? (
        <View wrap={false}>
          <H2>{`Claim checklist: does ${doc.brand}'s website say this clearly?`}</H2>
          <Table
            cols={[
              { title: "Claim AI rewards", width: "38%", render: (c: Claim) => c.claim, style: { fontWeight: 700 } },
              { title: "Competitor", width: "17%", render: (c: Claim) => c.competitor },
              { title: `${doc.brand} page that should say it`, width: "30%", render: (c: Claim) => c.page },
              { title: "Status", width: "15%", render: () => "To check", style: { color: C.amberInk, fontWeight: 700 } },
            ]}
            rows={doc.claims}
          />
        </View>
      ) : null}
    </Shell>
  );
}

/* ------------------------------------------------------------ 07 sources */

const SOURCE_TYPES = [
  { label: "Your website", color: "#3B6FD8", why: "The source you fully control", step: "FAQ, comparison and feature pages with clear answers" },
  { label: "Review and listing sites", color: "#2E9BD6", why: "Often used to describe and rank brands", step: "Complete and refresh your profiles" },
  { label: "\"Best of\" articles", color: "#8B5CF6", why: "Common source for list questions", step: "Pitch 5–10 relevant publications" },
  { label: "Reddit & forums", color: "#E07A2E", why: "Real user opinions", step: "Answer questions honestly in relevant threads" },
  { label: "YouTube reviews", color: "#D9488B", why: "Strong for beginner audiences", step: "Partner with 2–3 creators in your niche" },
  { label: "News & press", color: "#14A3A3", why: "Builds brand authority", step: "Announce milestones, funding or launches" },
];
type SourceType = (typeof SOURCE_TYPES)[number];
type Source = Doc["sources"][number];

function Sources({ doc }: { doc: Doc }) {
  const boxY = (i: number) => 8 + i * 36;
  return (
    <Shell doc={doc}>
      <SectionHead n="07" title="Sources AI trusts" lead="Which websites AI engines cite when answering. Being present on these sites is one of the strongest levers for being recommended." />
      {doc.sources.length ? (
        <Table
          cols={[
            { title: "Website", width: "34%", render: (s: Source) => s.domain, style: { fontWeight: 700 } },
            { title: "Citations", width: "14%", render: (s: Source) => String(s.citations) },
            { title: `With ${doc.brand} named`, width: "20%", render: (s: Source) => String(s.with_you), style: { color: C.you, fontWeight: 700 } },
            { title: "Owner", width: "16%", render: (s: Source) => s.owner ?? "Independent" },
            { title: "Type", width: "16%", render: (s: Source) => (s.source_type ?? "–").replace(/_/g, " "), style: { color: C.ink2 } },
          ]}
          rows={doc.sources}
          dense
        />
      ) : (
        <Callout title="No sources were cited in this scan">
          The engines in this scan answered from what they learned in training, so they cited no websites. Adding web-search engines (Perplexity, Gemini, ChatGPT Search, Google AI Mode) shows exactly which pages drive picks.
        </Callout>
      )}
      <Card style={{ marginTop: 10 }}>
        <CardTitle title="How AI learns which brand to recommend" />
        <Svg width={W - 26} height={222}>
          {SOURCE_TYPES.map((s, i) => (
            <React.Fragment key={s.label}>
              <Path d={`M 130 ${boxY(i) + 10} C 175 ${boxY(i) + 10}, 175 80, 215 80`} stroke="#C5CBE0" strokeWidth={0.6} fill="none" />
              <Path d={`M 130 ${boxY(i) + 10} C 175 ${boxY(i) + 10}, 175 140, 215 140`} stroke="#DCE0EC" strokeWidth={0.5} fill="none" />
              <Rect x={0} y={boxY(i)} width={130} height={20} rx={4} fill={s.color} />
              <Text x={8} y={boxY(i) + 13} style={{ fontSize: 7.5, fill: C.white }}>{s.label}</Text>
            </React.Fragment>
          ))}
          <Rect x={215} y={68} width={110} height={24} rx={5} fill={C.navy} />
          <Text x={270} y={83} textAnchor="middle" style={{ fontSize: 7.5, fontWeight: 700, fill: C.white }}>AI model memory</Text>
          <Rect x={215} y={128} width={110} height={24} rx={5} fill={C.head} />
          <Text x={270} y={143} textAnchor="middle" style={{ fontSize: 7.5, fontWeight: 700, fill: C.white }}>Live web search</Text>
          <Text x={270} y={164} textAnchor="middle" style={{ fontSize: 6, fill: C.muted }}>{doc.web_scanned ? "Measured in this scan" : "Not measured in this scan"}</Text>
          <Path d="M 325 80 C 360 80, 360 110, 395 110" stroke={C.navy} strokeWidth={1} fill="none" />
          <Path d="M 325 140 C 360 140, 360 110, 395 110" stroke={C.navy} strokeWidth={1} fill="none" />
          <Rect x={395} y={88} width={92} height={44} rx={6} fill={C.navy} />
          <Text x={441} y={107} textAnchor="middle" style={{ fontSize: 8, fontWeight: 700, fill: C.white }}>AI answer</Text>
          <Text x={441} y={120} textAnchor="middle" style={{ fontSize: 6, fill: "#C9CFEE" }}>"Try this one…"</Text>
        </Svg>
      </Card>
      <H2>Where to be present</H2>
      <Table
        cols={[
          { title: "Source type", width: "22%", render: (s: SourceType) => s.label, style: { fontWeight: 700 } },
          { title: "Why it matters", width: "28%", render: (s: SourceType) => s.why, style: { color: C.ink2 } },
          { title: "First step", width: "36%", render: (s: SourceType) => s.step },
          { title: "Status", width: "14%", render: () => "To check", style: { color: C.amberInk, fontWeight: 700 } },
        ]}
        rows={SOURCE_TYPES}
        dense
      />
    </Shell>
  );
}

/* --------------------------------------------------------- 08 action plan */

const ACTION_COLORS = ["#3B6FD8", "#12A37F", "#2E9BD6", "#8B5CF6", "#14A3A3", "#E07A2E", "#D9488B"];
type Quadrant = "quick" | "big" | "fill" | "avoid";

function Actions({ doc }: { doc: Doc }) {
  const weekW = 18;
  const quadrant = (impact: string, effort: string): Quadrant =>
    impact === "High" ? (effort === "Low" ? "quick" : "big") : effort === "Low" ? "fill" : "avoid";
  const groups: Record<Quadrant, number[]> = { quick: [], big: [], fill: [], avoid: [] };
  doc.actions.forEach((a, i) => groups[quadrant(a.impact, a.effort)].push(i));
  const easy = [...groups.quick, ...groups.fill].map((i) => i + 1).sort((a, b) => a - b);
  const cols: [string, number][] = [["#", 18], ["Action", 270], ["Targets", 80], ["Impact", 50], ["Effort", 45], ["When", 52]];
  return (
    <Shell doc={doc}>
      <SectionHead n="08" title="Action plan" lead={`Ranked by expected impact on how often AI recommends ${doc.brand}. Each action is tied to the questions it targets.`} />
      <View style={{ flexDirection: "row", backgroundColor: C.head, paddingVertical: 5 }}>
        {cols.map(([t, w]) => (
          <Text key={t} style={{ width: w, fontSize: 6.5, fontWeight: 700, color: C.white, paddingLeft: 6 }}>{t.toUpperCase()}</Text>
        ))}
      </View>
      {doc.actions.map((a, i) => (
        <View key={a.title} wrap={false} style={{ flexDirection: "row", borderBottom: `0.5 solid ${C.line}`, backgroundColor: i % 2 ? C.soft : C.white }}>
          <View style={{ width: 18, backgroundColor: ACTION_COLORS[i % 7], alignItems: "center", justifyContent: "center" }}>
            <Text style={{ fontSize: 8, fontWeight: 700, color: C.white }}>{i + 1}</Text>
          </View>
          <View style={{ width: 270, padding: 5 }}>
            <Text style={{ fontSize: 8, fontWeight: 700 }}>{a.title}</Text>
            <Text style={{ fontSize: 7, color: C.ink2, marginTop: 1.5, lineHeight: 1.35 }}>{a.detail}</Text>
          </View>
          <Text style={{ width: 80, fontSize: 7.5, padding: 5, alignSelf: "center" }}>{a.targets}</Text>
          <Text style={{ width: 50, fontSize: 7.5, padding: 5, alignSelf: "center", fontWeight: 700, color: a.impact === "High" ? C.good : C.amberInk }}>{a.impact}</Text>
          <Text style={{ width: 45, fontSize: 7.5, padding: 5, alignSelf: "center" }}>{a.effort}</Text>
          <Text style={{ width: 52, fontSize: 7.5, padding: 5, alignSelf: "center" }}>{a.when}</Text>
        </View>
      ))}
      <View wrap={false} style={{ flexDirection: "row", marginTop: 10 }}>
        <Card style={{ width: 330, marginRight: 8 }}>
          <CardTitle title="90-day roadmap (weeks)" />
          <View style={{ flexDirection: "row", marginLeft: 96 }}>
            {["MONTH 1", "MONTH 2", "MONTH 3"].map((m) => <Text key={m} style={{ width: weekW * 4, fontSize: 5.5, fontWeight: 700, color: C.head, textAlign: "center" }}>{m}</Text>)}
          </View>
          <View style={{ flexDirection: "row", marginLeft: 96, marginBottom: 4 }}>
            {Array.from({ length: 12 }, (_, w) => <Text key={w} style={{ width: weekW, fontSize: 5.5, color: C.muted, textAlign: "center" }}>{w + 1}</Text>)}
          </View>
          {doc.actions.map((a, i) => (
            <View key={a.title} style={{ flexDirection: "row", alignItems: "center", height: 17 }}>
              <View style={{ width: 11, height: 11, borderRadius: 6, backgroundColor: ACTION_COLORS[i % 7], alignItems: "center", justifyContent: "center", marginRight: 4 }}>
                <Text style={{ fontSize: 6, fontWeight: 700, color: C.white }}>{i + 1}</Text>
              </View>
              <Text style={{ width: 81, fontSize: 6.3 }}>{a.title.length > 22 ? `${a.title.slice(0, 21)}…` : a.title}</Text>
              <Svg width={weekW * 12} height={12}>
                {Array.from({ length: 12 }, (_, w) => (w % 2 === 0 ? <Rect key={w} x={w * weekW} y={0} width={weekW} height={12} fill={C.soft} /> : null))}
                <Rect x={(a.start - 1) * weekW + 1} y={1.5} width={Math.min(a.length, 13 - a.start) * weekW - 2} height={9} rx={4} fill={ACTION_COLORS[i % 7]} />
              </Svg>
            </View>
          ))}
        </Card>
        <Card style={{ flex: 1 }}>
          <CardTitle title="Impact vs effort" />
          <View style={{ flexDirection: "row", flexWrap: "wrap" }}>
            {([["quick", "QUICK WINS", C.goodSoft], ["big", "BIG BETS", C.soft], ["fill", "FILL-INS", C.soft], ["avoid", "AVOID", C.soft]] as const).map(([k, label, bg]) => (
              <View key={k} style={{ width: "48%", height: 64, margin: "1%", backgroundColor: bg, borderRadius: 4, padding: 5 }}>
                <Text style={{ fontSize: 5.5, fontWeight: 700, color: k === "quick" ? C.good : C.head }}>{label}</Text>
                <View style={{ flexDirection: "row", flexWrap: "wrap", marginTop: 6 }}>
                  {groups[k].map((i) => (
                    <View key={i} style={{ width: 16, height: 16, borderRadius: 8, backgroundColor: ACTION_COLORS[i % 7], alignItems: "center", justifyContent: "center", margin: 1.5 }}>
                      <Text style={{ fontSize: 7, fontWeight: 700, color: C.white }}>{i + 1}</Text>
                    </View>
                  ))}
                </View>
              </View>
            ))}
          </View>
          <Text style={{ fontSize: 6, color: C.muted, textAlign: "center", marginTop: 2 }}>Top row: high impact. Left column: low effort.</Text>
        </Card>
      </View>
      <Callout tone="bad" title="Quick wins first, then check every claim">
        {`${easy.length > 1 ? `Actions ${easy.join(", ")} are` : `Action ${easy[0] ?? 1} is`} low effort; most can be live within two weeks. Comparison pages must stay factual: avoid promises you cannot back up, and have claims reviewed against your industry's advertising rules before going live.`}
      </Callout>
    </Shell>
  );
}

/* -------------------------------------------------------------- 09 goals */

type Goal = Doc["goals"][number];

function Goals({ doc }: { doc: Doc }) {
  const trackW = 300;
  return (
    <Shell doc={doc}>
      <SectionHead n="09" title="Goals for the next scan" lead="Suggested targets to judge whether the action plan is working. Web-search engines usually move first; model memory moves over months." />
      <Card>
        <View style={{ flexDirection: "row", justifyContent: "space-between", marginBottom: 10 }}>
          <Text style={{ fontSize: 10, fontWeight: 700 }}>Progress path</Text>
          <Legend items={[{ label: "Today", color: C.you }, { label: "30-day goal", color: C.amber }, { label: "90-day goal", color: C.good }]} />
        </View>
        {doc.goals.filter((g) => g.values).map((g) => {
          const [today, d30, d90] = g.values as number[];
          const scale = Math.max(d90 * 1.25, 0.2);
          const x = (v: number) => 8 + (Math.min(v, scale) / scale) * (trackW - 16);
          return (
            <View key={g.metric} style={{ flexDirection: "row", alignItems: "center", marginBottom: 14 }}>
              <Text style={{ fontSize: 8, width: 100, textAlign: "right", marginRight: 10 }}>{g.metric}</Text>
              <Svg width={trackW} height={14}>
                <Rect x={0} y={4} width={trackW} height={6} rx={3} fill={C.soft} />
                <Rect x={x(today)} y={4} width={Math.max(0, x(d90) - x(today))} height={6} fill="#D5F2E1" />
                <Circle cx={x(today)} cy={7} r={5} fill={C.you} />
                <Circle cx={x(d30)} cy={7} r={5} fill={C.amber} />
                <Circle cx={x(d90)} cy={7} r={5} fill={C.good} />
              </Svg>
              <Text style={{ fontSize: 8, fontWeight: 700, color: C.good, marginLeft: 10 }}>{g.d90}</Text>
            </View>
          );
        })}
      </Card>
      <View style={{ marginTop: 10 }}>
        <Table
          cols={[
            { title: "Metric", width: "22%", render: (g: Goal) => g.metric, style: { fontWeight: 700 } },
            { title: "Today", width: "12%", render: (g: Goal) => g.today, style: { color: C.you, fontWeight: 700 } },
            { title: "30-day goal (est.)", width: "20%", render: (g: Goal) => g.d30, style: { color: C.amberInk } },
            { title: "90-day goal (est.)", width: "18%", render: (g: Goal) => g.d90, style: { color: C.good, fontWeight: 700 } },
            { title: "Where to look first", width: "28%", render: (g: Goal) => g.where, style: { color: C.ink2 } },
          ]}
          rows={doc.goals}
        />
        <Text style={{ fontSize: 7, color: C.muted, marginTop: 4 }}>{doc.estimate_note} Goals are directional, not guaranteed. Changes smaller than the 95% range may be normal variation.</Text>
      </View>
      <H2>Recommended setup for the next scan</H2>
      {doc.next_setup.map((s) => (
        <View key={s.title} wrap={false} style={{ flexDirection: "row", height: 40, marginBottom: 6, backgroundColor: C.softBlue, borderRadius: 6, overflow: "hidden" }}>
          <View style={{ width: 66, backgroundColor: C.head, alignItems: "center", justifyContent: "center" }}>
            <Text style={{ fontSize: 15, fontWeight: 700, color: C.white }}>{s.big}</Text>
          </View>
          <View style={{ justifyContent: "center", paddingLeft: 14 }}>
            <Text style={{ fontSize: 10, fontWeight: 700 }}>{s.title}</Text>
            <Text style={{ fontSize: 7.5, color: C.ink2, marginTop: 2 }}>{s.detail}</Text>
          </View>
        </View>
      ))}
    </Shell>
  );
}

/* ------------------------------------------------------- 10 methodology */

type Pair = [string, string];

function Method({ doc }: { doc: Doc }) {
  const steps = [
    [`${doc.questions} buyer questions`, "Real buyer wording", "#3B6FD8"],
    ["Sent to AI", "Fresh chat, no brand", "#8B5CF6"],
    ["Answers collected", `${doc.answers} of ${doc.answers_expected} answers`, "#2E9BD6"],
    ["Each answer read", "Named? Picked? Rank?", "#14A3A3"],
    ["Scored & ranked", "Metrics and actions", "#12A37F"],
  ];
  const details: Pair[] = [
    ["Scan", `#${doc.scan_no}${doc.baseline ? " (baseline), no earlier scan to compare" : ""}`],
    ["Scan date", doc.scan_date],
    ["AI engines", doc.engines.join(", ")],
    ["Buyer questions", `${doc.questions}, each in a fresh conversation`],
    ["Answers analysed", `${doc.answers} of ${doc.answers_expected} collected`],
    ["Market", doc.country],
    ["Tracked brands", doc.brands.map((b) => b.name).join(", ")],
  ];
  const glossary: Pair[] = [
    ["Mention rate", "Share of answers that name the brand."],
    ["Recommendation rate", "Share of answers that pick the brand."],
    ["Share of voice", "The brand's slice of all brand picks."],
    ["Citation rate", "Share of answers linking to the brand's site."],
    ["Open question", "No tracked brand was recommended."],
    ["95% range", "Likely span of the true rate (Wilson method)."],
  ];
  return (
    <Shell doc={doc}>
      <SectionHead n="10" title="Methodology and glossary" lead="How these numbers were produced, so they can be checked and compared over time." />
      <View style={{ flexDirection: "row" }}>
        {steps.map(([t, s, color], i) => (
          <View key={t} style={{ flex: 1, height: 56, backgroundColor: color, marginRight: i < 4 ? 3 : 0, padding: 7, borderRadius: 4 }}>
            <Text style={{ fontSize: 15, fontWeight: 700, color: "#FFFFFF90" }}>{i + 1}</Text>
            <Text style={{ fontSize: 7.5, fontWeight: 700, color: C.white }}>{t}</Text>
            <Text style={{ fontSize: 6, color: "#FFFFFFD0", marginTop: 1 }}>{s}</Text>
          </View>
        ))}
      </View>
      <View style={{ flexDirection: "row", marginTop: 12 }}>
        <View style={{ flex: 1, marginRight: 8 }}>
          <Table cols={[{ title: "Scan details", width: "38%", render: (r: Pair) => r[0], style: { fontWeight: 700 } }, { title: "", width: "62%", render: (r: Pair) => r[1], style: { color: C.ink2 } }]} rows={details} dense />
        </View>
        <View style={{ flex: 1 }}>
          <Table cols={[{ title: "Term", width: "38%", render: (r: Pair) => r[0], style: { fontWeight: 700 } }, { title: "Meaning", width: "62%", render: (r: Pair) => r[1], style: { color: C.ink2 } }]} rows={glossary} dense />
        </View>
      </View>
      <View style={{ flexDirection: "row", marginTop: 6 }}>
        <View style={{ flex: 1, marginRight: 12 }}>
          <H2>How answers are read</H2>
          <Text style={{ fontSize: 8, color: C.ink2, lineHeight: 1.5 }}>
            Each answer is checked for every tracked brand: whether it is named, whether it is recommended as a pick, its rank in any list, the tone used, and which websites are cited. A brand counts as mentioned only if its name appears in the text. Buying stages are assigned from the wording of each question.
          </Text>
        </View>
        <View style={{ flex: 1 }}>
          <H2>AI Visibility Score</H2>
          <Text style={{ fontSize: 8, color: C.ink2, lineHeight: 1.5 }}>
            One 0–100 number for tracking over time: <Text style={{ fontWeight: 700, color: C.ink }}>40%</Text> mention rate + <Text style={{ fontWeight: 700, color: C.ink }}>40%</Text> recommendation rate + <Text style={{ fontWeight: 700, color: C.ink }}>20%</Text> citation rate. Scores compare only within the same method.
          </Text>
          <View style={{ flexDirection: "row", marginTop: 6 }}>
            {([["Mentions 40%", 2], ["Picks 40%", 2], ["Cites 20%", 1]] as const).map(([l, f]) => (
              <View key={l} style={{ flex: f, backgroundColor: C.head, borderRadius: 4, paddingVertical: 6, marginRight: 3, alignItems: "center" }}>
                <Text style={{ fontSize: 7, fontWeight: 700, color: C.white }}>{l}</Text>
              </View>
            ))}
          </View>
        </View>
      </View>
      <Card style={{ marginTop: 12, flexDirection: "row", alignItems: "center" }}>
        <View style={{ marginRight: 14 }}>
          <Text style={{ fontSize: 9, fontWeight: 700 }}>Question set at a glance</Text>
          <Text style={{ fontSize: 6.5, color: C.muted, marginBottom: 4 }}>{doc.questions} questions by buying stage</Text>
          <Donut size={74} thickness={13} segments={doc.stages.map((s) => ({ value: s.count, color: s.color }))} center={String(doc.questions)} sub="questions" />
        </View>
        <View style={{ flex: 1, flexDirection: "row" }}>
          {doc.stages.map((s) => (
            <View key={s.key} style={{ flex: s.count, marginRight: 2, alignItems: "center" }}>
              <View style={{ alignSelf: "stretch", backgroundColor: s.color, borderRadius: 4, paddingVertical: 5, alignItems: "center" }}>
                <Text style={{ fontSize: 8, fontWeight: 700, color: C.white }}>{s.count}</Text>
              </View>
              <Text style={{ fontSize: 6, fontWeight: 700, marginTop: 3 }}>{s.label}</Text>
            </View>
          ))}
        </View>
      </Card>
      <Callout title="Limitations">
        AI answers vary between runs, users, locations and over time, and engines update their models without notice. Results reflect the questions and engines above on the date shown, not every possible conversation. This report describes observed AI answers and is not a guarantee of future results.
      </Callout>
    </Shell>
  );
}

export function Report({ doc }: { doc: Doc }) {
  return (
    <Document title={`${doc.brand} – AI Visibility Report`} author="SeenLens" creator="SeenLens" producer="SeenLens">
      <Cover doc={doc} />
      <Contents doc={doc} />
      <Summary doc={doc} />
      <Standing doc={doc} />
      <Instead doc={doc} />
      <Stages doc={doc} />
      <Opportunities doc={doc} />
      <Questions doc={doc} />
      <Why doc={doc} />
      <Sources doc={doc} />
      <Actions doc={doc} />
      <Goals doc={doc} />
      <Method doc={doc} />
    </Document>
  );
}
