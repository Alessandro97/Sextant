/* The page reduced to what app.js touches: enough of a DOM that the script
 * runs, and no more. Shared, so a test can call a single function out of
 * app.js without standing up a browser. */
const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync("src/sextant/web/static/index.html", "utf8");
const ids = [...html.matchAll(/id="([^"]+)"/g)].map(m => m[1]);

const node = () => ({
  classList: { add(){}, remove(){}, toggle(){}, contains: () => false },
  style: {}, dataset: {}, insertBefore(){}, remove(){},
  // Children are kept, so a test can look at what a function actually built
  // rather than only at whether it threw.
  appendChild(n){ (this.kids ??= []).push(n); return n; },
  addEventListener(){}, removeEventListener(){}, querySelector: () => null,
  querySelectorAll: () => [], setPointerCapture(){}, releasePointerCapture(){},
  scrollIntoView(){}, getBoundingClientRect: () => ({top:0,left:0,width:800,height:600}),
  // Stored, not discarded: a test cannot check what a button says if the
  // harness throws the words away.
  set textContent(v){ this._text = String(v); }, get textContent(){ return this._text ?? ""; },
  set innerHTML(v){}, get innerHTML(){return "";},
  hidden: false, value: "", files: [], offsetWidth: 100, clientWidth: 800,
  parentElement: null, checked: true, disabled: false,
  focus(){}, select(){}, blur(){},
  setAttribute(k, v) { (this.attrs ??= {})[k] = String(v); },
  getAttribute(k) { return (this.attrs ??= {})[k] ?? null; },
});

/* One node per id, kept. A fresh object per lookup cannot show a test what a
   toggle did: the state would be thrown away with the node that held it. */
const byId = new Map();
global.document = {
  getElementById: (id) => {
    if (!ids.includes(id)) return null;
    if (!byId.has(id)) byId.set(id, node());
    return byId.get(id);
  },
  createElement: () => node(),
  querySelectorAll: () => [], querySelector: () => null,
  addEventListener(){}, body: node(), documentElement: { style: { setProperty(){} } },
};
global.window = { addEventListener(){}, innerWidth: 1400, location: {} };
global.localStorage = { getItem: () => null, setItem(){}, removeItem(){} };
global.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
global.FormData = class { append(){} };
global.IntersectionObserver = class { observe(){} unobserve(){} disconnect(){} };
global.navigator = { clipboard: { writeText: () => Promise.resolve() } };
global.Option = class {};

/** Run app.js in this context, which leaves its top-level functions callable. */
exports.loadApp = () =>
  new vm.Script(fs.readFileSync("src/sextant/web/static/app.js", "utf8"),
                { filename: "app.js" }).runInThisContext();
