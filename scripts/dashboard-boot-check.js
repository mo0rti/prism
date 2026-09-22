// Runtime boot harness for the Prism dashboard inline script.
// Stubs just enough DOM to execute the whole boot sequence and surface
// runtime errors (TDZ, undefined refs) that `node --check` cannot catch.
// Usage: node boot_harness.js <exported-dashboard.html> [--check-guide-transition] [--check-escaping] [--check-health-labels] [--check-view-accessibility] [--check-unknown-stage] [--check-transitions]

const fs = require("fs");

const htmlPath = process.argv[2];
const html = fs.readFileSync(htmlPath, "utf-8");
const checkGuideTransition = process.argv.includes("--check-guide-transition");
const checkEscaping = process.argv.includes("--check-escaping");
const checkHealthLabels = process.argv.includes("--check-health-labels");
const checkViewAccessibility = process.argv.includes("--check-view-accessibility");
const checkUnknownStage = process.argv.includes("--check-unknown-stage");
const checkTransitions = process.argv.includes("--check-transitions");

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

function decodeHtml(value) {
  return String(value).replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
}
function parseAttributes(raw) {
  const attrs = {};
  const pattern = /([:\w-]+)(?:="([^"]*)")?/g;
  let match;
  while ((match = pattern.exec(raw)) !== null) attrs[match[1]] = match[2] === undefined ? "" : decodeHtml(match[2]);
  return attrs;
}
function hasClass(attrs, name) {
  return String(attrs.class || "").split(/\s+/).includes(name);
}
function matchesSelector(tag, attrs, selector) {
  return selector.split(",").some(part => {
    const value = part.trim();
    if (value === ".card[data-id]") return tag === "div" && hasClass(attrs, "card") && attrs["data-id"] !== undefined;
    if (value === ".card[data-intake]") return tag === "div" && hasClass(attrs, "card") && attrs["data-intake"] !== undefined;
    if (value === ".column[data-stage]") return tag === "div" && hasClass(attrs, "column") && attrs["data-stage"] !== undefined;
    if (value === "[data-transition-id]" || value === ".prepare-btn") return tag === "button" && attrs["data-transition-id"] !== undefined;
    if (value === "[data-transition-cancel]" || value === ".cancel-btn") return tag === "button" && attrs["data-transition-cancel"] !== undefined;
    if (value === "[data-transition-copy]" || value === ".copy-request") return tag === "button" && attrs["data-transition-copy"] !== undefined;
    if (value === "[data-transition-surface]" || value.startsWith("[data-transition-surface=\"")) {
      const surfaceMatch = value.match(/^\[data-transition-surface="([^"]+)"\]$/);
      return tag === "button" && attrs["data-transition-surface"] !== undefined && (!surfaceMatch || surfaceMatch[1] === attrs["data-transition-surface"]);
    }
    if (value === "[data-transition-select]") return tag === "select" && attrs["data-transition-select"] !== undefined;
    if (value === "[data-transition-hint]") return attrs["data-transition-hint"] !== undefined;
    if (value === ".fchip") return tag === "div" && hasClass(attrs, "fchip");
    if (value === ".conn") return tag === "div" && hasClass(attrs, "conn");
    if (value === ".copy-btn") return (tag === "button" || tag === "a") && hasClass(attrs, "copy-btn");
    if (value === ".cmd-tabs button") return tag === "button";
    if (value === ".legend-head") return hasClass(attrs, "legend-head");
    if (value === ".transition-dialog") return hasClass(attrs, "transition-dialog");
    if (value === "#transition-dialog-title" || value === "#transition-copy-status") return attrs.id === value.slice(1);
    if (value === "button") return tag === "button";
    if (value === "a[href]") return tag === "a" && attrs.href !== undefined;
    if (value === "input") return tag === "input";
    if (value === "select") return tag === "select";
    if (value === "textarea") return tag === "textarea";
    if (value.startsWith("[tabindex]")) return attrs.tabindex !== undefined && attrs.tabindex !== "-1";
    return false;
  });
}
function makeElement(id, sourceHtml) {
  const listeners = {};
  const classes = new Set();
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
    __attributes: {},
    __parsedSource: null,
    __parsedCache: {},
    __nodeCache: {},
    __sourceHtml: sourceHtml,
    isConnected: true,
    classList: {
      add(...names) { names.forEach(name => classes.add(name)); },
      remove(...names) { names.forEach(name => classes.delete(name)); },
      toggle(name, force) {
        const next = force === undefined ? !classes.has(name) : !!force;
        if (next) classes.add(name); else classes.delete(name);
        return next;
      },
      contains(name) { return classes.has(name); },
    },
    setAttribute(name, value) {
      this.__attributes[name] = String(value);
      if (name === "class") { this.className = String(value); String(value).split(/\s+/).filter(Boolean).forEach(name => classes.add(name)); }
      if (name.startsWith("data-")) this.dataset[name.slice(5).replace(/-([a-z])/g, (_m, ch) => ch.toUpperCase())] = String(value);
      if (name === "hidden") this.hidden = true;
    },
    removeAttribute(name) {
      delete this.__attributes[name];
      if (name.startsWith("data-")) delete this.dataset[name.slice(5).replace(/-([a-z])/g, (_m, ch) => ch.toUpperCase())];
      if (name === "hidden") this.hidden = false;
    },
    hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.__attributes, name); },
    getAttribute(name) { return this.__attributes[name] === undefined ? null : this.__attributes[name]; },
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    __listeners: listeners,
    querySelector(selector) {
      const matches = this.querySelectorAll(selector);
      return matches.length ? matches[0] : null;
    },
    querySelectorAll(selector) {
      const source = this.__sourceHtml !== undefined && this.__sourceHtml !== null ? this.__sourceHtml : this.innerHTML;
      if (this.__parsedSource !== source) {
        Object.values(this.__nodeCache).forEach(node => { node.isConnected = false; });
        this.__parsedSource = source;
        this.__parsedCache = {};
        this.__nodeCache = {};
      }
      let cache = this.__parsedCache[selector];
      if (!cache) {
        cache = { source, nodes: [] };
        this.__parsedCache[selector] = cache;
        const pattern = /<([a-z][\w-]*)\b([^>]*)>/gi;
        let match;
        while ((match = pattern.exec(source || "")) !== null) {
          const tag = match[1].toLowerCase();
          const attrs = parseAttributes(match[2]);
          if (!matchesSelector(tag, attrs, selector)) continue;
          const key = String(match.index);
          const node = this.__nodeCache[key] || makeElement(id + "-node-" + key, source);
          this.__nodeCache[key] = node;
          node.__root = this.__root || this;
          node.__owner = this;
          node.parentElement = this;
          node.__attributes = Object.fromEntries(Object.entries(attrs).map(([key, value]) => [key, value]));
          node.className = attrs.class || "";
          node.className.split(/\s+/).filter(Boolean).forEach(name => node.classList.add(name));
          Object.entries(attrs).forEach(([key, value]) => {
            if (key.startsWith("data-")) node.dataset[key.slice(5).replace(/-([a-z])/g, (_m, ch) => ch.toUpperCase())] = value;
          });
          node.textContent = decodeHtml((source.slice(match.index + match[0].length, source.indexOf("</", match.index + match[0].length)) || "").replace(/<[^>]*>/g, "").trim());
          if (attrs.id) { node.id = attrs.id; elements[attrs.id] = node; }
          cache.nodes.push(node);
        }
      }
      return cache.nodes;
    },
    appendChild() {},
    focus() { doc.activeElement = this; },
    contains(target) { return !!target && (target === this || target.__root === (this.__root || this)); },
    closest() { return null; },
    getBoundingClientRect() { return { width: 1200, height: 800 }; },
  };
}
const elements = {};
const docListeners = {};
const doc = {
  documentElement: makeElement("html"),
  activeElement: null,
  getElementById(id) {
    if (elements[id] && elements[id].isConnected !== false) return elements[id];
    delete elements[id];
    const roots = ["panel", "transition-dialog", "board-view", "platform-view", "firstrun-view", "graph-view", "views", "toolbar"];
    for (const rootId of roots) {
      const root = elements[rootId];
      if (!root || !root.querySelector) continue;
      const found = root.querySelector("#" + id);
      if (found) return found;
    }
    return elements[id] || (elements[id] = makeElement(id));
  },
  querySelector(selector) {
    if (selector.startsWith("#") && !selector.includes(" ")) return doc.getElementById(selector.slice(1));
    if (selector.startsWith("#panel ")) return doc.getElementById("panel").querySelector(selector.slice(7));
    if (selector.startsWith("#board-view ")) return doc.getElementById("board-view").querySelector(selector.slice(12));
    if (selector.startsWith("#transition-dialog ")) return doc.getElementById("transition-dialog").querySelector(selector.slice(20));
    return null;
  },
  querySelectorAll(selector) {
    if (selector === "#dashboard .view") return ["firstrun-view", "graph-view", "board-view", "platform-view"].map(id => doc.getElementById(id));
    if (selector.startsWith("#panel ")) return doc.getElementById("panel").querySelectorAll(selector.slice(7));
    if (selector.startsWith("#board-view ")) return doc.getElementById("board-view").querySelectorAll(selector.slice(12));
    if (selector.startsWith("#transition-dialog ")) return doc.getElementById("transition-dialog").querySelectorAll(selector.slice(20));
    return [];
  },
  addEventListener(type, fn) { (docListeners[type] = docListeners[type] || []).push(fn); },
  __listeners: docListeners,
  createElement(tag) { return makeElement("dyn-" + tag); },
};
doc.documentElement.setAttribute = function (name, value) { this.__attributes[name] = String(value); };
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
  clearTimeout() {},
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
  transitioned.facts.setup_state = "initialized";
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
if (checkTransitions) {
  regressionChecks.push(`
;(() => {
  const clone = value => JSON.parse(JSON.stringify(value));
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const makeReady = () => {
    const payload = clone(globalThis.transitionPayload);
    const sourcePath = "knowledge/wiki/features/F-001-ready-handoff.md";
    const feature = {
      id: "F-001", type: "feature", title: "Ready handoff", path: sourcePath, health: "ok", status: "specified", owner: "po", open_questions: [],
      transition: {
        version: 1, feature_id: "F-001", source_status: "specified", source_owner: "po", source_path: sourcePath,
        target_status: "ready-for-design", action: "po-handoff", classification: "ready", supported: true,
        checks: [{ code: "source-readable", status: "pass", message: "Feature source is readable.", path: sourcePath }],
        sources: [sourcePath, "knowledge/wiki/SCHEMA.md", "knowledge/wiki/index.md"],
        invocations: { codex: "$po-handoff F-001", claude: "/po-handoff F-001" }
      }
    };
    payload.root = "C:\\\\demo\\workspace";
    payload.workspace = { kind: "generated-project", project_name: "TreasuryFlow", platforms: ["backend"] };
    payload.facts.nodes = [feature];
    payload.facts.node_count = 1;
    payload.facts.edges = [];
    payload.facts.edge_count = 0;
    payload.facts.intake = { pending: ["first-brief.md"], quarantined: ["CONFLICT.md"] };
    payload.facts.transition_capability = {
      version: 1, mode: "copy-only", supported_actions: ["po-handoff"],
      snapshot: { fingerprint: "fp-1", observed_at: "2026-09-08T12:00:00+02:00", consistent: true },
      sources: [sourcePath, "knowledge/wiki/SCHEMA.md", "knowledge/wiki/index.md"],
      surfaces: [
        { role: "codex", path: "C:\\\\demo\\workspace\\.agents\\skills\\po-handoff\\SKILL.md", available: true, check: "pass", invocation_template: "$po-handoff F-XXX" },
        { role: "claude", path: "C:\\\\demo\\workspace\\.claude\\commands\\po-handoff.md", available: true, check: "pass", invocation_template: "/po-handoff F-XXX" },
      ],
    };
    payload.blocker_facts = [];
    return payload;
  };
  const ready = makeReady();
  adoptData(ready);
  switchView("board");
  renderBoard();
  const board = document.getElementById("board-view");
  const feature = ready.facts.nodes[0];
  const card = board.querySelectorAll(".card[data-id]").find(item => item.dataset.id === "F-001");
  const action = board.querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-001");
  assert(card && card.hasAttribute("draggable"), "supported feature card was not made draggable");
  assert(card.__listeners.keydown && card.__listeners.keydown.length, "feature card has no keyboard handler");
  assert(action && action.__listeners.click && action.__listeners.click.length, "Prepare handoff control was not wired");
  card.focus();
  card.__listeners.keydown[0]({ key: "Enter", preventDefault() {} });
  const panel = document.getElementById("panel");
  assert(panel.innerHTML.includes("Prepare handoff") && panel.querySelectorAll("[data-transition-id]").length, "inspector handoff control is missing");
  closePanel();
  action.__listeners.click[0]({ stopPropagation() {}, preventDefault() {} });
  const dialog = document.getElementById("transition-dialog");
  assert(!dialog.hidden && dialog.innerHTML.includes("Prepare handoff") && dialog.innerHTML.includes("Copy request") && dialog.innerHTML.includes("Cancel"), "handoff preview did not render");
  assert(document.getElementById("app-shell").hasAttribute("inert"), "modal did not inert the application background");
  assert(document.activeElement && document.activeElement.id === "transition-dialog-title", "modal did not move focus to its heading");
  assert(feature.status === "specified", "opening a preview changed the source stage");
  const before = JSON.stringify(feature);
  const dialogNode = dialog.querySelector(".transition-dialog");
  const focusCancel = dialogNode.querySelector("[data-transition-cancel]");
  const focusCopy = dialogNode.querySelector("[data-transition-copy]");
  const cancel = dialog.querySelector("[data-transition-cancel]");
  const copy = dialog.querySelector("[data-transition-copy]");
  assert(cancel && copy && dialogNode.__listeners.keydown && dialogNode.__listeners.keydown.length, "modal controls or focus handler are missing");
  const trap = dialogNode.querySelectorAll('button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
  document.activeElement = trap[trap.length - 1];
  dialogNode.__listeners.keydown[0]({ key: "Tab", shiftKey: false, preventDefault() {} });
  assert(document.activeElement === trap[0], "modal focus did not wrap: " + trap.length + " active=" + (document.activeElement && document.activeElement.id) + " first=" + (trap[0] && trap[0].id));
  globalThis.navigator = {};
  copy.__listeners.click[0]({ preventDefault() {} });
  assert(document.getElementById("transition-copy-status").textContent.includes("Clipboard unavailable") && document.getElementById("transition-copy-status").textContent.includes("manually"), "clipboard fallback was not exposed");
  cancel.__listeners.click[0]();
  assert(dialog.hidden && !document.getElementById("app-shell").hasAttribute("inert"), "cancel did not close and restore the background");
  assert(document.activeElement === action, "cancel did not restore focus to the source action");
  assert(JSON.stringify(feature) === before, "copy/cancel mutated source feature data");
  card.__listeners.keydown[0]({ key: "Enter", target: action, preventDefault() { throw new Error("card intercepted descendant control"); } });
  assert(document.getElementById("panel").hasAttribute("inert"), "card key handler intercepted a descendant action");

  let copied = "";
  globalThis.navigator = { clipboard: { writeText(value) { copied = value; return { then(done) { done(); return { catch() {} }; } }; } } };
  showTransitionPreview("F-001", action);
  const copyAgain = document.getElementById("transition-dialog").querySelector("[data-transition-copy]");
  copyAgain.__listeners.click[0]({ preventDefault() {} });
  assert(copied.includes("Workspace root (envelope.root): " + JSON.stringify(ready.root)), "copied request omitted the exact workspace root");
  assert(copied.includes("Feature ID: " + JSON.stringify("F-001")) && copied.includes("Source path: " + JSON.stringify(feature.path)), "copied request omitted exact feature identity/path");
  assert(copied.includes("Exact invocation: " + JSON.stringify("/po-handoff F-001")), "copied request omitted exact invocation");
  assert(copied.includes("CAPTURED SOURCE DATA") && copied.includes("INSTRUCTIONS") && copied.includes("No job was dispatched") === false, "copied request mixed status text into its instructions");
  assert(feature.status === "specified", "copy changed the source stage");
  const cancelAgain = document.getElementById("transition-dialog").querySelector("[data-transition-cancel]");
  cancelAgain.__listeners.click[0]();

  const missingSurface = makeReady();
  missingSurface.facts.nodes[0].transition.invocations.codex = "";
  adoptData(missingSurface); switchView("board"); renderBoard();
  const missingAction = document.getElementById("board-view").querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-001");
  missingAction.__listeners.click[0]({ stopPropagation() {}, preventDefault() {} });
  const missingDialog = document.getElementById("transition-dialog");
  const missingCodex = missingDialog.querySelector('[data-transition-surface="codex"]');
  assert(missingCodex && missingCodex.hasAttribute("aria-disabled") && missingDialog.innerHTML.includes("No generated Codex invocation"), "missing agent surface was presented as available");
  missingDialog.querySelector("[data-transition-cancel]").__listeners.click[0]();

  const sameDrop = makeReady();
  adoptData(sameDrop); switchView("board"); renderBoard();
  let sameCard = document.getElementById("board-view").querySelectorAll(".card[data-id]").find(item => item.dataset.id === "F-001");
  const columns = document.getElementById("board-view").querySelectorAll(".column[data-stage]");
  const specifiedColumn = columns.find(column => column.dataset.stage === "specified");
  const readyColumn = columns.find(column => column.dataset.stage === "ready-for-design");
  const invalidColumn = columns.find(column => column.dataset.stage === "in-design");
  const dataTransfer = { setData() {}, effectAllowed: "", dropEffect: "" };
  sameCard.__listeners.dragstart[0]({ currentTarget: sameCard, dataTransfer });
  sameCard.__listeners.dragend[0]({});
  assert(document.getElementById("transition-dialog").hidden, "dragend did not cancel the preview path");
  sameCard.__listeners.dragstart[0]({ currentTarget: sameCard, dataTransfer });
  specifiedColumn.__listeners.drop[0]({ currentTarget: specifiedColumn, preventDefault() {} });
  assert(document.getElementById("transition-dialog").hidden && sameDrop.facts.nodes[0].status === "specified", "same-column drop changed source state");
  sameCard.__listeners.dragstart[0]({ currentTarget: sameCard, dataTransfer });
  invalidColumn.__listeners.drop[0]({ currentTarget: invalidColumn, preventDefault() {} });
  assert(document.getElementById("transition-dialog").hidden && sameDrop.facts.nodes[0].status === "specified", "unsupported drop changed source state");
  sameCard.__listeners.dragstart[0]({ currentTarget: sameCard, dataTransfer });
  readyColumn.__listeners.drop[0]({ currentTarget: readyColumn, preventDefault() {} });
  assert(!document.getElementById("transition-dialog").hidden && sameDrop.facts.nodes[0].status === "specified", "supported drop did not open a source-preserving preview");
  document.getElementById("transition-dialog").querySelector("[data-transition-cancel]").__listeners.click[0]();

  const refreshStart = makeReady();
  adoptData(refreshStart); switchView("board"); renderBoard();
  const refreshCard = document.getElementById("board-view").querySelectorAll(".card[data-id]").find(item => item.dataset.id === "F-001");
  refreshCard.__listeners.dragstart[0]({ currentTarget: refreshCard, dataTransfer });
  const refreshChanged = makeReady();
  refreshChanged.facts.transition_capability.snapshot.fingerprint = "fp-refresh";
  adoptData(refreshChanged);
  assert(!state.drag && document.getElementById("sr-status").textContent.includes("active workflow drag canceled"), "live refresh did not cancel active drag");
  const refreshedAction = document.getElementById("board-view").querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-001");
  refreshedAction.__listeners.click[0]({ stopPropagation() {}, preventDefault() {} });
  const refreshAgain = makeReady();
  refreshAgain.facts.transition_capability.snapshot.fingerprint = "fp-refresh-again";
  adoptData(refreshAgain);
  const staleDialog = document.getElementById("transition-dialog");
  const staleCopy = staleDialog.querySelector("[data-transition-copy]");
  assert(!staleDialog.hidden && staleDialog.innerHTML.includes("capability changed") && staleCopy.hasAttribute("aria-disabled"), "live capability change did not stale an open preview");
  staleDialog.querySelector("[data-transition-cancel]").__listeners.click[0]();

  const old = makeReady();
  delete old.facts.transition_capability;
  adoptData(old); switchView("board"); renderBoard();
  const oldCard = document.getElementById("board-view").querySelectorAll(".card[data-id]").find(item => item.dataset.id === "F-001");
  const oldAction = document.getElementById("board-view").querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-001");
  assert(!oldCard.hasAttribute("draggable") && oldAction.hasAttribute("aria-disabled") && document.getElementById("board-view").innerHTML.includes("inspect-only"), "old capability did not fall back to inspect-only");
  const unavailable = makeReady();
  adoptData(unavailable); switchView("board"); renderBoard();
  markLiveRefreshUnavailable(42);
  const unavailableAction = document.getElementById("board-view").querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-001");
  assert(unavailableAction.hasAttribute("aria-disabled") && document.getElementById("board-view").innerHTML.includes("copying is disabled"), "failed live refresh did not disable handoff freshness");

  const mismatch = makeReady();
  mismatch.facts.nodes[0].owner = "designer";
  adoptData(mismatch); switchView("board"); renderBoard();
  const mismatchCard = document.getElementById("board-view").querySelectorAll(".card[data-id]").find(item => item.dataset.id === "F-001");
  assert(!mismatchCard.hasAttribute("draggable") && document.getElementById("board-view").innerHTML.includes("does not match"), "source/transition mismatch was offered as runnable");

  const duplicate = makeReady();
  const duplicateSecond = clone(duplicate.facts.nodes[0]);
  duplicateSecond.id = "F-001-copy";
  duplicate.facts.nodes[0].transition.feature_id = "F-DUP";
  duplicateSecond.transition.feature_id = "F-DUP";
  duplicate.facts.nodes = [duplicate.facts.nodes[0], duplicateSecond];
  duplicate.facts.node_count = 2;
  adoptData(duplicate); switchView("board"); renderBoard();
  const duplicateCards = document.getElementById("board-view").querySelectorAll(".card[data-id]");
  assert(duplicateCards.length === 2 && duplicateCards.every(item => !item.hasAttribute("draggable")), "duplicate canonical feature IDs were not inspect-only");

  const hostile = makeReady();
  const hostileFeature = hostile.facts.nodes[0];
  hostileFeature.title = "<img src=x onerror=alert(1)>";
  hostileFeature.path = "knowledge/wiki/features/hostile" + String.fromCharCode(10) + "<svg/onload=alert(2)>.md";
  hostileFeature.transition.source_path = hostileFeature.path;
  hostileFeature.transition.invocations.claude = '/po-handoff --feature "<script>alert(3)</script>"';
  hostileFeature.transition.checks[0].message = "<img src=x onerror=alert(4)>";
  adoptData(hostile); switchView("board"); renderBoard();
  const hostileAction = document.getElementById("board-view").querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-001");
  hostileAction.__listeners.click[0]({ stopPropagation() {}, preventDefault() {} });
  const hostileHtml = document.getElementById("transition-dialog").innerHTML;
  assert(hostileHtml.indexOf("<img") === -1 && hostileHtml.indexOf("<svg") === -1 && hostileHtml.indexOf("<script") === -1 && hostileHtml.includes("&lt;img"), "malformed transition context was rendered as markup");
  document.getElementById("transition-dialog").querySelector("[data-transition-cancel]").__listeners.click[0]();

  const intake = makeReady();
  adoptData(intake); switchView("board"); renderBoard();
  const intakeCard = document.getElementById("board-view").querySelectorAll(".card[data-intake]").find(item => item.dataset.name === "first-brief.md");
  intakeCard.focus();
  intakeCard.__listeners.keydown[0]({ key: "Enter", preventDefault() {} });
  assert(document.getElementById("panel").innerHTML.includes("first-brief.md"), "intake card had no keyboard access");
  closePanel();

  const replaced = makeReady();
  adoptData(replaced); switchView("board"); renderBoard();
  const replacedAction = document.getElementById("board-view").querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-001");
  replacedAction.focus();
  showTransitionPreview("F-001", replacedAction);
  assert(state.transitionPreview && !document.getElementById("transition-dialog").hidden, "replacement scenario did not open a preview");
  const nonFeature = makeReady();
  nonFeature.facts.nodes = [{ id: "F-001", type: "platform", title: "Reused identity", path: "knowledge/wiki/platforms/backend.md", health: "ok" }];
  nonFeature.facts.node_count = 1;
  nonFeature.facts.edges = [];
  nonFeature.facts.edge_count = 0;
  adoptData(nonFeature);
  const replacementDialog = document.getElementById("transition-dialog");
  assert(!state.transitionPreview && replacementDialog.hidden && !document.getElementById("app-shell").hasAttribute("inert"), "same-ID non-feature refresh left an active invisible preview");
  assert(document.getElementById("sr-status").textContent.includes("no longer supports this action"), "same-ID non-feature refresh did not announce the invalidation");
  assert(document.activeElement && document.activeElement.id === "board-view", "same-ID non-feature refresh did not recover Board focus");
  const globalKeydown = document.__listeners.keydown[0];
  globalKeydown({ key: "1" });
  assert(state.view === "firstrun", "keyboard shortcuts remained swallowed after invalid preview cleanup");
  globalKeydown({ key: "3" });

  const deleted = makeReady();
  adoptData(deleted); switchView("board"); renderBoard();
  const deletedCard = document.getElementById("board-view").querySelectorAll(".card[data-id]").find(item => item.dataset.id === "F-001");
  deletedCard.focus();
  deletedCard.__listeners.keydown[0]({ key: "Enter", preventDefault() {} });
  const deletedAction = document.getElementById("panel").querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-001");
  deletedAction.__listeners.click[0]({ stopPropagation() {}, preventDefault() {} });
  const removed = makeReady();
  removed.facts.nodes = []; removed.facts.node_count = 0;
  adoptData(removed);
  assert(document.getElementById("transition-dialog").hidden && document.getElementById("sr-status").textContent.includes("source was removed"), "deleted source did not invalidate open preview");
  assert(document.activeElement && document.activeElement.id === "board-view", "deleted source did not recover focus to the Board (active=" + (document.activeElement && document.activeElement.id) + ", view=" + state.view + ", preview=" + !!state.transitionPreview + ")");

  const priorEventSource = globalThis.EventSource;
  const priorFetch = globalThis.fetch;
  const priorSetTimeout = globalThis.setTimeout;
  const priorSetInterval = globalThis.setInterval;
  const priorClearTimeout = globalThis.clearTimeout;
  const liveSources = [];
  const liveTimers = [];
  let liveFetches = 0;
  let liveLastError = "";
  const liveChain = (value, failure) => ({
    then(onFulfilled) {
      if (failure) return this;
      try { return liveChain(onFulfilled(value), null); }
      catch (error) { return liveChain(null, error); }
    },
    catch(onRejected) {
      if (!failure) return this;
      liveLastError = failure && failure.message || String(failure);
      try { return liveChain(onRejected(failure), null); }
      catch (error) { return liveChain(null, error); }
    },
  });
  const liveEnvelope = makeReady();
  liveEnvelope.facts.transition_capability.snapshot.fingerprint = "fp-live";
  let livePayload = { version: 3, epoch: "first", envelope: liveEnvelope };
  globalThis.EventSource = function () { this.onmessage = null; this.onerror = null; liveSources.push(this); };
  globalThis.setTimeout = (callback, delay) => { liveTimers.push({ callback, delay }); return liveTimers.length; };
  globalThis.setInterval = () => 1;
  globalThis.clearTimeout = () => {};
  globalThis.fetch = () => {
    liveFetches += 1;
    return liveFetches === 1
      ? liveChain({ json() { throw new Error("temporary fetch failure"); } }, null)
      : liveChain({ json() { return livePayload; } }, null);
  };
  initLive();
  assert(liveSources.length === 1, "live mode did not create an EventSource");
  liveSources[0].onmessage({ data: "2", lastEventId: "first:2" });
  assert(liveFetches === 1, "first SSE event did not fetch the live snapshot");
  const retry = liveTimers.find(timer => timer.delay === 1500);
  assert(retry, "failed live fetch did not schedule a retry");
  retry.callback();
  assert(liveFetches === 2 && state.data === liveEnvelope && state.liveRefreshError === null, "scheduled live retry did not adopt the successful snapshot (fetches=" + liveFetches + ", same=" + (state.data === liveEnvelope) + ", error=" + state.liveRefreshError + ", last=" + liveLastError + ")");
  liveSources[0].onmessage({ data: "3", lastEventId: "first:3" });
  assert(liveFetches === 2, "live client did not advance from payload.version and coalesce the adopted event");
  liveSources[0].onerror();
  assert(state.liveRefreshError, "disconnect must disable copying stale facts");
  livePayload = { version: 1, epoch: "restarted", envelope: JSON.parse(JSON.stringify(liveEnvelope)) };
  liveSources[0].onmessage({ data: "1", lastEventId: "restarted:1" });
  assert(liveFetches === 3 && state.data === livePayload.envelope && !state.liveRefreshError, "server restart did not adopt its lower version");
  livePayload = { version: 2, epoch: "restarted", envelope: JSON.parse(JSON.stringify(liveEnvelope)) };
  liveSources[0].onmessage({ data: "2", lastEventId: "restarted:2" });
  assert(liveFetches === 4 && state.data === livePayload.envelope, "post-restart update was ignored");
  globalThis.EventSource = priorEventSource;
  globalThis.fetch = priorFetch;
  globalThis.setTimeout = priorSetTimeout;
  globalThis.setInterval = priorSetInterval;
  globalThis.clearTimeout = priorClearTimeout;

  const actionSpecs = {
    "po-specify": { source_status: "raw", source_owner: "po", target_status: "specified", target_owner: "po", command: "po-specify" },
    "po-handoff": { source_status: "specified", source_owner: "po", target_status: "ready-for-design", target_owner: "designer", command: "po-handoff" },
    "design-start": { source_status: "ready-for-design", source_owner: "designer", target_status: "in-design", target_owner: "designer", command: "design-start" },
    "design-handoff": { source_status: "in-design", source_owner: "designer", target_status: "ready-for-dev", target_owner: "dev", command: "design-handoff" },
    "dev-start": { source_status: "ready-for-dev", source_owner: "dev", target_status: "in-dev", target_owner: "dev", command: "dev-start" },
    "dev-done": { source_status: "in-dev", source_owner: "dev", target_status: "done", target_owner: "none", command: "dev-done" },
    "reopen-spec": { source_status: "done", source_owner: "none", target_status: "specified", target_owner: "po", command: "feature-reopen" },
    "reopen-design": { source_status: "done", source_owner: "none", target_status: "in-design", target_owner: "designer", command: "feature-reopen" },
    "reopen-dev": { source_status: "done", source_owner: "none", target_status: "in-dev", target_owner: "dev", command: "feature-reopen" },
  };
  const makeLifecycleAction = (id, path, action) => {
    const spec = actionSpecs[action];
    const suffix = spec.command === "feature-reopen" ? " " + spec.target_status : "";
    return {
      version: 1, feature_id: id, source_status: spec.source_status, source_owner: spec.source_owner, source_path: path,
      target_status: spec.target_status, target_owner: spec.target_owner, action, classification: "ready", supported: true,
      checks: [{ code: "source-readable", status: "pass", message: "Feature source is readable.", path }],
      sources: [path, "knowledge/wiki/SCHEMA.md", "knowledge/wiki/index.md"],
      invocations: { codex: "$" + spec.command + " " + id + suffix, claude: "/" + spec.command + " " + id + suffix },
    };
  };
  const makeLifecycleFeature = (id, title, action) => {
    const path = "knowledge/wiki/features/" + id + ".md";
    const primary = makeLifecycleAction(id, path, action);
    return { id, type: "feature", title, path, health: "ok", status: primary.source_status, owner: primary.source_owner, open_questions: [], transition: primary, transitions: [primary] };
  };
  const makeDoneFeature = id => {
    const path = "knowledge/wiki/features/" + id + ".md";
    const transitions = ["reopen-spec", "reopen-design", "reopen-dev"].map(action => makeLifecycleAction(id, path, action));
    return {
      id, type: "feature", title: "Done feature", path, health: "ok", status: "done", owner: "none", open_questions: [],
      transition: { version: 1, feature_id: id, source_status: "done", source_owner: "none", target_status: "done", target_owner: "none", action: null, classification: "unknown", supported: false, checks: [], sources: [], invocations: {} },
      transitions,
    };
  };
  const makeV2Payload = () => {
    const payload = clone(globalThis.transitionPayload);
    const features = [
      makeLifecycleFeature("F-raw", "Raw feature", "po-specify"),
      makeLifecycleFeature("F-specified", "Specified feature", "po-handoff"),
      makeLifecycleFeature("F-ready-design", "Ready for design", "design-start"),
      makeLifecycleFeature("F-in-design", "In design", "design-handoff"),
      makeLifecycleFeature("F-ready-dev", "Ready for development", "dev-start"),
      makeLifecycleFeature("F-in-dev", "In development", "dev-done"),
      makeDoneFeature("F-done"),
    ];
    const supportedActions = Object.keys(actionSpecs);
    const surfaces = [];
    supportedActions.forEach(action => {
      surfaces.push({ role: "codex", action, path: "C:/demo/workspace/.agents/skills/" + actionSpecs[action].command + "/SKILL.md", available: true, check: "pass", invocation_template: "$" + actionSpecs[action].command + " F-XXX" });
      surfaces.push({ role: "claude", action, path: "C:/demo/workspace/.claude/commands/" + actionSpecs[action].command + ".md", available: true, check: "pass", invocation_template: "/" + actionSpecs[action].command + " F-XXX" });
    });
    payload.root = "C:/demo/workspace";
    payload.workspace = { kind: "generated-project", project_name: "TreasuryFlow", platforms: ["backend", "android", "ios"] };
    payload.facts.nodes = features;
    payload.facts.node_count = features.length;
    payload.facts.edges = [];
    payload.facts.edge_count = 0;
    payload.facts.intake = { pending: ["first-brief.md"], quarantined: ["CONFLICT.md"] };
    payload.facts.transition_capability = {
      version: 2, mode: "copy-only", supported_actions: supportedActions, surfaces,
      snapshot: { fingerprint: "fp-v2", observed_at: "2026-09-08T12:00:00+02:00", consistent: true },
      sources: ["knowledge/wiki/SCHEMA.md", "knowledge/wiki/index.md"],
    };
    payload.blocker_facts = [];
    return payload;
  };

  const lifecycle = makeV2Payload();
  adoptData(lifecycle);
  switchView("board");
  renderBoard();
  const lifecycleBoard = document.getElementById("board-view");
  const lifecycleCard = id => lifecycleBoard.querySelectorAll(".card[data-id]").find(item => item.dataset.id === id);
  const lifecycleAction = id => lifecycleBoard.querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === id);
  [
    ["F-raw", "Prepare specification", "specified"],
    ["F-specified", "Prepare handoff", "ready-for-design"],
    ["F-ready-design", "Prepare design start", "in-design"],
    ["F-in-design", "Prepare development handoff", "ready-for-dev"],
    ["F-ready-dev", "Prepare development start", "in-dev"],
    ["F-in-dev", "Prepare completion", "done"],
  ].forEach(([id, label, target]) => {
    const control = lifecycleAction(id);
    assert(control && control.textContent.includes(label) && lifecycle.facts.nodes.find(node => node.id === id).status !== target, "lifecycle action was not rendered or changed source state: " + id);
  });
  const doneNode = lifecycle.facts.nodes.find(node => node.id === "F-done");
  const doneCard = lifecycleCard("F-done");
  const doneAction = lifecycleAction("F-done");
  const doneSelect = lifecycleBoard.querySelectorAll("[data-transition-select]").find(item => item.dataset.transitionSelectId === "F-done");
  assert(doneCard && doneCard.hasAttribute("draggable") && doneSelect && doneAction && doneAction.hasAttribute("aria-disabled") && doneAction.dataset.transitionIndex === "", "Done did not require an explicit reopen route");
  const selectedBeforePickerClick = state.selected;
  doneSelect.closest = selector => selector === "button, select, label" ? doneSelect : null;
  doneCard.__listeners.click[0]({ target: doneSelect });
  assert(state.selected === selectedBeforePickerClick, "pointer click on the Done route picker opened the feature inspector");
  showTransitionPreview("F-done", doneAction);
  assert(!state.transitionPreview && document.getElementById("transition-dialog").hidden && document.getElementById("sr-status").textContent.includes("Choose a workflow destination"), "Done preview silently selected a reopen route");
  doneSelect.value = "1";
  doneSelect.__listeners.change[0]({ target: doneSelect });
  assert(doneAction.dataset.transitionIndex === "1" && doneAction.textContent.includes("reopen for design") && !doneAction.hasAttribute("aria-disabled"), "Done route selection did not enable the selected action");
  const doneBefore = JSON.stringify(doneNode);
  doneAction.__listeners.click[0]({ stopPropagation() {}, preventDefault() {} });
  let lifecycleCopied = "";
  globalThis.navigator = { clipboard: { writeText(value) { lifecycleCopied = value; return { then(done) { done(); return { catch() {} }; } }; } } };
  const lifecycleDialog = document.getElementById("transition-dialog");
  const codexSurface = lifecycleDialog.querySelector('[data-transition-surface="codex"]');
  assert(codexSurface && !codexSurface.hasAttribute("aria-disabled"), "available v2 Codex surface was not exposed");
  codexSurface.__listeners.click[0]({ preventDefault() {} });
  lifecycleDialog.querySelector("[data-transition-copy]").__listeners.click[0]({ preventDefault() {} });
  assert(lifecycleCopied.includes("Exact invocation: " + JSON.stringify("$feature-reopen F-done in-design")) && JSON.stringify(doneNode) === doneBefore, "selected Done request copied the wrong invocation or changed source state");
  lifecycleDialog.querySelector("[data-transition-cancel]").__listeners.click[0]();
  selectNode("F-done");
  const donePanel = document.getElementById("panel");
  const donePanelSelect = donePanel.querySelectorAll("[data-transition-select]").find(item => item.dataset.transitionSelectId === "F-done");
  const donePanelAction = donePanel.querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-done");
  assert(donePanelSelect && donePanelAction && donePanelAction.hasAttribute("aria-disabled"), "inspector omitted explicit Done route selection");
  donePanelSelect.value = "2";
  donePanelSelect.__listeners.change[0]({ target: donePanelSelect });
  assert(donePanelAction.dataset.transitionIndex === "2" && donePanelAction.textContent.includes("reopen for development"), "inspector Done route selection did not update the action");
  donePanelAction.__listeners.click[0]({ stopPropagation() {}, preventDefault() {} });
  assert(state.transitionPreview && doneNode.status === "done" && document.getElementById("transition-dialog").innerHTML.includes("reopen-dev"), "inspector selected route did not open a source-preserving preview");
  document.getElementById("transition-dialog").querySelector("[data-transition-cancel]").__listeners.click[0]();
  closePanel();

  const targetDrops = [["specified", "reopen-spec"], ["in-design", "reopen-design"], ["in-dev", "reopen-dev"]];
  const dataTransferV2 = { setData() {}, effectAllowed: "", dropEffect: "" };
  for (const [stage, action] of targetDrops) {
    const target = lifecycleBoard.querySelectorAll(".column[data-stage]").find(column => column.dataset.stage === stage);
    doneCard.__listeners.dragstart[0]({ currentTarget: doneCard, dataTransfer: dataTransferV2 });
    target.__listeners.drop[0]({ currentTarget: target, preventDefault() {} });
    assert(state.transitionPreview && document.getElementById("transition-dialog").innerHTML.includes(action) && doneNode.status === "done", "drop did not select source-preserving route " + action);
    document.getElementById("transition-dialog").querySelector("[data-transition-cancel]").__listeners.click[0]();
  }
  const doneColumn = lifecycleBoard.querySelectorAll(".column[data-stage]").find(column => column.dataset.stage === "done");
  doneCard.__listeners.dragstart[0]({ currentTarget: doneCard, dataTransfer: dataTransferV2 });
  doneColumn.__listeners.drop[0]({ currentTarget: doneColumn, preventDefault() {} });
  assert(!state.transitionPreview && doneNode.status === "done", "same-column Done drop created a transition");
  const unsupportedColumn = lifecycleBoard.querySelectorAll(".column[data-stage]").find(column => column.dataset.stage === "ready-for-design");
  doneCard.__listeners.dragstart[0]({ currentTarget: doneCard, dataTransfer: dataTransferV2 });
  unsupportedColumn.__listeners.drop[0]({ currentTarget: unsupportedColumn, preventDefault() {} });
  assert(!state.transitionPreview && doneNode.status === "done", "unsupported Done drop moved or previewed a route");

  const changedStart = makeV2Payload();
  adoptData(changedStart); switchView("board"); renderBoard();
  const changedAction = document.getElementById("board-view").querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-done");
  showTransitionPreview("F-done", changedAction, 1);
  const changedTarget = clone(changedStart);
  changedTarget.facts.nodes.find(node => node.id === "F-done").transitions[1].target_status = "specified";
  adoptData(changedTarget);
  assert(state.transitionPreview && document.getElementById("transition-dialog").innerHTML.includes("capability changed") && document.getElementById("transition-dialog").querySelector("[data-transition-copy]").hasAttribute("aria-disabled"), "changed target did not stale an open route preview");
  document.getElementById("transition-dialog").querySelector("[data-transition-cancel]").__listeners.click[0]();
  const removedTarget = makeV2Payload();
  adoptData(removedTarget); switchView("board"); renderBoard();
  const removedAction = document.getElementById("board-view").querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-done");
  showTransitionPreview("F-done", removedAction, 1);
  const removedRoute = clone(removedTarget);
  removedRoute.facts.nodes.find(node => node.id === "F-done").transitions.splice(1, 2);
  adoptData(removedRoute);
  assert(!state.transitionPreview && document.getElementById("transition-dialog").hidden && !document.getElementById("app-shell").hasAttribute("inert"), "removed selected route left a modal state active");

  const emptyCapability = makeV2Payload();
  emptyCapability.facts.transition_capability.supported_actions = [];
  adoptData(emptyCapability); switchView("board"); renderBoard();
  const emptyCard = document.getElementById("board-view").querySelectorAll(".card[data-id]").find(item => item.dataset.id === "F-raw");
  const emptyAction = document.getElementById("board-view").querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-raw");
  assert(!emptyCard.hasAttribute("draggable") && emptyAction && document.getElementById("board-view").innerHTML.includes("not exposed"), "empty supported_actions advertised a draggable action");
  emptyAction.__listeners.click[0]({ stopPropagation() {}, preventDefault() {} });
  assert(!document.getElementById("transition-dialog").hidden && document.getElementById("transition-dialog").querySelector("[data-transition-copy]").hasAttribute("aria-disabled"), "unadvertised action did not remain inspect-only");
  document.getElementById("transition-dialog").querySelector("[data-transition-cancel]").__listeners.click[0]();
  const missingArray = makeV2Payload();
  delete missingArray.facts.nodes.find(node => node.id === "F-raw").transitions;
  adoptData(missingArray); switchView("board"); renderBoard();
  const missingArrayCard = document.getElementById("board-view").querySelectorAll(".card[data-id]").find(item => item.dataset.id === "F-raw");
  assert(!missingArrayCard.hasAttribute("draggable"), "v2 singular fallback bypassed the required transitions array");

  const mismatchId = makeV2Payload();
  mismatchId.facts.nodes.find(node => node.id === "F-done").transitions[1].feature_id = "F-other";
  adoptData(mismatchId); switchView("board"); renderBoard();
  const mismatchIdCard = document.getElementById("board-view").querySelectorAll(".card[data-id]").find(item => item.dataset.id === "F-done");
  const mismatchIdSelect = document.getElementById("board-view").querySelectorAll("[data-transition-select]").find(item => item.dataset.transitionSelectId === "F-done");
  const mismatchIdAction = document.getElementById("board-view").querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-done");
  mismatchIdSelect.value = "1";
  mismatchIdSelect.__listeners.change[0]({ target: mismatchIdSelect });
  assert(mismatchIdCard.hasAttribute("draggable") && mismatchIdAction.hasAttribute("aria-disabled") && mismatchIdAction.textContent.includes("reopen for design") && mismatchIdAction.getAttribute("title").includes("feature ID does not match"), "mismatched transition feature ID was offered as runnable: drag=" + mismatchIdCard.hasAttribute("draggable") + ", disabled=" + mismatchIdAction.hasAttribute("aria-disabled") + ", value=" + mismatchIdSelect.value + ", listeners=" + ((mismatchIdSelect.__listeners.change || []).length) + ", id=" + mismatchIdSelect.dataset.transitionSelectId + ", text=" + mismatchIdAction.textContent + ", title=" + mismatchIdAction.getAttribute("title"));

  const ambiguous = makeV2Payload();
  const ambiguousFeature = ambiguous.facts.nodes.find(node => node.id === "F-raw");
  const ambiguousDuplicate = clone(ambiguousFeature.transitions[0]);
  ambiguousDuplicate.target_status = "in-dev";
  ambiguousFeature.transitions.push(ambiguousDuplicate);
  adoptData(ambiguous); switchView("board"); renderBoard();
  const ambiguousCard = document.getElementById("board-view").querySelectorAll(".card[data-id]").find(item => item.dataset.id === "F-raw");
  assert(!ambiguousCard.hasAttribute("draggable") && document.getElementById("board-view").innerHTML.includes("No workflow action is supplied"), "ambiguous duplicate action IDs were silently accepted");

  const inherited = makeV2Payload();
  const inheritedFeature = inherited.facts.nodes.find(node => node.id === "F-raw");
  inheritedFeature.transitions[0].action = "__proto__";
  inherited.facts.transition_capability.supported_actions = ["__proto__"];
  adoptData(inherited); switchView("board"); renderBoard();
  const inheritedCard = document.getElementById("board-view").querySelectorAll(".card[data-id]").find(item => item.dataset.id === "F-raw");
  assert(!inheritedCard.hasAttribute("draggable") && document.getElementById("board-view").innerHTML.includes("unavailable in this capability version"), "inherited action name bypassed the lifecycle allowlist");

  const wrongV1 = makeReady();
  wrongV1.facts.nodes[0].transition.target_status = "in-design";
  adoptData(wrongV1); switchView("board"); renderBoard();
 const wrongV1Card = document.getElementById("board-view").querySelectorAll(".card[data-id]").find(item => item.dataset.id === "F-001");
 assert(!wrongV1Card.hasAttribute("draggable") && document.getElementById("board-view").innerHTML.includes("unavailable in this capability version"), "legacy v1 accepted a wrong source/target mapping");

  const priorSurface = state.surface;
  state.surface = "codex";
  const nonPassSurface = makeV2Payload();
  nonPassSurface.facts.transition_capability.surfaces.find(entry => entry.role === "codex" && entry.action === "po-specify").check = "unknown";
  adoptData(nonPassSurface); switchView("board"); renderBoard();
  const nonPassAction = document.getElementById("board-view").querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-raw");
  nonPassAction.__listeners.click[0]({ stopPropagation() {}, preventDefault() {} });
  const nonPassDialog = document.getElementById("transition-dialog");
  assert(nonPassDialog.querySelector("[data-transition-copy]").hasAttribute("aria-disabled") && nonPassDialog.innerHTML.includes("No generated Codex invocation"), "non-pass v2 surface was treated as copy-ready");
  nonPassDialog.querySelector("[data-transition-cancel]").__listeners.click[0]();

  for (const field of ["fingerprint", "observed_at"]) {
    const blankSnapshot = makeV2Payload();
    blankSnapshot.facts.transition_capability.snapshot[field] = "   ";
    adoptData(blankSnapshot); switchView("board"); renderBoard();
    const blankCard = document.getElementById("board-view").querySelectorAll(".card[data-id]").find(item => item.dataset.id === "F-raw");
    assert(!blankCard.hasAttribute("draggable"), "blank snapshot " + field + " was accepted as capability-ready");
  }

  const wrongInvocation = makeV2Payload();
  wrongInvocation.facts.nodes.find(node => node.id === "F-specified").transitions[0].invocations.codex = "$design-start F-specified";
  adoptData(wrongInvocation); switchView("board"); renderBoard();
  const wrongInvocationAction = document.getElementById("board-view").querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-specified");
  wrongInvocationAction.__listeners.click[0]({ stopPropagation() {}, preventDefault() {} });
  const wrongInvocationDialog = document.getElementById("transition-dialog");
  assert(wrongInvocationDialog.querySelector("[data-transition-copy]").hasAttribute("aria-disabled") && wrongInvocationDialog.innerHTML.includes("No generated Codex invocation"), "wrong action invocation was copied");
  wrongInvocationDialog.querySelector("[data-transition-cancel]").__listeners.click[0]();

  const wrongReopenInvocation = makeV2Payload();
  wrongReopenInvocation.facts.nodes.find(node => node.id === "F-done").transitions[1].invocations.codex = "$feature-reopen F-done";
  adoptData(wrongReopenInvocation); switchView("board"); renderBoard();
  const wrongReopenSelect = document.getElementById("board-view").querySelectorAll("[data-transition-select]").find(item => item.dataset.transitionSelectId === "F-done");
  wrongReopenSelect.value = "1";
  wrongReopenSelect.__listeners.change[0]({ target: wrongReopenSelect });
  const wrongReopenAction = document.getElementById("board-view").querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-done");
  wrongReopenAction.__listeners.click[0]({ stopPropagation() {}, preventDefault() {} });
  const wrongReopenDialog = document.getElementById("transition-dialog");
  assert(wrongReopenDialog.querySelector("[data-transition-copy]").hasAttribute("aria-disabled") && wrongReopenDialog.innerHTML.includes("No generated Codex invocation"), "reopen invocation without its concrete target was copied");
  wrongReopenDialog.querySelector("[data-transition-cancel]").__listeners.click[0]();
  state.surface = priorSurface;
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
if (checkTransitions) console.log("TRANSITIONS OK - copy-only preview, source-preserving drag, refresh invalidation, and safe fallback passed");
// sanity: header + views wired
const viewsEl = elements["views"];
if (viewsEl && viewsEl.__listeners.click) console.log("EVENTS OK — view switcher has click handler");
else { console.error("EVENTS MISSING — view switcher not wired"); process.exit(1); }
