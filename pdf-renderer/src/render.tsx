// Reads a report document (JSON) on stdin and writes the PDF to stdout. Usage: node dist/render.mjs <fonts dir>
import React from "react";
import { Font, renderToBuffer } from "@react-pdf/renderer";
import { Report } from "./report";
import type { Doc } from "./types";

const fonts = process.argv[2];
if (!fonts) {
  process.stderr.write("usage: render.mjs <fonts dir>\n");
  process.exit(2);
}
Font.register({
  family: "Geist",
  fonts: [
    { src: `${fonts}/Geist-Regular.ttf`, fontWeight: 400 },
    { src: `${fonts}/Geist-Medium.ttf`, fontWeight: 500 },
    { src: `${fonts}/Geist-SemiBold.ttf`, fontWeight: 600 },
    { src: `${fonts}/Geist-Bold.ttf`, fontWeight: 700 },
  ],
});
// Hindi and other Devanagari text in questions or brand names.
Font.register({
  family: "NotoDevanagari",
  fonts: [
    { src: `${fonts}/NotoSansDevanagari-Regular.ttf`, fontWeight: 400 },
    { src: `${fonts}/NotoSansDevanagari-SemiBold.ttf`, fontWeight: 700 },
  ],
});
Font.registerHyphenationCallback((word) => [word]); // never split words with hyphens

const chunks: Buffer[] = [];
for await (const chunk of process.stdin) chunks.push(chunk as Buffer);
const doc = JSON.parse(Buffer.concat(chunks).toString("utf8")) as Doc;
process.stdout.write(await renderToBuffer(<Report doc={doc} />));
