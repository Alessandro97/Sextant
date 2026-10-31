/* Opening and putting away one pane's search, printed as `label :: facts`. */
const { loadApp } = require("./fake_dom.js");
loadApp();

const row = document.getElementById("find-manuscript-row");
const lens = document.getElementById("find-manuscript-toggle");
const box = document.getElementById("find-manuscript");

row.hidden = true;                       // as index.html ships it
box.value = "write throughput";

try {
  toggleFind("manuscript", true);
  console.log(`opened :: hidden=${row.hidden} expanded=${lens.getAttribute("aria-expanded")}`);

  toggleFind("manuscript", false);
  console.log(`closed :: hidden=${row.hidden} expanded=${lens.getAttribute("aria-expanded")}`
              + ` query=${JSON.stringify(box.value)}`);
} catch (e) {
  console.log(`THREW :: ${e.name}: ${e.message}`);
}
