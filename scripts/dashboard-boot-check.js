// Runtime boot harness for the Prism dashboard inline script.
// Stubs just enough DOM to execute the whole boot sequence and surface
// runtime errors (TDZ, undefined refs) that `node --check` cannot catch.
// Usage: node boot_harness.js <exported-dashboard.html>

const fs = require("fs");

const htmlPath = process.argv[2];
const html = fs.readFileSync(htmlPath, "utf-8");

// --- extract embedded JSON payloads and the app script ---
function tagContent(id) {
  const marker = `id="${id}" type="application/json">`;
  const start = html.indexOf(marker) + marker.length;
  return html.slice(start, html.indexOf("</script>", start));
}
const dataJson = tagContent("prism-data");
const configJson = tagContent("prism-config");
const appMatch = html.match(/<script>\s*"use strict";[\s\S]*$/);
const appStart = html.lastIndexOf(appMatch ? appMatch[0].slice(0, 30) : "@@nomatch@@");
if (appStart < 0) { console.error("Could not locate app script"); process.exit(1); }
const appJs = html.slice(appStart + "<script>".length, html.indexOf("</script>", appStart));

// --- minimal DOM stubs ---
function makeElement(id) {
  const listeners = {};
  return {
    id,
    innerHTML: "",
    textContent: id === "prism-data" ? dataJson : id === "prism-config" ? configJson : "",
    style: {},
    dataset: {},
    hidden: false,
    className: "",
    value: "",
    title: "",
    clientWidth: 1200,
    clientHeight: 800,
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    __listeners: listeners,
    querySelector() { return makeElement(id + "-child"); },
    querySelectorAll() { return []; },
    appendChild() {},
    focus() {},
    closest() { return null; },
    getBoundingClientRect() { return { width: 1200, height: 800 }; },
  };
}
const elements = {};
const doc = {
  documentElement: makeElement("html"),
  activeElement: null,
  getElementById(id) { return elements[id] || (elements[id] = makeElement(id)); },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  addEventListener() {},
  createElement(tag) { return makeElement("dyn-" + tag); },
};
doc.documentElement.setAttribute = function () {};
doc.documentElement.getAttribute = function () { return "dark"; };

// chainable ForceGraph stub
function makeChain() {
  const target = function () {};
  const proxy = new Proxy(target, {
    get(_t, prop) {
      if (prop === "graphData") {
        return function (arg) { return arg === undefined ? { nodes: [], links: [] } : proxy; };
      }
      if (prop === "zoom") {
        return function (arg) { return arg === undefined ? 1 : proxy; };
      }
      return function () { return proxy; };
    },
    apply() { return proxy; },
  });
  return proxy;
}

const errors = [];
const sandbox = {
  document: doc,
  window: {
    matchMedia() { return { matches: true, addEventListener() {} }; },
    addEventListener() {},
  },
  localStorage: { getItem() { return null; }, setItem() {} },
  getComputedStyle() { return { getPropertyValue() { return "#3987e5"; } }; },
  performance: { now: () => Date.now() },
  requestAnimationFrame(fn) { /* don't run: avoid loops */ },
  cancelAnimationFrame() {},
  setTimeout() {},
  navigator: {},
  EventSource: undefined,
  fetch() { return Promise.resolve({ json: () => Promise.resolve({}) }); },
  ForceGraph: () => makeChain(),
  console,
};
sandbox.globalThis = sandbox;

const vm = require("vm");
try {
  vm.runInNewContext(appJs, sandbox, { filename: "dashboard-app.js" });
  console.log("BOOT OK — full script executed without runtime errors");
} catch (err) {
  console.error("BOOT FAILED:", err.constructor.name + ":", err.message);
  const line = (err.stack.match(/dashboard-app\.js:(\d+)/) || [])[1];
  if (line) console.error("  at inline script line", line);
  process.exit(1);
}

// sanity: the first-run teaching page must have rendered for a fresh workspace
const data = JSON.parse(dataJson);
const anyFeature = data.facts.nodes.some(n => n.type === "feature");
const firstrun = elements["firstrun-view"];
if (!anyFeature) {
  const html = firstrun ? firstrun.innerHTML : "";
  if (html.includes("WORKSPACE SETUP") && html.includes("FIRST-RUN.TXT") && html.includes("pipe-track")) {
    console.log("FIRSTRUN OK — teaching page (pipeline + setup steps) rendered for fresh workspace");
  } else {
    console.error("FIRSTRUN MISSING — fresh workspace did not render the teaching page");
    process.exit(1);
  }
} else {
  const statrow = elements["statrow"];
  if (statrow && statrow.innerHTML.includes("stat")) {
    console.log("DASHBOARD OK — stats rendered for populated workspace");
  } else {
    console.error("DASHBOARD MISSING — populated workspace did not render stats");
    process.exit(1);
  }
}
// sanity: header + views wired
const viewsEl = elements["views"];
if (viewsEl && viewsEl.__listeners.click) console.log("EVENTS OK — view switcher has click handler");
else { console.error("EVENTS MISSING — view switcher not wired"); process.exit(1); }
