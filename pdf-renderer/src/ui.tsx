import React from "react";
import { Circle, Path, Rect, Svg, Text, View } from "@react-pdf/renderer";
import type { Style } from "@react-pdf/types";

export const C = {
  navy: "#1E2A5A",
  navyDeep: "#141B3D",
  head: "#33407F",
  ink: "#151A2D",
  ink2: "#454B63",
  muted: "#7A8098",
  line: "#E3E6EF",
  soft: "#F3F4F8",
  softBlue: "#ECEEF6",
  white: "#FFFFFF",
  you: "#C8373F",
  youSoft: "#F9E9EA",
  good: "#2F7D57",
  goodSoft: "#E8F2EC",
  amber: "#C98A1B",
  amberInk: "#9A6510",
  amberSoft: "#FBF1E1",
  lilac: "#8E9BE0",
};

export const pct = (v: number | null | undefined) => (v == null ? "–" : `${Math.round(v * 100)}%`);

/** Section banner: navy card, title, one-line lead and the section number set large and faint. */
export function SectionHead({ n, title, lead }: { n: string; title: string; lead: string }) {
  return (
    <View style={{ backgroundColor: C.head, borderRadius: 10, paddingVertical: 14, paddingHorizontal: 18, marginBottom: 14, overflow: "hidden" }}>
      <Svg width={200} height={120} style={{ position: "absolute", right: -30, top: -20 }}>
        <Circle cx={130} cy={50} r={70} fill="#FFFFFF" fillOpacity={0.05} />
        <Circle cx={170} cy={110} r={45} fill="#FFFFFF" fillOpacity={0.05} />
      </Svg>
      <Text style={{ position: "absolute", right: 22, top: 10, fontSize: 52, fontWeight: 700, color: "#FFFFFF", opacity: 0.18 }}>{n}</Text>
      <Text style={{ fontSize: 7, fontWeight: 700, color: C.lilac, letterSpacing: 0.6 }}>SECTION {n}</Text>
      <Text style={{ fontSize: 19, fontWeight: 700, color: C.white, marginTop: 3 }}>{title}</Text>
      <Text style={{ fontSize: 9, color: "#DCE0F5", marginTop: 4, width: "76%", lineHeight: 1.4 }}>{lead}</Text>
    </View>
  );
}

export type Col<T> = { title: string; width: number | string; render: (row: T, i: number) => React.ReactNode; style?: Style };

/** Navy header row, striped body. Cells render strings as text and anything else as given. */
export function Table<T>({ cols, rows, highlight, dense }: { cols: Col<T>[]; rows: T[]; highlight?: (row: T) => boolean; dense?: boolean }) {
  const pad = dense ? 3 : 5;
  return (
    <View>
      <View style={{ flexDirection: "row", backgroundColor: C.head, paddingVertical: 5, paddingHorizontal: 6 }} fixed>
        {cols.map((c) => (
          <Text key={c.title} style={{ width: c.width, fontSize: 6.5, fontWeight: 700, color: C.white, letterSpacing: 0.3 }}>
            {c.title.toUpperCase()}
          </Text>
        ))}
      </View>
      {rows.map((row, i) => (
        <View
          key={i}
          wrap={false}
          style={{
            flexDirection: "row", alignItems: "center", paddingVertical: pad, paddingHorizontal: 6, borderBottom: `0.5 solid ${C.line}`,
            backgroundColor: highlight?.(row) ? C.youSoft : i % 2 ? C.soft : C.white,
          }}
        >
          {cols.map((c) => {
            const v = c.render(row, i);
            return typeof v === "string" || typeof v === "number" ? (
              <Text key={c.title} style={[{ width: c.width, fontSize: 8, color: C.ink, lineHeight: 1.3, paddingRight: 4 }, c.style ?? {}]}>{v}</Text>
            ) : (
              <View key={c.title} style={{ width: c.width, paddingRight: 4 }}>{v}</View>
            );
          })}
        </View>
      ))}
    </View>
  );
}

const TONES = {
  info: { bar: C.head, bg: C.softBlue, title: C.head, mark: "i" },
  warn: { bar: C.amber, bg: C.amberSoft, title: C.amberInk, mark: "!" },
  good: { bar: C.good, bg: C.goodSoft, title: C.good, mark: "" },
  bad: { bar: C.you, bg: C.youSoft, title: C.you, mark: "!" },
};

export function Callout({ tone = "info", title, children, style }: { tone?: keyof typeof TONES; title: string; children: React.ReactNode; style?: Style }) {
  const t = TONES[tone];
  return (
    <View wrap={false} style={[{ flexDirection: "row", backgroundColor: t.bg, borderLeft: `3 solid ${t.bar}`, borderRadius: 6, padding: 11, marginTop: 10 }, style ?? {}]}>
      <View style={{ width: 18, height: 18, borderRadius: 9, backgroundColor: t.bar, alignItems: "center", justifyContent: "center", marginRight: 10 }}>
        <Text style={{ color: C.white, fontSize: 9, fontWeight: 700 }}>{t.mark}</Text>
      </View>
      <View style={{ flex: 1 }}>
        <Text style={{ fontSize: 9.5, fontWeight: 700, color: t.title, marginBottom: 2 }}>{title}</Text>
        {typeof children === "string" ? <Text style={{ fontSize: 8.5, color: C.ink2, lineHeight: 1.45 }}>{children}</Text> : children}
      </View>
    </View>
  );
}

