// Runtime boot harness for the Prism dashboard inline script.
// Stubs just enough DOM to execute the whole boot sequence and surface
// runtime errors (TDZ, undefined refs) that `node --check` cannot catch.
// Usage: node boot_harness.js <exported-dashboard.html> [--check-guide-transition] [--check-escaping] [--check-health-labels] [--check-view-accessibility] [--check-unknown-stage] [--check-transitions] [--check-connected-board] [--check-board-defects]

const fs = require("fs");

const htmlPath = process.argv[2];
const html = fs.readFileSync(htmlPath, "utf-8");
const checkGuideTransition = process.argv.includes("--check-guide-transition");
const checkEscaping = process.argv.includes("--check-escaping");
const checkHealthLabels = process.argv.includes("--check-health-labels");
const checkViewAccessibility = process.argv.includes("--check-view-accessibility");
const checkUnknownStage = process.argv.includes("--check-unknown-stage");
const checkTransitions = process.argv.includes("--check-transitions");
const checkConnectedBoard = process.argv.includes("--check-connected-board");
const checkBoardDefects = process.argv.includes("--check-board-defects");

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
    const dataAttribute = value.match(/^\[([\w-]+)\]$/);
    if (dataAttribute && dataAttribute[1].startsWith("data-")) return attrs[dataAttribute[1]] !== undefined;
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
    if (value === "summary") return tag === "summary";
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
      if (name === "disabled") this.disabled = true;
      if (name === "checked") this.checked = true;
    },
    removeAttribute(name) {
      delete this.__attributes[name];
      if (name.startsWith("data-")) delete this.dataset[name.slice(5).replace(/-([a-z])/g, (_m, ch) => ch.toUpperCase())];
      if (name === "hidden") this.hidden = false;
      if (name === "disabled") this.disabled = false;
      if (name === "checked") this.checked = false;
    },
    hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.__attributes, name); },
    getAttributeNames() { return Object.keys(this.__attributes); },
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
          if (attrs.disabled !== undefined) node.disabled = true;
          if (attrs.checked !== undefined) node.checked = true;
          if (tag === "textarea") node.value = node.textContent;
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
    const roots = ["panel", "transition-dialog", "board-view", "app-view", "firstrun-view", "graph-view", "views", "toolbar"];
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
    if (selector === "#dashboard .view") return ["firstrun-view", "graph-view", "board-view", "app-view"].map(id => doc.getElementById(id));
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
function syncChain(value, failure) {
  const settle = result => result && result.__syncChain ? result : syncChain(result);
  return {
    __syncChain: true,
    value,
    failure,
    then(onFulfilled, onRejected) {
      if (failure) return onRejected ? settle(onRejected(failure)) : syncChain(null, failure);
      try { return onFulfilled ? settle(onFulfilled(value)) : syncChain(value); }
      catch (error) { return syncChain(null, error); }
    },
    catch(onRejected) {
      if (!failure) return syncChain(value);
      try { return onRejected ? settle(onRejected(failure)) : syncChain(null, failure); }
      catch (error) { return syncChain(null, error); }
    },
  };
}
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
  fetch() { return new Promise(() => {}); },
  ForceGraph: () => makeChain(),
  console,
};
sandbox.globalThis = sandbox;
sandbox.__syncChain = syncChain;
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
    { id: "app:web", type: "app", title: "<svg/onload=alert(4)>", path: null, health: "ok" },
  ];
  escaped.facts.node_count = 2;
  escaped.facts.edges = [{ source: maliciousId, target: "app:web", kind: "<img src=x>", evidence: "malformed id" }];
  escaped.facts.edge_count = 1;
  escaped.facts.intake = { pending: [], quarantined: [] };
  escaped.blocker_facts = [{ feature_id: maliciousId, code: "pending-board-review", message: "<svg/onload=alert(5)>" }];
  adoptData(escaped);
  renderBoard();
  selectNode(maliciousId);
  globalThis.__escapingHtml = {
    board: document.getElementById("board-view").innerHTML,
    app: document.getElementById("app-view").innerHTML,
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
  state.boardConnection = "unsupported";
  const makeReady = () => {
    const payload = clone(globalThis.transitionPayload);
    const sourcePath = "knowledge/wiki/features/F-001-ready-handoff.md";
    const feature = {
      id: "F-001", type: "feature", title: "Ready handoff", path: sourcePath, health: "ok", status: "specified", owner: "po", open_questions: [],
      transitions: [{
        version: 2, feature_id: "F-001", source_status: "specified", source_owner: "po", source_path: sourcePath,
        target_status: "ready-for-design", target_owner: "designer", action: "po-handoff", classification: "ready", supported: true,
        checks: [{ code: "source-readable", status: "pass", message: "Feature source is readable.", path: sourcePath }],
        sources: [sourcePath, "knowledge/wiki/SCHEMA.md", "knowledge/wiki/status-board.md"],
        invocations: { codex: "$po-handoff F-001", claude: "/po-handoff F-001" }
      }]
    };
    payload.root = "C:\\\\demo\\workspace";
    payload.workspace = { kind: "generated-project", project_name: "TreasuryFlow", apps: [{ id: "backend" }] };
    payload.facts.nodes = [feature];
    payload.facts.node_count = 1;
    payload.facts.edges = [];
    payload.facts.edge_count = 0;
    payload.facts.intake = { pending: ["first-brief.md"], quarantined: ["CONFLICT.md"] };
    payload.facts.transition_capability = {
      version: 3, mode: "copy-only", supported_actions: ["po-handoff"],
      snapshot: { fingerprint: "fp-1", observed_at: "2026-09-08T12:00:00+02:00", consistent: true },
      sources: [sourcePath, "knowledge/wiki/SCHEMA.md", "knowledge/wiki/status-board.md"],
      surfaces: [
        { role: "codex", action: "po-handoff", path: "C:\\\\demo\\workspace\\.agents\\skills\\po-handoff\\SKILL.md", available: true, check: "pass", invocation_template: "$po-handoff F-XXX" },
        { role: "claude", action: "po-handoff", path: "C:\\\\demo\\workspace\\.claude\\commands\\po-handoff.md", available: true, check: "pass", invocation_template: "/po-handoff F-XXX" },
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
  missingSurface.facts.nodes[0].transitions[0].invocations.codex = "";
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
  duplicate.facts.nodes[0].transitions[0].feature_id = "F-DUP";
  duplicateSecond.transitions[0].feature_id = "F-DUP";
  duplicate.facts.nodes = [duplicate.facts.nodes[0], duplicateSecond];
  duplicate.facts.node_count = 2;
  adoptData(duplicate); switchView("board"); renderBoard();
  const duplicateCards = document.getElementById("board-view").querySelectorAll(".card[data-id]");
  assert(duplicateCards.length === 2 && duplicateCards.every(item => !item.hasAttribute("draggable")), "duplicate canonical feature IDs were not inspect-only");

  const hostile = makeReady();
  const hostileFeature = hostile.facts.nodes[0];
  hostileFeature.title = "<img src=x onerror=alert(1)>";
  hostileFeature.path = "knowledge/wiki/features/hostile" + String.fromCharCode(10) + "<svg/onload=alert(2)>.md";
  hostileFeature.transitions[0].source_path = hostileFeature.path;
  hostileFeature.transitions[0].invocations.claude = '/po-handoff --feature "<script>alert(3)</script>"';
  hostileFeature.transitions[0].checks[0].message = "<img src=x onerror=alert(4)>";
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
  nonFeature.facts.nodes = [{ id: "F-001", type: "app", title: "Reused identity", path: "knowledge/wiki/apps/backend.md", health: "ok" }];
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
  let failNextLiveFetches = 0;
  globalThis.EventSource = function () { this.onmessage = null; this.onerror = null; liveSources.push(this); };
  globalThis.setTimeout = (callback, delay) => { liveTimers.push({ callback, delay }); return liveTimers.length; };
  globalThis.setInterval = () => 1;
  globalThis.clearTimeout = () => {};
  globalThis.fetch = () => {
    liveFetches += 1;
    if (failNextLiveFetches > 0) {
      failNextLiveFetches -= 1;
      return liveChain({ json() { throw new Error("temporary fetch failure"); } }, null);
    }
    return liveChain({ ok: true, json() { return livePayload; } }, null);
  };
  adoptData(liveEnvelope); switchView("board"); renderBoard();
  const liveAction = document.getElementById("board-view").querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-001");
  liveAction.__listeners.click[0]({ stopPropagation() {}, preventDefault() {} });
  const liveDialog = document.getElementById("transition-dialog");
  assert(!liveDialog.querySelector("[data-transition-copy]").hasAttribute("aria-disabled"), "live recovery fixture did not start with an available Copy action");
  document.getElementById("sr-status").textContent = "";
  initLive();
  assert(liveSources.length === 1, "live mode did not create an EventSource");
  liveSources[0].onmessage({ data: "3", lastEventId: "first:3" });
  assert(liveFetches === 1 && state.data === liveEnvelope && state.liveRefreshError === null, "initial epoch greeting did not adopt a healthy live snapshot");
  assert(!document.getElementById("sr-status").textContent.includes("Live refresh unavailable"), "initial epoch greeting was announced as a server restart");
  assert(!liveDialog.querySelector("[data-transition-copy]").hasAttribute("aria-disabled"), "initial epoch greeting incorrectly staled an open preview");
  livePayload = { version: 4, epoch: "first", envelope: liveEnvelope };
  liveSources[0].onmessage({ data: "4", lastEventId: "first:4" });
  assert(liveFetches === 2 && state.data === livePayload.envelope && state.liveRefreshError === null, "new same-server version was not adopted");
  liveSources[0].onmessage({ data: "4", lastEventId: "first:4" });
  assert(liveFetches === 2, "healthy duplicate event caused an unnecessary snapshot fetch");
  liveSources[0].onerror();
  const freshness = document.getElementById("freshness");
  const copyAfterDisconnect = liveDialog.querySelector("[data-transition-copy]");
  assert(state.liveRefreshError && freshness.innerHTML.includes('class="live-dot stale"') && freshness.innerHTML.includes("STALE"), "disconnect did not render stale header state after the normal header rebuild");
  assert(copyAfterDisconnect.hasAttribute("aria-disabled") && liveDialog.innerHTML.includes("Copy is disabled"), "disconnect did not revoke Copy from the already-open preview");
  failNextLiveFetches = 1;
  liveSources[0].onmessage({ data: "4", lastEventId: "first:4" });
  assert(liveFetches === 3, "same-epoch reconnect with the same version did not request a fresh snapshot");
  const copyAfterReconnect = liveDialog.querySelector("[data-transition-copy]");
  assert(state.liveRefreshError && freshness.innerHTML.includes('class="live-dot stale"') && copyAfterReconnect.hasAttribute("aria-disabled"), "reconnect notice cleared stale state before snapshot validation succeeded");
  const retry = liveTimers.filter(timer => timer.delay === 1500).at(-1);
  assert(retry, "failed same-version reconnect refresh did not schedule a retry");
  retry.callback();
  assert(liveFetches === 4 && state.data === livePayload.envelope && state.liveRefreshError === null, "successful same-version retry did not restore the validated live snapshot (fetches=" + liveFetches + ", same=" + (state.data === livePayload.envelope) + ", error=" + state.liveRefreshError + ", last=" + liveLastError + ")");
  assert(freshness.innerHTML.includes('class="live-dot"') && freshness.innerHTML.includes("LIVE") && !freshness.innerHTML.includes("stale"), "validated recovery did not restore the healthy header indicator");
  const copyAfterRecovery = liveDialog.querySelector("[data-transition-copy]");
  assert(copyAfterRecovery.hasAttribute("aria-disabled") && liveDialog.innerHTML.includes("Copy is disabled until this feature is refreshed and reviewed again"), "recovery silently approved the preview that was open during the disconnect");
  liveDialog.querySelector("[data-transition-cancel]").__listeners.click[0]();
  const recoveredAction = document.getElementById("board-view").querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-001");
  recoveredAction.__listeners.click[0]({ stopPropagation() {}, preventDefault() {} });
  const recoveredDialog = document.getElementById("transition-dialog");
  assert(!recoveredDialog.querySelector("[data-transition-copy]").hasAttribute("aria-disabled"), "fresh preview remained disabled after validated same-version recovery");
  recoveredDialog.querySelector("[data-transition-cancel]").__listeners.click[0]();
  liveSources[0].onmessage({ data: "4", lastEventId: "first:4" });
  assert(liveFetches === 4, "live client did not coalesce a healthy duplicate event after recovery");
  liveSources[0].onerror();
  livePayload = { version: 1, epoch: "restarted", envelope: JSON.parse(JSON.stringify(liveEnvelope)) };
  liveSources[0].onmessage({ data: "1", lastEventId: "restarted:1" });
  assert(liveFetches === 5 && state.data === livePayload.envelope && !state.liveRefreshError, "server restart did not adopt its lower version");
  livePayload = { version: 2, epoch: "restarted", envelope: JSON.parse(JSON.stringify(liveEnvelope)) };
  liveSources[0].onmessage({ data: "2", lastEventId: "restarted:2" });
  assert(liveFetches === 6 && state.data === livePayload.envelope, "post-restart update was ignored");
  globalThis.__liveRecoveryChecked = true;
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
    "dev-done": { source_status: "in-dev", source_owner: "dev", target_status: "ready-for-qa", target_owner: "qa", command: "dev-done" },
  };
  const makeLifecycleAction = (id, path, action) => {
    const spec = actionSpecs[action];
    const suffix = spec.command === "feature-reopen" ? " " + spec.target_status : "";
    return {
      version: 2, feature_id: id, source_status: spec.source_status, source_owner: spec.source_owner, source_path: path,
      target_status: spec.target_status, target_owner: spec.target_owner, action, classification: "ready", supported: true,
      checks: [{ code: "source-readable", status: "pass", message: "Feature source is readable.", path }],
      sources: [path, "knowledge/wiki/SCHEMA.md", "knowledge/wiki/status-board.md"],
      invocations: { codex: "$" + spec.command + " " + id + suffix, claude: "/" + spec.command + " " + id + suffix },
    };
  };
  const makeLifecycleFeature = (id, title, action) => {
    const path = "knowledge/wiki/features/" + id + ".md";
    const primary = makeLifecycleAction(id, path, action);
    return { id, type: "feature", title, path, health: "ok", status: primary.source_status, owner: primary.source_owner, open_questions: [], transitions: [primary] };
  };
  // A feature in ready-for-design offers two routes: its design start and the development handoff.
  const makeRoutesFeature = id => {
    const path = "knowledge/wiki/features/" + id + ".md";
    const transitions = ["design-start", "design-handoff"].map(action => makeLifecycleAction(id, path, action));
    transitions[1].source_status = "ready-for-design";
    transitions[1].source_owner = "designer";
    return {
      id, type: "feature", title: "Feature with two routes", path, health: "ok", status: "ready-for-design", owner: "designer", open_questions: [],
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
      makeRoutesFeature("F-routes"),
    ];
    const supportedActions = Object.keys(actionSpecs);
    const surfaces = [];
    supportedActions.forEach(action => {
      surfaces.push({ role: "codex", action, path: "C:/demo/workspace/.agents/skills/" + actionSpecs[action].command + "/SKILL.md", available: true, check: "pass", invocation_template: "$" + actionSpecs[action].command + " F-XXX" });
      surfaces.push({ role: "claude", action, path: "C:/demo/workspace/.claude/commands/" + actionSpecs[action].command + ".md", available: true, check: "pass", invocation_template: "/" + actionSpecs[action].command + " F-XXX" });
    });
    payload.root = "C:/demo/workspace";
    payload.workspace = { kind: "generated-project", project_name: "TreasuryFlow", apps: [{ id: "backend" }, { id: "android" }, { id: "ios" }] };
    payload.facts.nodes = features;
    payload.facts.node_count = features.length;
    payload.facts.edges = [];
    payload.facts.edge_count = 0;
    payload.facts.intake = { pending: ["first-brief.md"], quarantined: ["CONFLICT.md"] };
    payload.facts.transition_capability = {
      version: 3, mode: "copy-only", supported_actions: supportedActions, surfaces,
      snapshot: { fingerprint: "fp-v2", observed_at: "2026-09-08T12:00:00+02:00", consistent: true },
      sources: ["knowledge/wiki/SCHEMA.md", "knowledge/wiki/status-board.md"],
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
    ["F-in-dev", "Prepare delivery", "ready-for-qa"],
  ].forEach(([id, label, target]) => {
    const control = lifecycleAction(id);
    assert(control && control.textContent.includes(label) && lifecycle.facts.nodes.find(node => node.id === id).status !== target, "lifecycle action was not rendered or changed source state: " + id);
  });
  const doneNode = lifecycle.facts.nodes.find(node => node.id === "F-routes");
  const doneCard = lifecycleCard("F-routes");
  const doneAction = lifecycleAction("F-routes");
  const doneSelect = lifecycleBoard.querySelectorAll("[data-transition-select]").find(item => item.dataset.transitionSelectId === "F-routes");
  assert(doneCard && doneCard.hasAttribute("draggable") && doneSelect && doneAction && doneAction.hasAttribute("aria-disabled") && doneAction.dataset.transitionIndex === "", "A feature with two routes did not require an explicit route");
  const selectedBeforePickerClick = state.selected;
  doneSelect.closest = selector => selector === "button, select, label" ? doneSelect : null;
  doneCard.__listeners.click[0]({ target: doneSelect });
  assert(state.selected === selectedBeforePickerClick, "pointer click on the route picker opened the feature inspector");
  showTransitionPreview("F-routes", doneAction);
  assert(!state.transitionPreview && document.getElementById("transition-dialog").hidden && document.getElementById("sr-status").textContent.includes("Choose a workflow destination"), "a preview silently selected one of two routes");
  doneSelect.value = "1";
  doneSelect.__listeners.change[0]({ target: doneSelect });
  assert(doneAction.dataset.transitionIndex === "1" && doneAction.textContent.includes("development handoff") && !doneAction.hasAttribute("aria-disabled"), "route selection did not enable the selected action");
  const doneBefore = JSON.stringify(doneNode);
  doneAction.__listeners.click[0]({ stopPropagation() {}, preventDefault() {} });
  let lifecycleCopied = "";
  globalThis.navigator = { clipboard: { writeText(value) { lifecycleCopied = value; return { then(done) { done(); return { catch() {} }; } }; } } };
  const lifecycleDialog = document.getElementById("transition-dialog");
  const codexSurface = lifecycleDialog.querySelector('[data-transition-surface="codex"]');
  assert(codexSurface && !codexSurface.hasAttribute("aria-disabled"), "available v2 Codex surface was not exposed");
  codexSurface.__listeners.click[0]({ preventDefault() {} });
  lifecycleDialog.querySelector("[data-transition-copy]").__listeners.click[0]({ preventDefault() {} });
  assert(lifecycleCopied.includes("Exact invocation: " + JSON.stringify("$design-handoff F-routes")) && JSON.stringify(doneNode) === doneBefore, "the selected request copied the wrong invocation or changed source state");
  lifecycleDialog.querySelector("[data-transition-cancel]").__listeners.click[0]();
  selectNode("F-routes");
  const donePanel = document.getElementById("panel");
  const donePanelSelect = donePanel.querySelectorAll("[data-transition-select]").find(item => item.dataset.transitionSelectId === "F-routes");
  const donePanelAction = donePanel.querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-routes");
  assert(donePanelSelect && donePanelAction && donePanelAction.hasAttribute("aria-disabled"), "inspector omitted explicit route selection");
  donePanelSelect.value = "1";
  donePanelSelect.__listeners.change[0]({ target: donePanelSelect });
  assert(donePanelAction.dataset.transitionIndex === "1" && donePanelAction.textContent.includes("development handoff"), "inspector route selection did not update the action");
  donePanelAction.__listeners.click[0]({ stopPropagation() {}, preventDefault() {} });
  assert(state.transitionPreview && doneNode.status === "ready-for-design" && document.getElementById("transition-dialog").innerHTML.includes("design-handoff"), "inspector selected route did not open a source-preserving preview");
  document.getElementById("transition-dialog").querySelector("[data-transition-cancel]").__listeners.click[0]();
  closePanel();

  const targetDrops = [["in-design", "design-start"], ["ready-for-dev", "design-handoff"]];
  const dataTransferV2 = { setData() {}, effectAllowed: "", dropEffect: "" };
  for (const [stage, action] of targetDrops) {
    const target = lifecycleBoard.querySelectorAll(".column[data-stage]").find(column => column.dataset.stage === stage);
    doneCard.__listeners.dragstart[0]({ currentTarget: doneCard, dataTransfer: dataTransferV2 });
    target.__listeners.drop[0]({ currentTarget: target, preventDefault() {} });
    assert(state.transitionPreview && document.getElementById("transition-dialog").innerHTML.includes(action) && doneNode.status === "ready-for-design", "drop did not select source-preserving route " + action);
    document.getElementById("transition-dialog").querySelector("[data-transition-cancel]").__listeners.click[0]();
  }
  const doneColumn = lifecycleBoard.querySelectorAll(".column[data-stage]").find(column => column.dataset.stage === "ready-for-design");
  doneCard.__listeners.dragstart[0]({ currentTarget: doneCard, dataTransfer: dataTransferV2 });
  doneColumn.__listeners.drop[0]({ currentTarget: doneColumn, preventDefault() {} });
  assert(!state.transitionPreview && doneNode.status === "ready-for-design", "same-column drop created a transition");
  const unsupportedColumn = lifecycleBoard.querySelectorAll(".column[data-stage]").find(column => column.dataset.stage === "specified");
  doneCard.__listeners.dragstart[0]({ currentTarget: doneCard, dataTransfer: dataTransferV2 });
  unsupportedColumn.__listeners.drop[0]({ currentTarget: unsupportedColumn, preventDefault() {} });
  assert(!state.transitionPreview && doneNode.status === "ready-for-design", "unsupported drop moved or previewed a route");

  const changedStart = makeV2Payload();
  adoptData(changedStart); switchView("board"); renderBoard();
  const changedAction = document.getElementById("board-view").querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-routes");
  showTransitionPreview("F-routes", changedAction, 1);
  const changedTarget = clone(changedStart);
  changedTarget.facts.nodes.find(node => node.id === "F-routes").transitions[1].target_status = "specified";
  adoptData(changedTarget);
  assert(state.transitionPreview && document.getElementById("transition-dialog").innerHTML.includes("capability changed") && document.getElementById("transition-dialog").querySelector("[data-transition-copy]").hasAttribute("aria-disabled"), "changed target did not stale an open route preview");
  document.getElementById("transition-dialog").querySelector("[data-transition-cancel]").__listeners.click[0]();
  const removedTarget = makeV2Payload();
  adoptData(removedTarget); switchView("board"); renderBoard();
  const removedAction = document.getElementById("board-view").querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-routes");
  showTransitionPreview("F-routes", removedAction, 1);
  const removedRoute = clone(removedTarget);
  removedRoute.facts.nodes.find(node => node.id === "F-routes").transitions.splice(1, 1);
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
  assert(!missingArrayCard.hasAttribute("draggable"), "a feature without a transitions array was offered as runnable");

  const singularOnly = makeV2Payload();
  const singularOnlyFeature = singularOnly.facts.nodes.find(node => node.id === "F-raw");
  singularOnlyFeature.transition = singularOnlyFeature.transitions[0];
  delete singularOnlyFeature.transitions;
  adoptData(singularOnly); switchView("board"); renderBoard();
  const singularOnlyCard = document.getElementById("board-view").querySelectorAll(".card[data-id]").find(item => item.dataset.id === "F-raw");
  assert(!singularOnlyCard.hasAttribute("draggable"), "a singular node transition was read as a workflow action");

  const capabilityV1 = makeV2Payload();
  capabilityV1.facts.transition_capability.version = 1;
  adoptData(capabilityV1); switchView("board"); renderBoard();
  const capabilityV1Card = document.getElementById("board-view").querySelectorAll(".card[data-id]").find(item => item.dataset.id === "F-specified");
  assert(!capabilityV1Card.hasAttribute("draggable") && document.getElementById("board-view").innerHTML.includes("inspect-only"), "a version 1 transition capability was accepted");

  const mismatchId = makeV2Payload();
  mismatchId.facts.nodes.find(node => node.id === "F-routes").transitions[1].feature_id = "F-other";
  adoptData(mismatchId); switchView("board"); renderBoard();
  const mismatchIdCard = document.getElementById("board-view").querySelectorAll(".card[data-id]").find(item => item.dataset.id === "F-routes");
  const mismatchIdSelect = document.getElementById("board-view").querySelectorAll("[data-transition-select]").find(item => item.dataset.transitionSelectId === "F-routes");
  const mismatchIdAction = document.getElementById("board-view").querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-routes");
  mismatchIdSelect.value = "1";
  mismatchIdSelect.__listeners.change[0]({ target: mismatchIdSelect });
  assert(mismatchIdCard.hasAttribute("draggable") && mismatchIdAction.hasAttribute("aria-disabled") && mismatchIdAction.textContent.includes("development handoff") && mismatchIdAction.getAttribute("title").includes("feature ID does not match"), "mismatched transition feature ID was offered as runnable: drag=" + mismatchIdCard.hasAttribute("draggable") + ", disabled=" + mismatchIdAction.hasAttribute("aria-disabled") + ", value=" + mismatchIdSelect.value + ", listeners=" + ((mismatchIdSelect.__listeners.change || []).length) + ", id=" + mismatchIdSelect.dataset.transitionSelectId + ", text=" + mismatchIdAction.textContent + ", title=" + mismatchIdAction.getAttribute("title"));

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

  const wrongMapping = makeReady();
  wrongMapping.facts.nodes[0].transitions[0].target_status = "in-design";
  adoptData(wrongMapping); switchView("board"); renderBoard();
  const wrongMappingCard = document.getElementById("board-view").querySelectorAll(".card[data-id]").find(item => item.dataset.id === "F-001");
  assert(!wrongMappingCard.hasAttribute("draggable") && document.getElementById("board-view").innerHTML.includes("unavailable in this capability version"), "v2 accepted a wrong source/target mapping");

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
  wrongReopenInvocation.facts.nodes.find(node => node.id === "F-routes").transitions[1].invocations.codex = "$design-start F-routes";
  adoptData(wrongReopenInvocation); switchView("board"); renderBoard();
  const wrongReopenSelect = document.getElementById("board-view").querySelectorAll("[data-transition-select]").find(item => item.dataset.transitionSelectId === "F-routes");
  wrongReopenSelect.value = "1";
  wrongReopenSelect.__listeners.change[0]({ target: wrongReopenSelect });
  const wrongReopenAction = document.getElementById("board-view").querySelectorAll("[data-transition-id]").find(item => item.dataset.transitionId === "F-routes");
  wrongReopenAction.__listeners.click[0]({ stopPropagation() {}, preventDefault() {} });
  const wrongReopenDialog = document.getElementById("transition-dialog");
  assert(wrongReopenDialog.querySelector("[data-transition-copy]").hasAttribute("aria-disabled") && wrongReopenDialog.innerHTML.includes("No generated Codex invocation"), "an invocation of another action was copied for the selected route");
  wrongReopenDialog.querySelector("[data-transition-cancel]").__listeners.click[0]();
  state.surface = priorSurface;
})();`);
}
if (checkConnectedBoard) {
  regressionChecks.push(`
;(() => {
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const syncChain = globalThis.__syncChain;
  const calls = [];
  const saved = [];
  localStorage.setItem = (key, value) => saved.push([key, value]);
  const makeEnvelope = () => {
    const payload = JSON.parse(JSON.stringify(globalThis.transitionPayload));
    payload.root = "C:\\\\demo\\\\board";
    payload.workspace = { kind: "generated-project", project_name: "Connected board fixture", apps: [{ id: "backend" }] };
    const agentPath = "knowledge/wiki/features/F-agent.md";
    const agentAction = { version: 2, feature_id: "F-agent", source_status: "in-design", source_owner: "designer", source_path: agentPath, target_status: "ready-for-dev", target_owner: "dev", action: "design-handoff", classification: "ready", supported: true, checks: [{ code: "source-readable", status: "pass", message: "Connected source is readable.", path: agentPath }], sources: [agentPath] };
    payload.facts.nodes = [
      { id: "F-blocked", type: "feature", title: "Blocked mapped action", path: "knowledge/wiki/features/F-blocked.md", health: "warning", status: "specified", owner: "wrong-owner", open_questions: [] },
      { id: "F-apply", type: "feature", title: "PO handoff", path: "knowledge/wiki/features/F-apply.md", health: "ok", status: "specified", owner: "po", advisory_review: "pending", open_questions: [] },
      { id: "F-close", type: "feature", title: "Closed while applying", path: "knowledge/wiki/features/F-close.md", health: "ok", status: "ready-for-design", owner: "designer", open_questions: [] },
      { id: "F-lost", type: "feature", title: "Lost response", path: "knowledge/wiki/features/F-lost.md", health: "ok", status: "ready-for-dev", owner: "dev", open_questions: [] },
      { id: "F-agent-node", type: "feature", title: "Provider-neutral agent handoff", path: agentPath, health: "ok", status: "in-design", owner: "designer", transitions: [agentAction], open_questions: [] },
    ];
    payload.facts.node_count = 5;
    payload.facts.edges = [];
    payload.facts.edge_count = 0;
    payload.facts.intake = { pending: [], quarantined: [] };
    payload.facts.transition_capability = { version: 3, mode: "copy-only", supported_actions: [], snapshot: { consistent: true, fingerprint: "fp-no-vendor", observed_at: "2026-09-22T12:00:00Z" }, surfaces: [] };
    payload.blocker_facts = [];
    return payload;
  };
  const beforeEnvelope = makeEnvelope();
  const afterEnvelope = JSON.parse(JSON.stringify(beforeEnvelope));
  const appliedFeature = afterEnvelope.facts.nodes.find(node => node.id === "F-apply");
  appliedFeature.status = "ready-for-design";
  appliedFeature.owner = "designer";
  const closedApplyEnvelope = JSON.parse(JSON.stringify(afterEnvelope));
  const closedDuringApply = closedApplyEnvelope.facts.nodes.find(node => node.id === "F-close");
  closedDuringApply.status = "in-design";
  const previewFeatureById = {};
  let dataRefreshEnvelope = beforeEnvelope;
  let failGraphRefresh = false;
  let staleDataReads = 0;
  let lostOperationId = "";
  let failNextOperationInspection = false;
  let failNextLostRecovery = false;
  let rejectPreview = false;
  const opListId = "op-list-pending";
  const abandonId = "op-abandon-pending";
  let opListReviewRevision = "review-op-1";
  let originalAgentGrantRevoked = false;
  let lostReviewRevision = "review-lost-1";
  let discoveredPendingOperations = [];
  const reply = (payload, status = 200) => syncChain({ ok: status >= 200 && status < 300, status, json: () => syncChain(payload) });
  globalThis.fetch = (path, options = {}) => {
    const url = String(path);
    calls.push({ path: url, options });
    if (url === "/api/board/v1/auth/session") return reply({ actor: { participant_id: "human-7", name: "Safe Human", kind: "human", writable: true, board_id: "board-7", workflow_version: "1", scopes: ["read", "write"] }, csrf_token: "csrf-only-in-memory" });
    if (url === "/api/board/v1/discover") return reply({ schema_version: 1, capability: { workflow_eligible: true, human_actions: ["po-handoff", "design-start", "dev-start"], supported_actions: ["po-specify", "po-handoff", "design-start", "design-handoff", "dev-start", "dev-done"], supported_write_skills: ["po-specify", "design-handoff", "dev-done"] }, pending_operations: discoveredPendingOperations, participant: { name: "Safe Human", kind: "human", writable: true } });
    if (url === "/api/board/v1/previews/transition") {
      if (rejectPreview) return reply({ error: { code: "unauthorized", message: "The participant grant was revoked." } }, 401);
      const body = JSON.parse(options.body || "{}");
      const previewId = "preview-" + (calls.filter(item => item.path === url).length);
      previewFeatureById[previewId] = body.feature_id;
      const blocked = body.feature_id === "F-blocked";
      const acknowledged = body.inputs && body.inputs.semantic_review_acknowledged === true;
      const skip = body.inputs && body.inputs.skip_advisory_review === true;
      const checks = [];
      if (blocked) checks.push({ code: "source-owner", status: "blocked", message: "Feature owner does not match the PO handoff source." });
      if (body.feature_id === "F-apply") checks.push({ code: "advisory-review", status: skip ? "pass" : "review", message: skip ? "Advisory review skip was proposed." : "Advisory review is pending." });
      checks.push({ code: "semantic-review-confirmation", status: acknowledged ? "pass" : "review", message: acknowledged ? "Semantic review acknowledged." : "Review the exact source changes before continuing." });
      return reply({ schema_version: 1, preview_id: previewId, action: body.action, feature_id: body.feature_id, classification: blocked ? "blocked" : acknowledged && (body.feature_id !== "F-apply" || skip) ? "ready" : "review", applicable: !blocked && acknowledged && (body.feature_id !== "F-apply" || skip), checks, blockers: checks.filter(check => check.status !== "pass"), review_obligations: [], source: { status: "specified", owner: blocked ? "wrong-owner" : "po" }, target: { status: "ready-for-design", owner: "designer" }, writes: [{ path: "knowledge/wiki/features/" + body.feature_id + ".md", role: "canonical", before: "status: specified\\nowner: po\\n", after: "status: ready-for-design\\nowner: designer\\n<title>& safe</title>" }, { path: "knowledge/wiki/log.md", role: "log", before: "", after: "<!-- board operation preview -->\\n" }] });
    }
    if (url === "/api/board/v1/query") {
      const body = JSON.parse(options.body || "{}");
      if (body.kind === "transition-preflight" && body.value === "F-agent" && body.action === "design-handoff") {
        return reply({ schema_version: 1, command: "wiki transition-preflight", facts: { transition: { version: 2, feature_id: "F-agent", source_status: "in-design", source_owner: "designer", source_path: "knowledge/wiki/features/F-agent.md", target_status: "ready-for-dev", target_owner: "dev", action: "design-handoff", classification: "ready", supported: true, checks: [{ code: "source-readable", status: "pass", message: "Connected source is current." }], reason: "ready" } }, snapshot: { consistent: true, revision: "sha256:agent-preflight" }, provenance: "fixture" });
      }
      return reply({ error: { code: "not_found", message: "Fixture query is unavailable." } }, 404);
    }
    if (url === "/api/board/v1/apply") {
      const body = JSON.parse(options.body);
      if (previewFeatureById[body.preview_id] === "F-lost") { lostOperationId = body.operation_id; return syncChain(null, new Error("simulated lost apply response")); }
      if (previewFeatureById[body.preview_id] === "F-close") {
        closeTransitionPreview("The dialog closed while Apply was in flight.");
        dataRefreshEnvelope = closedApplyEnvelope;
      } else dataRefreshEnvelope = afterEnvelope;
      return reply({ schema_version: 1, operation_id: body.operation_id, state: "applied", applied_paths: ["knowledge/wiki/features/F-apply.md", "knowledge/wiki/status-board.md", "knowledge/wiki/log.md"], recovery_available: false });
    }
    if (url === "/api/board/v1/operations/" + opListId) {
      if (failNextOperationInspection) { failNextOperationInspection = false; return reply({ error: { code: "temporarily_unavailable", message: "Inspection response was unavailable." } }, 503); }
      return reply({ schema_version: 1, operation_id: opListId, state: "conflict", recovery_review_revision: opListReviewRevision, actor: { participant_id: "agent-9", name: "Former Agent", kind: "agent" }, remaining_changes: [{ path: "knowledge/wiki/features/F-old.md", state: "conflict", before: "status: specified\\n", after: "status: ready-for-design <&>\\n", current_digest: "sha256:<current&>" }], moves: [{ source: "knowledge/intake/pending/F-old", destination: "knowledge/intake/processed/F-old", source_digest: "private" }], receipt: { schema_version: 1, operation_id: opListId, state: "conflict", applied_paths: ["knowledge/wiki/log.md"], conflicts: [{ path: "knowledge/wiki/features/F-old.md", reason: "Current <file> & differs." }] } });
    }
    if (url === "/api/board/v1/operations/" + abandonId) {
      return reply({ schema_version: 1, operation_id: abandonId, state: "conflict", recovery_review_revision: "review-abandon", actor: { participant_id: "agent-9", name: "Former Agent", kind: "agent" }, remaining_changes: [{ path: "knowledge/wiki/features/F-gone.md", state: "pending", before: null, after: "status: raw\\n", current_digest: null }], moves: [{ source: "knowledge/intake/pending/F-gone", destination: "knowledge/intake/processed/F-gone" }], receipt: { schema_version: 1, operation_id: abandonId, state: "conflict", applied_paths: [], conflicts: [{ path: null, reason: "recovery_move_conflict: Both the recorded intake source and destination are missing." }] } });
    }
    if (url.startsWith("/api/board/v1/operations/") && !url.endsWith("/recover")) return reply({ schema_version: 1, operation_id: lostOperationId, state: "pending", recovery_review_revision: lostReviewRevision, actor: { participant_id: "human-7", name: "Safe Human", kind: "human" }, remaining_changes: [{ path: "knowledge/wiki/features/F-lost.md", state: "pending", before: "status: ready-for-dev\\n", after: "status: done\\n", current_digest: "sha256-current" }], moves: [], receipt: null });
    if (url.endsWith("/recover")) {
      const operationId = decodeURIComponent(url.split("/").at(-2));
      const body = JSON.parse(options.body || "{}");
      if (operationId === abandonId) {
        if (body.abandon !== true || body.review_revision !== "review-abandon" || body.semantic_review_acknowledged !== true) return reply({ error: { code: "stale_recovery_review", message: "The operation changed after review." } }, 409);
        discoveredPendingOperations = discoveredPendingOperations.filter(item => item.operation_id !== operationId);
        return reply({ schema_version: 1, operation_id: abandonId, state: "abandoned", applied_paths: [], unapplied_paths: ["knowledge/wiki/features/F-gone.md"], moved_folders: [], unmoved_folders: [{ source: "knowledge/intake/pending/F-gone", destination: "knowledge/intake/processed/F-gone", state: "missing" }], recovery_available: false, actor: { participant_id: "agent-9", name: "Former Agent", kind: "agent" }, abandoned_by: { participant_id: "human-7", name: "Safe Human", kind: "human" } });
      }
      if (operationId === lostOperationId && failNextLostRecovery) { failNextLostRecovery = false; return syncChain(null, new Error("simulated lost recovery response")); }
      const expectedRevision = operationId === opListId ? opListReviewRevision : lostReviewRevision;
      if (body.review_revision !== expectedRevision || body.semantic_review_acknowledged !== true) return reply({ error: { code: "stale_recovery_review", message: "The operation changed after review." } }, 409);
      if (operationId === opListId && (!originalAgentGrantRevoked || state.boardActor.participant_id === "agent-9")) return reply({ error: { code: "unauthorized", message: "Only another current human can recover this revoked-agent operation." } }, 403);
      if (operationId === lostOperationId) failGraphRefresh = true;
      discoveredPendingOperations = discoveredPendingOperations.filter(item => item.operation_id !== operationId);
      const recoveredReceipt = { schema_version: 1, operation_id: operationId, state: "applied", applied_paths: ["knowledge/wiki/features/F-lost.md", "knowledge/wiki/status-board.md", "knowledge/wiki/log.md"], recovery_available: false, actor: operationId === opListId ? { participant_id: "agent-9", name: "Former Agent", kind: "agent" } : { participant_id: "human-7", name: "Safe Human", kind: "human" } };
      if (operationId === opListId) recoveredReceipt.recovered_by = { participant_id: "human-7", name: "Safe Human", kind: "human" };
      return reply(recoveredReceipt);
    }
    if (url === "/data.json") {
      if (failGraphRefresh) return reply({ error: { code: "graph_unavailable", message: "Snapshot is not ready." } }, 503);
      if (staleDataReads > 0) { staleDataReads -= 1; return reply({ epoch: "board-epoch", version: 1, envelope: beforeEnvelope }); }
      const version = dataRefreshEnvelope === closedApplyEnvelope ? 3 : dataRefreshEnvelope === afterEnvelope ? 2 : 1;
      return reply({ epoch: "board-epoch", version, envelope: dataRefreshEnvelope });
    }
    return reply({ error: { code: "not_found", message: "Fixture route is unavailable." } }, 404);
  };
  state.boardConnection = "connected";
  state.boardActor = { participant_id: "human-7", name: "Safe Human", kind: "human", writable: true, board_id: "board-7", workflow_version: "1", scopes: ["read", "write"] };
  state.boardCsrf = "csrf-only-in-memory";
  state.boardCapability = { workflow_eligible: true, human_actions: ["po-handoff", "design-start", "dev-start"], supported_actions: ["po-specify", "po-handoff", "design-start", "design-handoff", "dev-start", "dev-done", "reopen-spec", "reopen-design", "reopen-dev"], supported_write_skills: ["po-specify", "design-handoff", "dev-done", "feature-reopen"] };
  state.boardDiscover = { capability: state.boardCapability, pending_operations: [] };
  state.boardPendingOperations = [];
  state.liveRefreshError = null;
  state.liveEpoch = "board-epoch";
  state.liveVersion = 1;
  adoptData(beforeEnvelope);
  switchView("board");
  renderBoard();
  renderHeader();
  const sessionHtml = document.getElementById("board-session").innerHTML;
  assert(sessionHtml.includes("Safe Human") && !sessionHtml.includes("csrf-only-in-memory"), "header did not display only the safe actor identity");
  const board = document.getElementById("board-view");
  const agentButton = board.querySelectorAll("[data-transition-id]").find(button => button.dataset.transitionId === "F-agent-node");
  assert(agentButton && !agentButton.hasAttribute("aria-disabled"), "provider-neutral agent action was disabled despite canonical connected skill capability");
  agentButton.__listeners.click[0]({ stopPropagation() {}, preventDefault() {} });
  let agentDialog = document.getElementById("transition-dialog");
  assert(!agentDialog.hidden && agentDialog.innerHTML.includes("PROVIDER-NEUTRAL AGENT REQUEST") && agentDialog.innerHTML.includes("board-7") && agentDialog.innerHTML.includes("board_id exactly matches") && agentDialog.innerHTML.includes("design-handoff") && agentDialog.innerHTML.includes("get_skill") && agentDialog.innerHTML.includes("sha256:agent-preflight") && !agentDialog.innerHTML.includes("$design-handoff") && !agentDialog.innerHTML.includes("/design-handoff") && !agentDialog.innerHTML.includes("Apply reviewed changes"), "agent-only lifecycle action did not produce a provider-neutral MCP request");
  const agentQuery = calls.filter(item => item.path === "/api/board/v1/query").at(-1);
  assert(agentQuery && JSON.stringify(JSON.parse(agentQuery.options.body)) === JSON.stringify({ kind: "transition-preflight", value: "F-agent", action: "design-handoff" }), "agent request did not use the server transition-preflight query");
  assert(!agentDialog.querySelector("[data-transition-copy]").hasAttribute("aria-disabled"), "fresh connected agent preflight remained copy-disabled");
  markLiveRefreshUnavailable("agent-disconnected");
  agentDialog = document.getElementById("transition-dialog");
  assert(agentDialog.querySelector("[data-transition-copy]").hasAttribute("aria-disabled") && document.getElementById("freshness").innerHTML.includes("STALE"), "agent request remained copyable or header stayed green after connection loss");
  adoptData(beforeEnvelope);
  agentDialog = document.getElementById("transition-dialog");
  assert(agentDialog.querySelector("[data-transition-copy]").hasAttribute("aria-disabled"), "healthy snapshot silently re-approved a stale connected agent request");
  agentDialog.querySelector("[data-connected-agent-refresh]").__listeners.click[0]();
  agentDialog = document.getElementById("transition-dialog");
  assert(!agentDialog.querySelector("[data-transition-copy]").hasAttribute("aria-disabled") && agentDialog.innerHTML.includes("sha256:agent-preflight"), "fresh matching agent recheck did not clear stale state and restore the exact preflight");
  agentDialog.querySelector("[data-transition-cancel]").__listeners.click[0]();
  const blockedButton = board.querySelectorAll("[data-board-action]").find(button => button.dataset.boardFeatureId === "F-blocked");
  const blockedCard = board.querySelectorAll(".card[data-id]").find(card => card.dataset.id === "F-blocked");
  assert(blockedButton && blockedCard && blockedCard.hasAttribute("draggable"), "connected actions depended on legacy transition metadata or vendor folders");
  assert(board.querySelectorAll("[data-transition-id]").length === 1 && board.querySelectorAll("[data-transition-id]")[0].dataset.transitionId === "F-agent-node", "connected human action fell back to copy-only guidance: " + board.querySelectorAll("[data-transition-id]").map(button => button.dataset.transitionId).join(","));
  blockedCard.__listeners.dragstart[0]({ currentTarget: blockedCard, preventDefault() {}, dataTransfer: { setData() {} } });
  const target = board.querySelectorAll(".column[data-stage]").find(column => column.dataset.stage === "ready-for-design");
  target.__listeners.drop[0]({ currentTarget: target, preventDefault() {} });
  let dialog = document.getElementById("transition-dialog");
  assert(!dialog.hidden && dialog.innerHTML.includes("Feature owner does not match") && dialog.innerHTML.includes("&lt;title&gt;&amp; safe&lt;/title&gt;"), "blocked mapped drop did not show escaped exact service diff: " + dialog.innerHTML.slice(0, 900));
  assert(dialog.innerHTML.includes("rewrites the full YAML frontmatter") && dialog.innerHTML.includes("comments and original formatting may be removed or normalized") && dialog.innerHTML.includes("Review the exact before/after text above before confirming"), "connected human preview did not disclose YAML frontmatter formatting normalization before confirmation");
  assert(dialog.querySelector("[data-connected-apply]").disabled, "blocked connected preview exposed Apply");
  assert(calls.filter(item => item.path === "/api/board/v1/previews/transition").length === 1, "mapped drop did not call connected preview");
  const blockedRequest = JSON.parse(calls.find(item => item.path === "/api/board/v1/previews/transition").options.body);
  assert(blockedRequest.inputs.semantic_review_acknowledged === false, "semantic review was asserted before the diff was shown");
  dialog.querySelector("[data-transition-cancel]").__listeners.click[0]();

  originalAgentGrantRevoked = true;
  discoveredPendingOperations = [{ operation_id: opListId, state: "conflict", created_at: "2026-09-22T12:00:00Z" }];
  initBoardService();
  assert(originalAgentGrantRevoked && state.boardActor.kind === "human" && state.boardActor.writable === true && state.boardPendingOperations.length === 1 && state.boardPendingOperations[0].operation_id === opListId, "writable human could not inspect the revoked-agent operation surfaced by discovery");
  const operationsButton = document.getElementById("board-session").querySelector("[data-board-operations]");
  assert(operationsButton, "pending service operation was not surfaced separately in the header");
  operationsButton.__listeners.click[0]();
  dialog = document.getElementById("transition-dialog");
  assert(dialog.innerHTML.includes("Operation state is separate from feature lifecycle") && dialog.innerHTML.includes("no agent is involved"), "recovery view did not keep operations separate from lifecycle or identify direct recovery");
  failNextOperationInspection = true;
  dialog.querySelector("[data-operation-inspect]").__listeners.click[0]();
  assert(!state.transitionPreview.selectedOperation && !state.transitionPreview.inspectedOperationId && !state.transitionPreview.recoveryAcknowledged, "failed operation inspection authorized recovery");
  assert(dialog.querySelectorAll("[data-operation-recover]").every(button => button.disabled), "recovery remained enabled after an unknown inspection response");
  dialog.querySelector("[data-operation-inspect]").__listeners.click[0]();
  dialog = document.getElementById("transition-dialog");
  assert(dialog.innerHTML.includes("Current &lt;file&gt; &amp; differs.") && dialog.innerHTML.includes("Former Agent") && dialog.innerHTML.includes("Original actor") && dialog.innerHTML.includes("sha256:&lt;current&amp;&gt;") && dialog.innerHTML.includes("status: ready-for-design &lt;&amp;&gt;"), "operation inspection did not render escaped original actor, exact remaining changes, current digest, and conflict");
  assert(dialog.innerHTML.includes("knowledge/intake/pending/F-old → knowledge/intake/processed/F-old") && !dialog.innerHTML.includes("source_digest"), "operation inspection did not show safe folder-move endpoints only");
  assert(dialog.querySelectorAll("[data-operation-recover]").every(button => button.disabled), "successful inspection skipped explicit recovery acknowledgement");
  const pendingRecoveryButton = dialog.querySelectorAll("[data-operation-recover]")[0];
  pendingRecoveryButton.__listeners.click[0]();
  assert(!calls.some(item => item.path === "/api/board/v1/operations/" + opListId + "/recover"), "unacknowledged pending-operation recovery reached the service");
  const operationAck = dialog.querySelector("[data-operation-recovery-ack]");
  operationAck.checked = true;
  operationAck.__listeners.change[0]();
  opListReviewRevision = "review-op-2";
  dialog.querySelectorAll("[data-operation-recover]")[0].__listeners.click[0]();
  const staleRecoverCall = calls.filter(item => item.path === "/api/board/v1/operations/" + opListId + "/recover").at(-1);
  assert(JSON.parse(staleRecoverCall.options.body).review_revision === "review-op-1" && JSON.parse(staleRecoverCall.options.body).semantic_review_acknowledged === true, "pending human recovery did not send the inspected revision and explicit acknowledgement");
  assert(!state.transitionPreview.selectedOperation && !state.transitionPreview.inspectedOperationId && !state.transitionPreview.recoveryAcknowledged, "stale pending-operation recovery retained its old review token or acknowledgement");
  assert(dialog.querySelectorAll("[data-operation-recover]").every(button => button.disabled), "stale pending-operation inspection left recovery enabled");
  dialog.querySelector("[data-operation-inspect]").__listeners.click[0]();
  dialog = document.getElementById("transition-dialog");
  assert(dialog.innerHTML.includes("review-op-2") === false, "opaque recovery review revision was exposed in the UI");
  assert(dialog.querySelectorAll("[data-operation-recover]").every(button => button.disabled), "reinspection reused the old acknowledgement");
  const refreshedOperationAck = dialog.querySelector("[data-operation-recovery-ack]");
  refreshedOperationAck.checked = true;
  refreshedOperationAck.__listeners.change[0]();
  dialog.querySelectorAll("[data-operation-recover]")[0].__listeners.click[0]();
  const currentRecoverCall = calls.filter(item => item.path === "/api/board/v1/operations/" + opListId + "/recover").at(-1);
  assert(JSON.parse(currentRecoverCall.options.body).review_revision === "review-op-2" && JSON.parse(currentRecoverCall.options.body).semantic_review_acknowledged === true, "reinspected human recovery did not send the fresh revision and acknowledgement");
  assert(dialog.innerHTML.includes("Original actor") && dialog.innerHTML.includes("Former Agent") && dialog.innerHTML.includes("Recovered by") && dialog.innerHTML.includes("Safe Human"), "recovery receipt did not distinguish the original agent from the recovering human");
  assert(state.transitionPreview.operationState === "applied" && state.data.facts.nodes.find(node => node.id === "F-apply").status === "specified", "no-agent recovery changed lifecycle state or lost its operation receipt");
  assert(dialog.querySelectorAll("[data-operation-abandon]").length === 0, "an applied operation offered to be abandoned");
  document.getElementById("transition-dialog").querySelector("[data-transition-cancel]").__listeners.click[0]();

  // A person closes an operation that can no longer be rolled forward: same inspection and approval, explicit abandon.
  discoveredPendingOperations = [{ operation_id: abandonId, state: "conflict", created_at: "2026-09-22T13:00:00Z" }];
  refreshBoardDiscovery();
  openBoardOperations(null);
  dialog = document.getElementById("transition-dialog");
  dialog.querySelector("[data-operation-inspect]").__listeners.click[0]();
  dialog = document.getElementById("transition-dialog");
  assert(dialog.querySelectorAll("[data-operation-abandon]").length === 1 && dialog.querySelectorAll("[data-operation-abandon]").every(button => button.disabled), "abandon was available before the inspection was acknowledged");
  dialog.querySelectorAll("[data-operation-abandon]")[0].__listeners.click[0]();
  assert(!calls.some(item => item.path === "/api/board/v1/operations/" + abandonId + "/recover"), "an unacknowledged abandon reached the service");
  const abandonAck = dialog.querySelector("[data-operation-recovery-ack]");
  abandonAck.checked = true;
  abandonAck.__listeners.change[0]();
  assert(dialog.querySelectorAll("[data-operation-abandon]").every(button => !button.disabled), "abandon stayed disabled after the explicit acknowledgement");
  dialog.querySelectorAll("[data-operation-abandon]")[0].__listeners.click[0]();
  const abandonCall = calls.filter(item => item.path === "/api/board/v1/operations/" + abandonId + "/recover").at(-1);
  const abandonBody = JSON.parse(abandonCall.options.body);
  assert(abandonBody.review_revision === "review-abandon" && abandonBody.semantic_review_acknowledged === true && abandonBody.abandon === true, "abandon did not send the inspected revision, the acknowledgement and the explicit abandon flag");
  dialog = document.getElementById("transition-dialog");
  assert(state.transitionPreview.operationState === "abandoned" && dialog.innerHTML.includes("Operation abandoned") && dialog.innerHTML.includes("Abandoned by") && dialog.innerHTML.includes("Safe Human") && dialog.innerHTML.includes("Original actor") && dialog.innerHTML.includes("not written") && dialog.innerHTML.includes("knowledge/wiki/features/F-gone.md"), "the abandoned receipt did not show both actors and the writes that were not applied");
  assert(dialog.querySelectorAll("[data-operation-abandon]").length === 0 && dialog.querySelectorAll("[data-operation-recover]").length === 0, "an abandoned operation offered another recovery");
  document.getElementById("transition-dialog").querySelector("[data-transition-cancel]").__listeners.click[0]();

  const applyButton = board.querySelectorAll("[data-board-action]").find(button => button.dataset.boardFeatureId === "F-apply");
  applyButton.__listeners.click[0]({ preventDefault() {}, stopPropagation() {} });
  dialog = document.getElementById("transition-dialog");
  assert(dialog.innerHTML.includes("Advisory review is pending") && dialog.querySelector("[data-connected-skip]"), "pending PO advisory review did not offer an explicit skip proposal");
  const skip = dialog.querySelector("[data-connected-skip]");
  skip.checked = true;
  skip.__listeners.change[0]();
  dialog = document.getElementById("transition-dialog");
  const reason = dialog.querySelector("[data-connected-skip-reason]");
  reason.value = "PO reviewed the risk and accepts the delay.";
  reason.__listeners.input[0]();
  const repreview = dialog.querySelector("[data-connected-repreview]");
  assert(repreview && !repreview.disabled, "valid PO skip reason did not enable a new preview");
  repreview.__listeners.click[0]();
  const skipRequest = JSON.parse(calls.filter(item => item.path === "/api/board/v1/previews/transition").at(-1).options.body);
  assert(skipRequest.inputs.skip_advisory_review === true && skipRequest.inputs.advisory_skip_reason === "PO reviewed the risk and accepts the delay.", "PO skip reason was not sent as an explicit proposal");
  dialog = document.getElementById("transition-dialog");
  const ack = dialog.querySelector("[data-connected-ack]");
  ack.checked = true;
  ack.__listeners.change[0]();
  const ackRequest = JSON.parse(calls.filter(item => item.path === "/api/board/v1/previews/transition").at(-1).options.body);
  assert(ackRequest.inputs.semantic_review_acknowledged === true, "semantic-review acknowledgement was not sent after the exact diff was shown: " + JSON.stringify(ackRequest));
  dialog = document.getElementById("transition-dialog");
  const apply = dialog.querySelector("[data-connected-apply]");
  assert(apply && !apply.disabled, "applicable preview remained disabled after semantic acknowledgement");
  apply.__listeners.click[0]();
  assert(state.transitionPreview.operationState === "applied" && state.transitionPreview.operationMessage.includes("refreshed and validated"), "apply receipt did not retain applied plus validated-view truth");
  assert(state.data.facts.nodes.find(node => node.id === "F-apply").status === "ready-for-design", "successful apply did not refresh the graph from the service endpoint");
  const applyCall = calls.find(item => item.path === "/api/board/v1/apply");
  assert(applyCall && applyCall.options.headers["X-Prism-CSRF"] === "csrf-only-in-memory", "browser apply did not use the in-memory CSRF value");
  assert(!calls.some(item => item.path.includes("csrf-only-in-memory") || (item.options.body || "").includes("csrf-only-in-memory")), "session CSRF value leaked into a URL or request body");
  assert(!saved.some(pair => String(pair[0]).includes("token") || String(pair[1]).includes("csrf-only-in-memory")), "session data was persisted to localStorage");

  const closeApplyButton = board.querySelectorAll("[data-board-action]").find(button => button.dataset.boardFeatureId === "F-close");
  closeApplyButton.__listeners.click[0]({ preventDefault() {}, stopPropagation() {} });
  dialog = document.getElementById("transition-dialog");
  dialog.querySelector("[data-connected-ack]").checked = true;
  dialog.querySelector("[data-connected-ack]").__listeners.change[0]();
  dialog = document.getElementById("transition-dialog");
  dialog.querySelector("[data-connected-apply]").__listeners.click[0]();
  assert(state.transitionPreview === null && state.data.facts.nodes.find(node => node.id === "F-close").status === "in-design", "closing the preview while Apply was in flight discarded the operation receipt and graph refresh: modal=" + !!state.transitionPreview + ", status=" + state.data.facts.nodes.find(node => node.id === "F-close").status + ", stale=" + state.boardViewStale);

  // A snapshot that predates the applied write is retried and never reported as validated.
  const retryTimers = [];
  const priorSetTimeout = globalThis.setTimeout;
  globalThis.setTimeout = (callback, delay) => { retryTimers.push({ callback, delay }); return retryTimers.length; };
  const applyCloseFixture = () => {
    adoptData(beforeEnvelope);
    state.liveVersion = 1;
    retryTimers.length = 0;
    const button = board.querySelectorAll("[data-board-action]").find(item => item.dataset.boardFeatureId === "F-close");
    button.__listeners.click[0]({ preventDefault() {}, stopPropagation() {} });
    const opened = state.transitionPreview;
    let current = document.getElementById("transition-dialog");
    current.querySelector("[data-connected-ack]").checked = true;
    current.querySelector("[data-connected-ack]").__listeners.change[0]();
    current = document.getElementById("transition-dialog");
    current.querySelector("[data-connected-apply]").__listeners.click[0]();
    return opened;
  };
  const closeStage = () => state.data.facts.nodes.find(node => node.id === "F-close").status;
  const retryDelays = () => retryTimers.filter(item => [150, 300, 600, 900, 1200].includes(item.delay)).map(item => item.delay);
  const fireRetry = () => retryTimers.filter(item => [150, 300, 600, 900, 1200].includes(item.delay)).at(-1).callback();
  staleDataReads = 2;
  const dataCallsAndApplyBefore = { data: calls.filter(item => item.path === "/data.json").length, apply: calls.filter(item => item.path === "/api/board/v1/apply").length };
  const retriedPreview = applyCloseFixture();
  assert(retriedPreview.operationState === "applied" && retriedPreview.operationMessage.includes("Refreshing and validating") && !retriedPreview.operationMessage.includes("refreshed and validated") && closeStage() === "ready-for-design", "a snapshot older than the applied write was reported as refreshed and validated: " + retriedPreview.operationMessage);
  assert(!state.boardViewStale && !state.liveRefreshError && JSON.stringify(retryDelays()) === "[150]", "the first stale read did not schedule exactly one retry: " + JSON.stringify(retryDelays()));
  fireRetry();
  assert(retriedPreview.operationMessage.includes("Refreshing and validating") && closeStage() === "ready-for-design" && JSON.stringify(retryDelays()) === "[150,300]", "the second stale read did not keep waiting: " + retriedPreview.operationMessage);
  fireRetry();
  assert(retriedPreview.operationMessage.includes("refreshed and validated") && closeStage() === "in-design" && !state.boardViewStale && !state.liveRefreshError && state.liveVersion === 3, "the retry that returned the applied snapshot was not adopted and validated: " + retriedPreview.operationMessage);
  assert(JSON.stringify(retryDelays()) === "[150,300]", "a validated retry scheduled another read");
  const applyCallsAfterRetry = calls.filter(item => item.path === "/api/board/v1/apply").length;
  assert(applyCallsAfterRetry === dataCallsAndApplyBefore.apply + 1 && calls.filter(item => item.path === "/data.json").length >= dataCallsAndApplyBefore.data + 3, "the retries did not re-request the snapshot without resubmitting the apply");

  staleDataReads = 100;
  const waitingPreview = applyCloseFixture();
  assert(calls.filter(item => item.path === "/api/board/v1/apply").length === applyCallsAfterRetry + 1, "the fallback case did not submit exactly one apply");
  for (let index = 0; index < 5; index += 1) fireRetry();
  assert(JSON.stringify(retryDelays()) === "[150,300,600,900,1200]" && state.boardViewStale && state.liveRefreshError && closeStage() === "ready-for-design", "exhausted retries did not mark the view stale: " + JSON.stringify(retryDelays()));
  assert(waitingPreview.operationMessage.includes("view stale") && waitingPreview.operationMessage.includes("live update stream") && !waitingPreview.operationMessage.includes("refreshed and validated") && state.pendingAppliedStage && state.pendingAppliedStage.featureId === "F-close", "exhausted retries did not say the board is waiting for the event stream: " + waitingPreview.operationMessage);
  assert(calls.filter(item => item.path === "/api/board/v1/apply").length === applyCallsAfterRetry + 1, "exhausted retries resubmitted the apply");
  staleDataReads = 0;
  adoptData(beforeEnvelope);
  assert(waitingPreview.operationMessage.includes("view stale") && state.pendingAppliedStage, "an unrelated snapshot cleared the waiting state");
  adoptData(closedApplyEnvelope);
  assert(waitingPreview.operationMessage.includes("refreshed and validated") && !state.boardViewStale && !state.liveRefreshError && state.pendingAppliedStage === null && closeStage() === "in-design", "the event stream snapshot did not settle the waiting state");
  globalThis.setTimeout = priorSetTimeout;
  staleDataReads = 0;

  const legacyEnvelope = JSON.parse(JSON.stringify(beforeEnvelope));
  const legacyPath = "knowledge/wiki/features/F-legacy.md";
  const legacyAction = { version: 2, feature_id: "F-legacy", source_status: "in-design", source_owner: "designer", source_path: legacyPath, target_status: "ready-for-dev", target_owner: "dev", action: "design-handoff", classification: "ready", supported: true, checks: [{ code: "source-readable", status: "pass", message: "Feature source is readable.", path: legacyPath }], sources: [legacyPath], invocations: { codex: "$design-handoff F-legacy", claude: "/design-handoff F-legacy" } };
  legacyEnvelope.facts.nodes.push({ id: "F-legacy", type: "feature", title: "Legacy agent guidance", path: legacyPath, health: "ok", status: "in-design", owner: "designer", open_questions: [], transitions: [legacyAction] });
  legacyEnvelope.facts.node_count += 1;
  legacyEnvelope.facts.transition_capability = { version: 3, mode: "copy-only", supported_actions: ["design-handoff"], snapshot: { consistent: true, fingerprint: "fp-legacy", observed_at: "2026-09-22T12:00:00Z" }, surfaces: [{ role: "codex", action: "design-handoff", available: true, check: "pass" }, { role: "claude", action: "design-handoff", available: true, check: "pass" }] };
  const connectedStateBeforeLegacy = state.boardConnection;
  state.boardConnection = "unsupported";
  adoptData(legacyEnvelope);
  switchView("board");
  renderBoard();
  const legacyButton = document.getElementById("board-view").querySelectorAll("[data-transition-id]").find(button => button.dataset.transitionId === "F-legacy");
  assert(legacyButton && !legacyButton.hasAttribute("aria-disabled"), "nonhuman design-handoff did not retain its copy-only agent guidance");
  legacyButton.__listeners.click[0]({ stopPropagation() {}, preventDefault() {} });
  assert(document.getElementById("transition-dialog").innerHTML.includes("COPY-ONLY WORKFLOW REQUEST"), "unsupported human actions were routed into connected Apply");
  document.getElementById("transition-dialog").querySelector("[data-transition-cancel]").__listeners.click[0]();
  state.boardConnection = connectedStateBeforeLegacy;
  adoptData(afterEnvelope);

  const lostButton = document.getElementById("board-view").querySelectorAll("[data-board-action]").find(button => button.dataset.boardFeatureId === "F-lost");
  assert(lostButton, "connected dev-start action was not available without graph transition metadata: connection=" + state.boardConnection + ", capability=" + JSON.stringify(state.boardCapability) + ", stale=" + state.liveRefreshError + ", stage=" + state.data.facts.nodes.find(node => node.id === "F-lost").status + ", html=" + document.getElementById("board-view").innerHTML.slice(0, 1200));
  lostButton.__listeners.click[0]({ preventDefault() {}, stopPropagation() {} });
  dialog = document.getElementById("transition-dialog");
  dialog.querySelector("[data-connected-ack]").checked = true;
  dialog.querySelector("[data-connected-ack]").__listeners.change[0]();
  markLiveRefreshUnavailable("disconnected");
  assert(document.getElementById("freshness").innerHTML.includes("STALE") && document.getElementById("transition-dialog").querySelector("[data-connected-apply]").disabled, "live disconnect left connected Apply enabled or the header green");
  adoptData(state.data);
  assert(document.getElementById("freshness").innerHTML.includes("LIVE") && document.getElementById("transition-dialog").querySelector("[data-connected-apply]").disabled, "healthy snapshot recovery silently re-approved the stale connected preview");
  document.getElementById("transition-dialog").querySelector("[data-transition-cancel]").__listeners.click[0]();
  const freshLostButton = document.getElementById("board-view").querySelectorAll("[data-board-action]").find(button => button.dataset.boardFeatureId === "F-lost");
  freshLostButton.__listeners.click[0]({ preventDefault() {}, stopPropagation() {} });
  dialog = document.getElementById("transition-dialog");
  dialog.querySelector("[data-connected-ack]").checked = true;
  dialog.querySelector("[data-connected-ack]").__listeners.change[0]();
  dialog = document.getElementById("transition-dialog");
  dialog.querySelector("[data-connected-apply]").__listeners.click[0]();
  assert(state.transitionPreview.operationState === "pending" && state.transitionPreview.operationId === lostOperationId, "lost apply response did not query the same operation ID");
  const applyCountBeforeRecovery = calls.filter(item => item.path === "/api/board/v1/apply").length;
  dialog = document.getElementById("transition-dialog");
  assert(dialog.innerHTML.includes("status: done") && dialog.innerHTML.includes("sha256-current"), "inline recovery did not show the inspected exact remaining changes");
  assert(dialog.querySelector("[data-connected-recover]").disabled, "inline recovery was enabled before acknowledgement");
  dialog.querySelector("[data-connected-recover]").__listeners.click[0]();
  assert(!calls.some(item => item.path === "/api/board/v1/operations/" + lostOperationId + "/recover"), "unacknowledged inline recovery reached the service");
  let inlineRecoveryAck = dialog.querySelector("[data-connected-recovery-ack]");
  inlineRecoveryAck.checked = true;
  inlineRecoveryAck.__listeners.change[0]();
  assert(!dialog.querySelector("[data-connected-recover]").disabled, "inline recovery did not enable after explicit acknowledgement");
  const inlineReviewRevision = state.transitionPreview.operationRecord.recovery_review_revision;
  failNextLostRecovery = true;
  dialog.querySelector("[data-connected-recover]").__listeners.click[0]();
  const inlineRecoverCall = calls.filter(item => item.path === "/api/board/v1/operations/" + lostOperationId + "/recover").at(-1);
  assert(JSON.parse(inlineRecoverCall.options.body).review_revision === inlineReviewRevision && JSON.parse(inlineRecoverCall.options.body).semantic_review_acknowledged === true, "inline recovery did not send the inspected revision and explicit acknowledgement");
  assert(state.transitionPreview.operationState === "outcome unknown" && !state.transitionPreview.operationRecord && !state.transitionPreview.recoveryAcknowledged, "unknown recovery response retained stale inspection approval");
  assert(dialog.querySelector("[data-connected-recover]").disabled, "unknown recovery response left inline recovery enabled");
  dialog.querySelector("[data-connected-check-operation]").__listeners.click[0]();
  dialog = document.getElementById("transition-dialog");
  assert(state.transitionPreview.operationState === "pending" && !state.transitionPreview.recoveryAcknowledged && dialog.querySelector("[data-connected-recover]").disabled, "reinspection after an unknown recovery response reused the old acknowledgement");
  inlineRecoveryAck = dialog.querySelector("[data-connected-recovery-ack]");
  inlineRecoveryAck.checked = true;
  inlineRecoveryAck.__listeners.change[0]();
  dialog.querySelector("[data-connected-recover]").__listeners.click[0]();
  assert(state.transitionPreview.operationState === "applied" && state.boardViewStale && state.transitionPreview.operationMessage.includes("view stale"), "applied recovery with failed graph refresh was misreported as failed or current");
  assert(dialog.innerHTML.includes("Original actor") && dialog.innerHTML.includes("Safe Human") && !dialog.innerHTML.includes("Recovered by"), "same-originator receipt fabricated a separate recovery actor");
  assert(calls.filter(item => item.path === "/api/board/v1/apply").length === applyCountBeforeRecovery, "lost response recovery silently resubmitted Apply");
  assert(document.getElementById("freshness").innerHTML.includes("STALE"), "failed post-apply refresh left a green LIVE header");

  closeTransitionPreview();
  adoptData(beforeEnvelope);
  rejectPreview = true;
  const revokedButton = document.getElementById("board-view").querySelectorAll("[data-board-action]").find(button => button.dataset.boardFeatureId === "F-apply");
  revokedButton.__listeners.click[0]({ preventDefault() {}, stopPropagation() {} });
  assert(state.boardConnection === "unauthenticated" && state.boardActor === null && state.boardCsrf === null && state.boardPendingOperations.length === 0, "revoked actor kept connected identity, CSRF state, or pending receipts active");
  assert(!connectedHumanWriter() && document.getElementById("board-session").innerHTML.includes("Board session expired"), "revoked actor still appeared authorized in the dashboard header");
  let reloads = 0;
  window.location = { reload() { reloads += 1; } };
  document.getElementById("board-session").querySelector("[data-board-retry]").__listeners.click[0]();
  assert(reloads === 1, "expired-session reconnect did not return to the token login shell");
  globalThis.__connectedBoardChecked = true;
})();`);
}
if (checkBoardDefects) {
  regressionChecks.push(`
;(() => {
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const clone = value => JSON.parse(JSON.stringify(value));
  const syncChain = globalThis.__syncChain;
  const reply = (payload, status = 200) => syncChain({ ok: status >= 200 && status < 300, status, json: () => syncChain(payload) });
  // A response that settles later, so a test can decide what arrives first: the live event or the apply response.
  const lateChain = () => {
    const handlers = [];
    let done = false, value, failure;
    const run = () => {
      handlers.splice(0).forEach(handler => {
        let result;
        try {
          if (failure) {
            if (!handler.onRejected) { handler.next.settle(undefined, failure); return; }
            result = handler.onRejected(failure);
          } else result = handler.onFulfilled ? handler.onFulfilled(value) : value;
        } catch (error) { handler.next.settle(undefined, error); return; }
        if (result && typeof result.then === "function") result.then(next => handler.next.settle(next), error => handler.next.settle(undefined, error));
        else handler.next.settle(result);
      });
    };
    const chain = {
      then(onFulfilled, onRejected) { const next = lateChain(); handlers.push({ onFulfilled, onRejected, next }); if (done) run(); return next; },
      catch(onRejected) { return chain.then(undefined, onRejected); },
      settle(nextValue, nextFailure) { if (done) return; done = true; value = nextValue; failure = nextFailure; run(); },
    };
    return chain;
  };
  const actor = { participant_id: "human-7", name: "Safe Human", kind: "human", writable: true, board_id: "board-7", workflow_version: "1", scopes: ["read", "write"] };
  const capability = { workflow_eligible: true, human_actions: ["po-handoff", "design-start", "dev-start"], supported_actions: ["po-handoff", "design-start", "dev-start"], supported_write_skills: [] };
  const connect = () => {
    state.boardConnection = "connected";
    state.boardActor = actor;
    state.boardCsrf = "csrf-only-in-memory";
    state.boardCapability = capability;
    state.boardDiscover = { capability, pending_operations: [] };
    state.boardPendingOperations = [];
    state.liveRefreshError = null;
    state.liveEpoch = "defect-epoch";
    state.liveVersion = 1;
  };
  const featureNode = (id, extra) => Object.assign({ id, type: "feature", title: "Feature " + id, path: "knowledge/wiki/features/" + id + ".md", health: "ok", status: "specified", owner: "po", open_questions: [] }, extra || {});
  const makeEnvelope = () => {
    const payload = clone(globalThis.transitionPayload);
    payload.root = "/demo/defects";
    payload.workspace = { kind: "generated-project", project_name: "Defect fixture", apps: [{ id: "backend" }] };
    payload.facts.nodes = [
      featureNode("F-live"), featureNode("F-lost"), featureNode("F-rejected", { advisory_review: "pending" }), featureNode("F-revoked"), featureNode("F-down"), featureNode("F-drag"),
    ];
    payload.facts.node_count = payload.facts.nodes.length;
    payload.facts.edges = [];
    payload.facts.edge_count = 0;
    payload.facts.intake = { pending: [], quarantined: [] };
    payload.facts.transition_capability = { version: 3, mode: "copy-only", supported_actions: [], snapshot: { consistent: true, fingerprint: "fp-defects", observed_at: "2026-09-22T12:00:00Z" }, surfaces: [] };
    payload.blocker_facts = [];
    return payload;
  };
  const beforeEnvelope = makeEnvelope();
  const afterEnvelope = clone(beforeEnvelope);
  for (const node of afterEnvelope.facts.nodes) if (node.id === "F-live" || node.id === "F-lost") { node.status = "ready-for-design"; node.owner = "designer"; }
  const calls = [];
  let applyMode = "ok";
  let operationMode = "applied";
  let heldApply = null;
  let dataEnvelope = beforeEnvelope;
  let dataVersion = 1;
  let sessionStatus = 200;
  let dataStatus = 200;
  let previewCount = 0;
  const receiptFor = operationId => ({ schema_version: 1, operation_id: operationId, state: "applied", action: "po-handoff", feature_id: "F-live", applied_paths: ["knowledge/wiki/features/F-live.md", "knowledge/wiki/status-board.md", "knowledge/wiki/log.md"], recovery_available: false, actor });
  globalThis.fetch = (path, options = {}) => {
    const url = String(path);
    calls.push({ path: url, options });
    if (url === "/api/board/v1/auth/session") {
      if (sessionStatus === 401) return reply({ error: { code: "session_expired", message: "The Prism board session has expired." } }, 401);
      return reply({ actor, csrf_token: "csrf-only-in-memory" });
    }
    if (url === "/api/board/v1/discover") return reply({ schema_version: 1, capability, pending_operations: [], participant: actor });
    if (url === "/api/board/v1/previews/transition") {
      const body = JSON.parse(options.body || "{}");
      previewCount += 1;
      const acknowledged = body.inputs && body.inputs.semantic_review_acknowledged === true;
      const skip = body.inputs && body.inputs.skip_advisory_review === true;
      const advisory = body.feature_id === "F-rejected";
      const applicable = acknowledged && (!advisory || skip);
      return reply({ schema_version: 1, preview_id: "preview-" + previewCount, action: body.action, feature_id: body.feature_id, classification: applicable ? "ready" : "review", applicable,
        checks: advisory ? [{ code: "advisory-review", status: skip ? "pass" : "review", message: skip ? "Advisory review skip was proposed." : "Advisory review is pending." }] : [],
        blockers: [], review_obligations: [], source: { status: "specified", owner: "po" }, target: { status: "ready-for-design", owner: "designer" },
        writes: [{ path: "knowledge/wiki/features/" + body.feature_id + ".md", role: "canonical", before: "status: specified\\n", after: "status: ready-for-design\\n" }] });
    }
    if (url === "/api/board/v1/apply") {
      const body = JSON.parse(options.body);
      if (applyMode === "held") { heldApply = { body, chain: lateChain() }; return heldApply.chain; }
      if (applyMode === "lost") return syncChain(null, new Error("simulated lost apply response"));
      if (applyMode === "stale") return reply({ error: { code: "stale_preview", message: "Relevant source knowledge/wiki/features/F-rejected.md changed after this preview." } }, 409);
      if (applyMode === "unauthorized") return reply({ error: { code: "unauthorized", message: "The Prism participant token is invalid or revoked." } }, 401);
      if (applyMode === "unavailable") return reply({ error: { code: "service_closed", message: "The board service has been closed." } }, 503);
      return reply(receiptFor(body.operation_id));
    }
    if (url.startsWith("/api/board/v1/operations/")) {
      if (operationMode === "unavailable") return reply({ error: { code: "temporarily_unavailable", message: "Lookup unavailable." } }, 503);
      return reply(Object.assign(receiptFor(decodeURIComponent(url.split("/").at(-1))), { receipt: receiptFor(decodeURIComponent(url.split("/").at(-1))) }));
    }
    if (url === "/data.json") {
      if (dataStatus === 401) return reply({ error: { code: "session_expired", message: "The Prism board session has expired." } }, 401);
      return reply({ epoch: "defect-epoch", version: dataVersion, envelope: dataEnvelope });
    }
    return reply({ error: { code: "not_found", message: "Fixture route is unavailable." } }, 404);
  };
  const dialogNow = () => document.getElementById("transition-dialog");
  const boardNow = () => document.getElementById("board-view");
  const reset = () => {
    if (state.transitionPreview) closeTransitionPreview();
    applyMode = "ok"; operationMode = "applied"; heldApply = null; sessionStatus = 200; dataStatus = 200;
    dataEnvelope = beforeEnvelope; dataVersion = 1;
    calls.length = 0;
    connect();
    adoptData(beforeEnvelope);
    switchView("board");
    renderBoard();
  };
  const openReview = (featureId, acknowledge) => {
    const button = boardNow().querySelectorAll("[data-board-action]").find(item => item.dataset.boardFeatureId === featureId);
    assert(button, "no connected review button for " + featureId);
    button.__listeners.click[0]({ preventDefault() {}, stopPropagation() {} });
    if (acknowledge) {
      const ack = dialogNow().querySelector("[data-connected-ack]");
      ack.checked = true;
      ack.__listeners.change[0]();
    }
    return state.transitionPreview;
  };
  const click = selector => { const element = dialogNow().querySelector(selector); assert(element, "dialog has no " + selector); element.__listeners.click[0](); };
  const alertText = () => { const match = dialogNow().innerHTML.match(/role="alert">([^<]*)</); return match ? match[1] : ""; };

  // D4: a live update that arrives before the apply response must not mark the preview stale.
  reset();
  let preview = openReview("F-live", true);
  assert(preview.previewId && !dialogNow().querySelector("[data-connected-apply]").disabled, "the acknowledged preview did not offer Apply");
  applyMode = "held";
  click("[data-connected-apply]");
  assert(preview.operationState === "applying" && heldApply, "Apply did not reach the service while its response was held");
  dataEnvelope = afterEnvelope; dataVersion = 2;
  adoptData(afterEnvelope);
  assert(!preview.staleReason && !dialogNow().innerHTML.includes("Feature source changed"), "a live update during an in-flight apply marked the preview stale: " + preview.staleReason);
  heldApply.chain.settle({ ok: true, status: 200, json: () => syncChain(receiptFor(heldApply.body.operation_id)) });
  assert(preview.operationState === "applied" && !preview.staleReason, "the applied receipt did not settle the preview");
  assert(alertText().startsWith("Operation applied") && !dialogNow().innerHTML.includes("Feature source changed"), "the stale warning outranked the applied outcome: " + alertText());
  assert(calls.filter(item => item.path === "/api/board/v1/apply").length === 1, "the apply was submitted more than once");
  markLiveRefreshUnavailable("disconnected");
  assert(alertText().startsWith("Operation applied"), "a later stream drop replaced the applied outcome with a stale warning: " + alertText());

  // D4 after a lost response: the live stage change is the operation's effect, and the retrieved receipt wins.
  reset();
  applyMode = "lost"; operationMode = "unavailable";
  preview = openReview("F-lost", true);
  click("[data-connected-apply]");
  assert(preview.operationState === "outcome unknown" && preview.operationId, "a lost apply response was not reported as an unknown outcome");
  dataEnvelope = afterEnvelope; dataVersion = 2;
  adoptData(afterEnvelope);
  assert(!preview.staleReason && !dialogNow().innerHTML.includes("Feature source changed"), "a live update after a lost response marked the preview stale");
  operationMode = "applied";
  click("[data-connected-check-operation]");
  assert(preview.operationState === "applied" && alertText().startsWith("Operation applied"), "the retrieved receipt was shadowed after a lost response: " + alertText());
  assert(calls.filter(item => item.path === "/api/board/v1/apply").length === 1, "a lost response resubmitted the apply");

  // D2: a stale rejection is not an unknown outcome. The service's message shows, inputs stay, a fresh preview is offered.
  reset();
  applyMode = "stale";
  preview = openReview("F-rejected", false);
  let dialog = dialogNow();
  const skip = dialog.querySelector("[data-connected-skip]");
  skip.checked = true; skip.__listeners.change[0]();
  dialog = dialogNow();
  const reason = dialog.querySelector("[data-connected-skip-reason]");
  reason.value = "PO accepts the delay."; reason.__listeners.input[0]();
  dialog.querySelector("[data-connected-repreview]").__listeners.click[0]();
  const ack = dialogNow().querySelector("[data-connected-ack]");
  ack.checked = true; ack.__listeners.change[0]();
  assert(!dialogNow().querySelector("[data-connected-apply]").disabled, "the skip proposal preview did not offer Apply");
  const callsBeforeApply = calls.length;
  click("[data-connected-apply]");
  dialog = dialogNow();
  assert(!preview.operationId && !preview.operationState && preview.staleReason.includes("changed after this preview"), "a stale rejection was not treated as rejected before an operation existed");
  assert(alertText().includes("Relevant source knowledge/wiki/features/F-rejected.md changed after this preview."), "the service's stale message was not shown: " + alertText());
  assert(!dialog.innerHTML.includes("Operation ID") && !dialog.querySelector("[data-connected-check-operation]") && !dialog.querySelector("[data-connected-recover]"), "a stale rejection offered Inspect or Recover for an operation that never existed");
  assert(calls.slice(callsBeforeApply).every(item => !item.path.startsWith("/api/board/v1/operations/")), "a stale rejection looked up an operation that never existed");
  assert(dialog.querySelector("[data-connected-apply]").disabled && preview.previewId === null && preview.payload.applicable === false, "a rejected preview could still be applied");
  assert(preview.skipAdvisory === true && preview.skipReason === "PO accepts the delay." && dialog.innerHTML.includes("PO accepts the delay."), "the typed skip proposal was not kept");
  const previewAgain = dialog.querySelector("[data-connected-preview-again]");
  assert(previewAgain, "no fresh preview was offered after a stale rejection");
  previewAgain.__listeners.click[0]();
  const freshRequest = JSON.parse(calls.filter(item => item.path === "/api/board/v1/previews/transition").at(-1).options.body);
  assert(freshRequest.inputs.skip_advisory_review === true && freshRequest.inputs.advisory_skip_reason === "PO accepts the delay." && freshRequest.inputs.semantic_review_acknowledged === false, "the fresh preview did not keep the typed inputs or asked for approval it was not given: " + JSON.stringify(freshRequest));
  assert(!preview.staleReason && preview.semanticAcknowledged === false && dialogNow().querySelector("[data-connected-apply]").disabled, "a fresh preview was approved without a new acknowledgement");

  // D2 counterpart: a service failure leaves the outcome unknown, so Inspect stays offered.
  reset();
  applyMode = "unavailable"; operationMode = "unavailable";
  preview = openReview("F-down", true);
  click("[data-connected-apply]");
  assert(preview.operationState === "outcome unknown" && preview.operationId && dialogNow().querySelector("[data-connected-check-operation]"), "a 5xx apply answer was not left as an unknown outcome with Inspect");

  // D5: a 401 during apply shows the session-expired message with Reconnect, not an unknown outcome.
  reset();
  applyMode = "unauthorized";
  preview = openReview("F-revoked", true);
  click("[data-connected-apply]");
  dialog = dialogNow();
  assert(state.boardConnection === "unauthenticated" && !preview.operationId && !preview.operationState, "a 401 apply left an operation behind");
  assert(alertText().includes("The board session has expired. Reconnect"), "a 401 apply did not show the session-expired message: " + alertText());
  assert(!dialog.querySelector("[data-connected-check-operation]") && !dialog.querySelector("[data-connected-recover]") && !dialog.innerHTML.includes("Operation ID"), "a 401 apply offered Inspect or Recover");
  assert(dialog.querySelector("[data-connected-apply]").disabled, "Apply stayed enabled after the session ended");
  assert(calls.every(item => !item.path.startsWith("/api/board/v1/operations/")), "a 401 apply looked up an operation that never existed");
  let reloads = 0;
  window.location = { reload() { reloads += 1; } };
  click("[data-connected-reconnect]");
  assert(reloads === 1, "the dialog's Reconnect did not return to the token sign-in");

  // D3: the event stream and a fetch that get 401 show the expired session instead of a silent STALE.
  const priorEventSource = globalThis.EventSource, priorSetInterval = globalThis.setInterval, priorSetTimeout = globalThis.setTimeout;
  const sources = [], timers = [];
  globalThis.EventSource = function () { this.onmessage = null; this.onerror = null; sources.push(this); };
  globalThis.setInterval = () => 1;
  globalThis.setTimeout = (callback, delay) => { timers.push({ callback, delay }); return timers.length; };
  reset();
  sessionStatus = 401;
  openReview("F-live", true);
  initLive();
  assert(sources.length === 1, "live mode did not open the event stream");
  sources[0].onerror();
  assert(state.boardConnection === "unauthenticated", "a stream error answered with 401 left the board looking connected");
  assert(document.getElementById("board-session").innerHTML.includes("Board session expired") && document.getElementById("board-session").innerHTML.includes("Reconnect"), "the header did not offer Reconnect after the stream was refused");
  assert(document.getElementById("freshness").innerHTML.includes("STALE"), "the header went green while the session was gone");
  assert(alertText().includes("The board session has expired. Reconnect") && dialogNow().querySelector("[data-connected-reconnect]") && dialogNow().querySelector("[data-connected-apply]").disabled, "the open review did not show the expired session");
  const probesBefore = calls.filter(item => item.path === "/api/board/v1/auth/session").length;
  sources[0].onerror();
  assert(calls.filter(item => item.path === "/api/board/v1/auth/session").length === probesBefore, "an already-expired session was probed again");
  reset();
  dataStatus = 401;
  initLive();
  sources[1].onmessage({ data: "1", lastEventId: "defect-epoch:1" });
  assert(state.boardConnection === "unauthenticated" && document.getElementById("board-session").innerHTML.includes("Board session expired"), "a snapshot fetch answered with 401 did not show the expired session");
  assert(!timers.some(timer => timer.delay === 1500), "a snapshot fetch answered with 401 kept retrying");
  globalThis.EventSource = priorEventSource; globalThis.setInterval = priorSetInterval; globalThis.setTimeout = priorSetTimeout;

  // D1: a drop the board refuses is explained when the drag ends; same-column and leaving the board are not.
  reset();
  const toastEl = document.getElementById("toast");
  const srEl = document.getElementById("sr-status");
  const dragCard = () => boardNow().querySelectorAll(".card[data-id]").find(item => item.dataset.id === "F-drag");
  const column = stage => boardNow().querySelectorAll(".column[data-stage]").find(item => item.dataset.stage === stage);
  const startDrag = () => { const card = dragCard(); card.__listeners.dragstart[0]({ currentTarget: card, preventDefault() {}, dataTransfer: { setData() {} } }); return card; };
  const hover = target => target.__listeners.dragover[0]({ currentTarget: target, preventDefault() {}, dataTransfer: {} });
  toastEl.textContent = ""; srEl.textContent = "";
  let card = startDrag();
  hover(column("in-dev"));
  column("in-dev").__listeners.dragleave[0]({ currentTarget: column("in-dev") });
  card.__listeners.dragend[0]();
  assert(toastEl.textContent === "Unsupported drop - card stayed in its source stage" && srEl.textContent.includes("stayed in its source stage") && state.drag === null, "a refused drop was not explained: " + toastEl.textContent + " / " + srEl.textContent);
  toastEl.textContent = ""; srEl.textContent = "";
  card = startDrag();
  hover(column("specified"));
  card.__listeners.dragend[0]();
  assert(toastEl.textContent === "" && srEl.textContent === "Workflow drag canceled.", "a same-column drag was explained as an unsupported drop: " + toastEl.textContent + " / " + srEl.textContent);
  card = startDrag();
  hover(column("in-dev"));
  column("in-dev").__listeners.dragleave[0]({ currentTarget: column("in-dev"), relatedTarget: { closest() { return null; } } });
  card.__listeners.dragend[0]();
  assert(toastEl.textContent === "" && srEl.textContent === "Workflow drag canceled.", "a drag released outside the board was explained as an unsupported drop");
  card = startDrag();
  hover(column("ready-for-design"));
  card.__listeners.dragend[0]();
  assert(toastEl.textContent === "" && srEl.textContent === "Workflow drag canceled.", "a canceled drag over a supported column was explained as an unsupported drop");

  // A live re-render keeps focus on the control the person was on instead of sending it to the heading.
  reset();
  openReview("F-live", true);
  dialogNow().querySelector("[data-connected-apply]").focus();
  adoptData(beforeEnvelope);
  assert(document.activeElement && document.activeElement.hasAttribute("data-connected-apply") && document.activeElement.isConnected !== false, "a live re-render moved focus off the control the person was on");
  dialogNow().querySelector("#transition-dialog-title").focus();
  adoptData(beforeEnvelope);
  assert(document.activeElement && document.activeElement.id === "transition-dialog-title", "a re-render with focus on the heading did not keep it there");

  // D8 and D9: one Tab trap for every modal, computed at key time, covering focus that is not on a listed control.
  const rankOf = element => element.rank;
  const focusable = (name, rank) => ({ name, rank, hidden: false, disabled: false, getAttribute() { return null; }, focus() { document.activeElement = this; },
    compareDocumentPosition(other) { return rankOf(other) < rankOf(this) ? 2 : rankOf(other) > rankOf(this) ? 4 : 0; } });
  const heading = focusable("heading", 1), summaryRow = focusable("summary", 2), middle = focusable("middle", 5), closeButton = focusable("close", 8), applyButton = focusable("apply", 9);
  const outside = focusable("outside", -3);
  const fakeDialog = { rank: 0, listed: [summaryRow, middle, closeButton, applyButton], querySelectorAll() { return this.listed; }, contains(element) { return !!element && element.rank >= 0; }, focus() { document.activeElement = this; } };
  const press = (active, shiftKey) => {
    document.activeElement = active;
    const event = { key: "Tab", shiftKey, prevented: false, preventDefault() { this.prevented = true; } };
    trapDialogTab(event, fakeDialog);
    return event;
  };
  let tab = press(heading, true);
  assert(tab.prevented && document.activeElement === applyButton, "Shift+Tab from the dialog heading left the dialog");
  tab = press(fakeDialog, true);
  assert(tab.prevented && document.activeElement === applyButton, "Shift+Tab from the dialog itself left the dialog");
  tab = press(summaryRow, true);
  assert(tab.prevented && document.activeElement === applyButton, "Shift+Tab from the first file-change row did not wrap to the last control");
  tab = press(applyButton, false);
  assert(tab.prevented && document.activeElement === summaryRow, "Tab from the last control did not wrap to the first");
  tab = press(middle, false);
  assert(!tab.prevented && document.activeElement === middle, "Tab between controls was taken over from the browser");
  tab = press(middle, true);
  assert(!tab.prevented, "Shift+Tab between controls was taken over from the browser");
  tab = press(outside, false);
  assert(tab.prevented && document.activeElement === summaryRow, "Tab with focus outside the dialog did not come back to its first control");
  tab = press(outside, true);
  assert(tab.prevented && document.activeElement === applyButton, "Shift+Tab with focus outside the dialog did not come back to its last control");
  applyButton.disabled = true;
  tab = press(closeButton, false);
  assert(tab.prevented && document.activeElement === summaryRow, "a disabled control was still counted as the last focusable element");
  applyButton.disabled = false;
  fakeDialog.listed = [];
  tab = press(heading, false);
  assert(tab.prevented && document.activeElement === fakeDialog, "an empty dialog did not keep focus on itself");

  reset();
  closeTransitionPreview();
  state.boardPendingOperations = [{ operation_id: "op-pending", state: "pending", created_at: "2026-09-22T12:00:00Z" }];
  renderHeader();
  document.getElementById("board-session").querySelector("[data-board-operations]").__listeners.click[0]();
  const operationsModal = dialogNow().querySelector(".transition-dialog");
  assert(dialogNow().innerHTML.includes("Review pending operations") && operationsModal.__listeners.keydown && operationsModal.__listeners.keydown.length === 1, "the pending-operations dialog did not bind the shared keyboard handler");
  const operationControls = operationsModal.querySelectorAll("button");
  const lastControl = operationControls.filter(item => !item.disabled).at(-1);
  const firstControl = operationControls.filter(item => !item.disabled)[0];
  document.activeElement = lastControl;
  let operationTab = { key: "Tab", shiftKey: false, prevented: false, preventDefault() { this.prevented = true; } };
  operationsModal.__listeners.keydown[0](operationTab);
  assert(operationTab.prevented && document.activeElement === firstControl, "Tab from the last control of the pending-operations dialog left it");
  document.activeElement = firstControl;
  operationTab = { key: "Tab", shiftKey: true, prevented: false, preventDefault() { this.prevented = true; } };
  operationsModal.__listeners.keydown[0](operationTab);
  assert(operationTab.prevented && document.activeElement === lastControl, "Shift+Tab from the first control of the pending-operations dialog left it");
  closeTransitionPreview();
  state.boardPendingOperations = [];
  globalThis.__boardDefectsChecked = true;
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
  const knowledgeRoot = !!data.workspace && data.workspace.purpose === "knowledge-root";
  if (knowledgeRoot) {
    // A knowledge root with no features says so instead of teaching the feature pipeline.
    if (html.includes("KNOWLEDGE ROOT") && html.includes("No features yet") && !html.includes("FIRST-RUN.TXT")) {
      console.log("FIRSTRUN OK — knowledge root guide rendered for a workspace with no features");
    } else {
      console.error("FIRSTRUN MISSING — knowledge root did not render its no-features guide");
      process.exit(1);
    }
  } else if (html.includes("WORKSPACE SETUP") && html.includes("FIRST-RUN.TXT") && html.includes("pipe-track")) {
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
if (checkTransitions) {
  if (!sandbox.__liveRecoveryChecked) { console.error("LIVE RECOVERY FAILED - reconnect recovery checks did not complete"); process.exit(1); }
  console.log("LIVE RECOVERY OK - same-version reconnect validates the snapshot before restoring Copy and LIVE");
  console.log("TRANSITIONS OK - copy-only preview, source-preserving drag, refresh invalidation, and safe fallback passed");
}
if (checkConnectedBoard) {
  if (!sandbox.__connectedBoardChecked) { console.error("CONNECTED BOARD FAILED - connected service regressions did not complete"); process.exit(1); }
  console.log("CONNECTED BOARD OK - service-only preview, blocked drop, exact diff, PO skip, semantic acknowledgement, apply receipt, and refreshed view passed");
}
if (checkBoardDefects) {
  if (!sandbox.__boardDefectsChecked) { console.error("BOARD DEFECTS FAILED - the board defect regressions did not complete"); process.exit(1); }
  console.log("BOARD DEFECTS OK - in-flight apply never goes stale, rejected applies are not unknown outcomes, expired sessions offer Reconnect, refused drops are explained, and every modal keeps Tab focus");
}
// sanity: header + views wired
const viewsEl = elements["views"];
if (viewsEl && viewsEl.__listeners.click) console.log("EVENTS OK — view switcher has click handler");
else { console.error("EVENTS MISSING — view switcher not wired"); process.exit(1); }
