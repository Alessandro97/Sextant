/* The links a failed fetch offers, as hrefs. Printed one per line. */
const { loadApp } = require("./fake_dom.js");
loadApp();

const panel = document.getElementById("tab-marker");
try {
  showFetchFailures([{ key: "k", reason: "no pdf", landing_pages: [
    "https://zenodo.org/record/1", "http://hdl.handle.net/2117/1",
    "javascript:alert(document.domain)", "data:text/html,<b>x</b>", "  JavaScript:alert(1)",
  ] }]);
  const walk = (n) => [n, ...(n.kids || []).flatMap(walk)];
  for (const a of walk(panel).filter((n) => n.href !== undefined)) console.log(`href :: ${a.href}`);
} catch (e) {
  console.log(`THREW :: ${e.name}: ${e.message}`);
}