export function Card({ children, style, dark }: { children: React.ReactNode; style?: Style; dark?: boolean }) {
  return (
    <View wrap={false} style={[{ border: dark ? "none" : `0.75 solid ${C.line}`, borderRadius: 8, padding: 12, backgroundColor: dark ? C.navy : C.white }, style ?? {}]}>
      {children}
    </View>
  );
}

export function CardTitle({ title, sub, dark }: { title: string; sub?: string; dark?: boolean }) {
  return (
    <View style={{ marginBottom: 8 }}>
      <Text style={{ fontSize: 10, fontWeight: 700, color: dark ? C.white : C.ink }}>{title}</Text>
      {sub ? <Text style={{ fontSize: 7, color: dark ? "#B8BFDF" : C.muted, marginTop: 2 }}>{sub}</Text> : null}
    </View>
  );
}

export function H2({ children }: { children: string }) {
  return <Text style={{ fontSize: 12, fontWeight: 700, color: C.ink, marginTop: 14, marginBottom: 6 }}>{children}</Text>;
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap" }}>
      {items.map((it) => (
        <View key={it.label} style={{ flexDirection: "row", alignItems: "center", marginRight: 10 }}>
          <View style={{ width: 7, height: 7, borderRadius: 2, backgroundColor: it.color, marginRight: 4 }} />
          <Text style={{ fontSize: 7, color: C.ink2 }}>{it.label}</Text>
        </View>
      ))}
    </View>
  );
}

function arc(cx: number, cy: number, r: number, start: number, end: number) {
  const a0 = (start - 90) * (Math.PI / 180);
  const a1 = (end - 90) * (Math.PI / 180);
  const large = end - start > 180 ? 1 : 0;
  return `M ${cx + r * Math.cos(a0)} ${cy + r * Math.sin(a0)} A ${r} ${r} 0 ${large} 1 ${cx + r * Math.cos(a1)} ${cy + r * Math.sin(a1)}`;
}

/** Ring chart. Segments are drawn as arcs so they print cleanly at any size. */
export function Donut({ size, thickness, segments, center, sub, track = C.line }: {
  size: number; thickness: number; segments: { value: number; color: string }[]; center?: string; sub?: string; track?: string;
}) {
  const r = (size - thickness) / 2;
  const c = size / 2;
  const total = segments.reduce((s, x) => s + x.value, 0);
  let at = 0;
  return (
    <View style={{ width: size, height: size }}>
      <Svg width={size} height={size}>
        <Circle cx={c} cy={c} r={r} stroke={track} strokeWidth={thickness} fill="none" />
        {total > 0 &&
          segments.filter((s) => s.value > 0).map((s, i) => {
            const sweep = (s.value / total) * 360;
            const el = sweep >= 359.9
              ? <Circle key={i} cx={c} cy={c} r={r} stroke={s.color} strokeWidth={thickness} fill="none" />
              : <Path key={i} d={arc(c, c, r, at, at + sweep)} stroke={s.color} strokeWidth={thickness} fill="none" />;
            at += sweep;
            return el;
          })}
      </Svg>
      {center ? (
        <View style={{ position: "absolute", top: 0, left: 0, width: size, height: size, alignItems: "center", justifyContent: "center" }}>
          <Text style={{ fontSize: size / 4.6, fontWeight: 700, color: C.ink }}>{center}</Text>
          {sub ? <Text style={{ fontSize: Math.max(6, size / 14), color: C.muted, marginTop: 1 }}>{sub}</Text> : null}
        </View>
      ) : null}
    </View>
  );
}

/** Half-circle score gauge, red to green, with the score's position marked by a dot. */
export function Gauge({ value, size }: { value: number; size: number }) {
  const r = size / 2 - 10;
  const cx = size / 2;
  const cy = size / 2 + 4;
  const bands = ["#C8373F", "#D06A3A", "#C98A1B", "#7FA34A", "#2F9D6B"];
  const angle = -90 + (Math.min(100, Math.max(0, value)) / 100) * 180;
  const a = (angle - 90) * (Math.PI / 180);
  return (
    <Svg width={size} height={size / 2 + 14}>
      {bands.map((b, i) => (
        <Path key={b} d={arc(cx, cy, r, -90 + i * 36 + 1, -90 + (i + 1) * 36 - 1)} stroke={b} strokeWidth={9} fill="none" strokeOpacity={0.85} />
      ))}
      <Circle cx={cx + r * Math.cos(a)} cy={cy + r * Math.sin(a)} r={6} fill={C.white} stroke={C.navy} strokeWidth={2} />
    </Svg>
  );
}

/** One horizontal bar on a 0-100% track. */
export function Bar({ value, color, width, height = 8, max = 1, track = C.soft }: { value: number; color: string; width: number; height?: number; max?: number; track?: string }) {
  const w = Math.max(value > 0 ? 2 : 0, (Math.min(value, max) / max) * width);
  return (
    <Svg width={width} height={height}>
      <Rect x={0} y={0} width={width} height={height} rx={height / 2} fill={track} />
      {w > 0 ? <Rect x={0} y={0} width={w} height={height} rx={height / 2} fill={color} /> : null}
    </Svg>
  );
}

export function Pill({ label, color, text = C.white, width }: { label: string; color: string; text?: string; width?: number | string }) {
  return (
    <View style={{ backgroundColor: color, borderRadius: 3, paddingVertical: 2.5, width, alignItems: "center" }}>
      <Text style={{ fontSize: 6.5, fontWeight: 700, color: text }}>{label}</Text>
    </View>
  );
}
