#!/usr/bin/env node
/* Regression tests for the pure graph-layout core embedded in index.html
 * (<script id="layoutCore">). Extracted at runtime so the tests always run
 * against the real shipped code.
 *
 * Run: node frontend/test_graph_layout.js   (from the repo root)
 */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const htmlPath = path.join(__dirname, "index.html");
const html = fs.readFileSync(htmlPath, "utf8");
const m = html.match(/<script id="layoutCore">([\s\S]*?)<\/script>/);
if (!m) {
  console.error("FAIL: layoutCore script block not found in index.html");
  process.exit(1);
}
const ctx = {};
vm.createContext(ctx);
vm.runInContext(m[1], ctx);
const { graphLayout } = ctx;

let failures = 0;
function check(name, cond, detail) {
  if (cond) console.log("ok   " + name);
  else { failures++; console.log("FAIL " + name + (detail ? " — " + detail : "")); }
}

const rad = (L, id) => { const p = L.pos[id]; return p ? Math.hypot(p.x, p.y) : -1; };

function makeGraph(n, withIsolated) {
  const nodes = [{ id: "C", name: "Operation WHITE STRIKE", type: "CASE" }];
  const edges = [];
  const types = ["PERSON", "ORGANIZATION", "LOCATION", "DRUG", "VEHICLE", "EVENT"];
  for (let i = 1; i <= n; i++) {
    nodes.push({ id: "n" + i, name: "Node name number " + i + " with a fairly long label", type: types[i % types.length] });
    if (i % 3) edges.push({ source: "C", target: "n" + i });
    else edges.push({ source: "n" + (i - 1), target: "n" + i });
  }
  if (withIsolated) nodes.push({ id: "iso", name: "Amit Shah Mentioned Only Contextual", type: "PERSON" });
  return { nodes, edges };
}

// 1. Every graph size (1..50 nodes) places every node, all within bounds,
//    deterministically, with the center at the ORIGIN (the visual root of
//    the radial layout) and no truncated labels.
for (const n of [1, 2, 5, 10, 20, 30, 50]) {
  for (const iso of [false, true]) {
    const g = makeGraph(n, iso);
    const L = graphLayout({ nodes: g.nodes, edges: g.edges, centerId: "C" });
    const b = L.bounds;
    const missing = g.nodes.filter((x) => !L.pos[x.id]);
    const out = g.nodes.filter((x) => {
      const p = L.pos[x.id];
      return !p || p.x < b.minX || p.x > b.maxX || p.y < b.minY || p.y > b.maxY;
    });
    const L2 = graphLayout({ nodes: g.nodes, edges: g.edges, centerId: "C" });
    const same = g.nodes.every((x) => L.pos[x.id].x === L2.pos[x.id].x && L.pos[x.id].y === L2.pos[x.id].y);
    const truncated = g.nodes.some((x) => L.dims[x.id].lines.some((l) => l.includes("\u2026")));
    const hasIso = !iso || L.isoIds.has("iso");
    const centerAtOrigin = L.pos.C.x === 0 && L.pos.C.y === 0;
    check(`n=${n} iso=${iso}: all placed, in-bounds, deterministic, center-at-origin, no truncation`,
      !missing.length && !out.length && same && centerAtOrigin && !truncated && hasIso);
  }
}

// 2. Ring structure: BFS distance from the center decides the ring — nodes
//    one hop away sit closer to the origin than nodes two hops away, and
//    ring-1 nodes lie on a single circle (equal radius). Positioning only.
{
  const g = makeGraph(10, true);
  const L = graphLayout({ nodes: g.nodes, edges: g.edges, centerId: "C" });
  check("radial distance grows with graph distance", rad(L, "n3") > rad(L, "n1"), `n3=${rad(L, "n3")} n1=${rad(L, "n1")}`);
  check("layerOf reflects the distance", L.layerOf.n1 === 1 && L.layerOf.n3 === 2, JSON.stringify([L.layerOf.n1, L.layerOf.n3]));
  const r1 = g.nodes.filter((x) => L.layerOf[x.id] === 1);
  const spread = r1.length ? Math.max.apply(null, r1.map((x) => rad(L, x.id))) - Math.min.apply(null, r1.map((x) => rad(L, x.id))) : 0;
  check("ring-1 nodes sit on one circle (equal radius)", spread < 0.001, `spread=${spread}`);
}

// 3. Isolated / contextual nodes land on dedicated OUTER rings — further
//    from the origin than every connected node — separated by connectivity,
//    never by type.
{
  const g = makeGraph(8, true);
  const L = graphLayout({ nodes: g.nodes, edges: g.edges, centerId: "C" });
  const maxConnected = Math.max.apply(null, g.nodes.filter((x) => x.id !== "C" && x.id !== "iso").map((x) => rad(L, x.id)));
  check("isolated node sits beyond the connected network", rad(L, "iso") > maxConnected, `iso=${rad(L, "iso")} maxConnected=${maxConnected}`);
}

// 4. Full-name wrapping: long names wrap into at most two full lines and
//    are never truncated with an ellipsis.
{
  const g = makeGraph(3, false);
  const L = graphLayout({ nodes: g.nodes, edges: g.edges, centerId: "C" });
  check("long names wrap to <=2 full lines", g.nodes.every((x) => L.dims[x.id].lines.length <= 2 && !L.dims[x.id].lines.some((l) => l.includes("\u2026"))));
}

// 5. Label boxes are included in the bounding box (Fit never clips) and
//    every node has usable label metadata for outward placement.
{
  const g = makeGraph(6, true);
  const L = graphLayout({ nodes: g.nodes, edges: g.edges, centerId: "C" });
  const b = L.bounds;
  check("bounding box includes labels", g.nodes.every((x) => {
    const lb = L.labelBox[x.id];
    if (!lb) return false;
    return lb.x >= b.minX && lb.x + lb.w <= b.maxX && lb.y >= b.minY && lb.y + lb.h <= b.maxY;
  }));
  check("every node has outward label metadata", g.nodes.every((x) => L.labelMeta[x.id] && typeof L.labelMeta[x.id].anchor === "string"));
}

// 6. Barycenter ordering is deterministic even with many neighbours and
//    the layout never reorders on re-computation (REQ 30).
{
  const g = makeGraph(50, true);
  const L1 = graphLayout({ nodes: g.nodes, edges: g.edges, centerId: "C" });
  const L2 = graphLayout({ nodes: g.nodes, edges: g.edges, centerId: "C" });
  const ring = g.nodes.filter((x) => L1.layerOf[x.id] === 1);
  const order1 = ring.map((x) => Math.atan2(L1.pos[x.id].y, L1.pos[x.id].x).toFixed(6)).join(",");
  const order2 = ring.map((x) => Math.atan2(L2.pos[x.id].y, L2.pos[x.id].x).toFixed(6)).join(",");
  check("ring order is deterministic", order1 === order2);
}

if (failures) { console.error(`${failures} layout check(s) FAILED`); process.exit(1); }
console.log("All layout checks passed.");
