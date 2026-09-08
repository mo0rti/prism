// Runtime boot harness for the Prism dashboard inline script.
// Stubs just enough DOM to execute the whole boot sequence and surface
// runtime errors (TDZ, undefined refs) that `node --check` cannot catch.
// Usage: node boot_harness.js <exported-dashboard.html> [--check-guide-transition] [--check-escaping] [--check-health-labels] [--check-view-accessibility] [--check-unknown-stage]

const fs = require("fs");

const htmlPath = process.argv[2];
const html = fs.readFileSync(htmlPath, "utf-8");
const checkGuideTransition = process.argv.includes("--check-guide-transition");
const checkEscaping = process.argv.includes("--check-escaping");
const checkHealthLabels = process.argv.includes("--check-health-labels");
const checkViewAccessibility = process.argv.includes("--check-view-accessibility");
const checkUnknownStage = process.argv.includes("--check-unknown-stage");

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
    __attributes: {},
    __boardCards: null,
    __boardCardsHtml: null,
    setAttribute(name, value) { this.__attributes[name] = String(value); },
    removeAttribute(name) { delete this.__attributes[name]; },
    hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.__attributes, name); },
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    __listeners: listeners,
    querySelector() { return makeElement(id + "-child"); },
    querySelectorAll(selector) {
      if (id === "board-view" && selector === ".card[data-id]") {
        if (this.__boardCardsHtml !== this.innerHTML) {
          this.__boardCardsHtml = this.innerHTML;
          this.__boardCards = [];
          const cardPattern = /<div class="card(?: [^"]*)?" data-id="([^"]*)"/g;
          let match;
          while ((match = cardPattern.exec(this.innerHTML)) !== null) {
            const card = makeElement(`${id}-card-${this.__boardCards.length}`);
            card.dataset.id = match[1];
            this.__boardCards.push(card);
          }
        }
        return this.__boardCards;
      }
      return [];
    },
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
  querySelectorAll(selector) {
    if (selector === "#dashboard .view") return ["firstrun-view", "graph-view", "board-view", "platform-view"].map(id => doc.getElementById(id));
    return [];
  },
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
sandbox.transitionPayload = JSON.parse(dataJson);

const vm = require("vm");
const regressionChecks = [];
if (checkGuideTransition) {
  regressionChecks.push(`
;(() => {
  const transitioned = JSON.parse(JSON.stringify(globalThis.transitionPayload));
  transitioned.facts.nodes = [{
    id: "F-001", type: "feature", title: "First feature", path: "knowledge/wiki/features/F-001-first-feature.md",
    health: "ok", status: "raw", owner: "po", advisory_review: "not-needed", open_questions: []
  }];
  transitioned.facts.node_count = 1;
  transitioned.facts.edge_count = 0;
  transitioned.facts.edges = [];
  transitioned.facts.intake = { pending: [], quarantined: [] };
  transitioned.blocker_facts = [];
  adoptData(transitioned);
  globalThis.__guideTransitionHtml = document.getElementById("firstrun-view").innerHTML;
})();`);
}
if (checkEscaping) {
  regressionChecks.push(`
;(() => {
  const maliciousId = 'F-evil"><img src=x onerror=alert(1)>';
  const escaped = JSON.parse(JSON.stringify(globalThis.transitionPayload));
  escaped.facts.nodes = [
    { id: maliciousId, type: "feature", title: "<img src=x onerror=alert(2)>", path: 'knowledge/wiki/features/evil"><svg/onload=alert(3)>', health: "ok", status: "raw", open_questions: [] },
    { id: "platform:web", type: "platform", title: "<svg/onload=alert(4)>", path: null, health: "ok" },
  ];
  escaped.facts.node_count = 2;
  escaped.facts.edges = [{ source: maliciousId, target: "platform:web", kind: "<img src=x>", evidence: "malformed id" }];
  escaped.facts.edge_count = 1;
  escaped.facts.intake = { pending: [], quarantined: [] };
  escaped.blocker_facts = [{ feature_id: maliciousId, code: "pending-board-review", message: "<svg/onload=alert(5)>" }];
  adoptData(escaped);
  renderBoard();
  selectNode(maliciousId);
  globalThis.__escapingHtml = {
    board: document.getElementById("board-view").innerHTML,
    platform: document.getElementById("platform-view").innerHTML,
    panel: document.getElementById("panel").innerHTML,
  };
})();`);
}
if (checkHealthLabels) {
  regressionChecks.push(`
;(() => {
  const health = JSON.parse(JSON.stringify(globalThis.transitionPayload));
  health.facts.nodes = [
    { id: "F-error", type: "feature", title: "Malformed source", path: "knowledge/wiki/features/F-error.md", health: "error", status: "raw", owner: "po", open_questions: [] },
    { id: "F-warning", type: "feature", title: "Stale source", path: "knowledge/wiki/features/F-warning.md", health: "warning", status: "raw", owner: "po", open_questions: [] },
  ];
  health.facts.node_count = 2;
  health.facts.edge_count = 0;
  health.facts.edges = [];
  health.facts.intake = { pending: [], quarantined: [] };
  health.blocker_facts = [];
  adoptData(health);
  renderStats();
  renderBoard();
  globalThis.__healthLabelsHtml = {
    stats: document.getElementById("statrow").innerHTML,
    board: document.getElementById("board-view").innerHTML,
  };
})();`);
}
if (checkViewAccessibility) {
  regressionChecks.push(`
;(() => {
  const accessible = JSON.parse(JSON.stringify(globalThis.transitionPayload));
  accessible.facts.nodes = [
    { id: "F-access", type: "feature", title: "Accessible panel", path: "knowledge/wiki/features/F-access.md", health: "ok", status: "raw", owner: "po", open_questions: [] },
  ];
  accessible.facts.node_count = 1;
  accessible.facts.edge_count = 0;
  accessible.facts.edges = [];
  accessible.facts.intake = { pending: [], quarantined: [] };
  accessible.blocker_facts = [];
  adoptData(accessible);
  switchView("board");
  const board = document.getElementById("board-view");
  const graphView = document.getElementById("graph-view");
  if (board.hasAttribute("inert") || board.__attributes["aria-hidden"] !== "false" || !graphView.hasAttribute("inert") || graphView.__attributes["aria-hidden"] !== "true") {
    throw new Error("inactive view remained accessible");
  }
  selectNode("F-access");
  const panel = document.getElementById("panel");
  if (panel.hasAttribute("inert") || panel.__attributes["aria-hidden"] !== "false") throw new Error("open panel remained inert");
  closePanel();
  if (!panel.hasAttribute("inert") || panel.__attributes["aria-hidden"] !== "true") throw new Error("closed panel remained accessible");
})();`);
}
if (checkUnknownStage) {
  regressionChecks.push(`
;(() => {
  const malformed = JSON.parse(JSON.stringify(globalThis.transitionPayload));
  malformed.facts.nodes = [
    { id: "F-invalid", type: "feature", title: "Invalid stage feature", path: "knowledge/wiki/features/F-invalid.md", health: "error", status: "unexpected-stage", owner: "po", open_questions: [] },
    { id: "F-missing", type: "feature", title: "Missing stage feature", path: "knowledge/wiki/features/F-missing.md", health: "error", status: null, owner: "po", open_questions: [] },
  ];
  malformed.facts.node_count = 2;
  malformed.facts.edge_count = 0;
  malformed.facts.edges = [];
  malformed.facts.intake = { pending: [], quarantined: [] };
  malformed.blocker_facts = [];
  adoptData(malformed);
  renderBoard();
  const board = document.getElementById("board-view");
  const cards = board.querySelectorAll(".card[data-id]");
  const invalidCard = cards.find(card => card.dataset.id === "F-invalid");
  const boardHtml = board.innerHTML;
  if (!boardHtml.includes(">unknown stage<") || !boardHtml.includes("status: unexpected-stage") || !boardHtml.includes("missing status")) {
    throw new Error("unsupported feature stages were not surfaced in the board");
  }
  if (!invalidCard || !invalidCard.__listeners.click || !invalidCard.__listeners.click.length) {
    throw new Error("unknown-stage feature card was not wired for selection");
  }
  invalidCard.__listeners.click[0]();
  if (!document.getElementById("panel").innerHTML.includes("Invalid stage feature")) {
    throw new Error("unknown-stage feature card did not open its inspector");
  }
})();`);
}
try {
  vm.runInNewContext(appJs + regressionChecks.join("\n"), sandbox, { filename: "dashboard-app.js" });
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

if (checkGuideTransition) {
  const guideHtml = sandbox.__guideTransitionHtml || "";
  const completedSteps = (guideHtml.match(/class="step done"/g) || []).length;
  if (completedSteps === 3 && guideHtml.includes("brief captured") && guideHtml.includes("feature page created")) {
    console.log("GUIDE TRANSITION OK - first feature keeps capture and intake complete");
  } else {
    console.error("GUIDE TRANSITION FAILED - first feature did not preserve completed steps");
    process.exit(1);
  }
}

if (checkEscaping) {
  const output = sandbox.__escapingHtml || {};
  const rendered = (output.board || "") + (output.panel || "");
  if (/<(?:img|svg|script)\b/i.test(rendered) || !rendered.includes("&lt;img") || !rendered.includes("&lt;svg")) {
    console.error("ESCAPING FAILED - data-derived markup was not inert");
    process.exit(1);
  }
  console.log("ESCAPING OK - malformed IDs and text remain inert");
}
if (checkHealthLabels) {
  const output = sandbox.__healthLabelsHtml || {};
  const stats = output.stats || "";
  const board = output.board || "";
  if (!stats.includes("malformed pages") || !stats.includes("Warnings") || !board.includes(">malformed<") || !board.includes(">warning<")) {
    console.error("HEALTH LABELS FAILED - warning and malformed states were conflated");
    process.exit(1);
  }
  console.log("HEALTH LABELS OK - warning and malformed states stay distinct");
}
if (checkViewAccessibility) console.log("VIEW ACCESSIBILITY OK - inactive views and closed inspector are inert");
if (checkUnknownStage) console.log("UNKNOWN STAGE OK - malformed features remain visible and selectable");
// sanity: header + views wired
const viewsEl = elements["views"];
if (viewsEl && viewsEl.__listeners.click) console.log("EVENTS OK — view switcher has click handler");
else { console.error("EVENTS MISSING — view switcher not wired"); process.exit(1); }
