const { loadApp } = require("./fake_dom.js");

try {
  loadApp();
  console.log("  app.js executed top-to-bottom with no error");
} catch (e) {
  console.log("  *** THREW AT LOAD:", e.message);
  console.log("  ", (e.stack||"").split("\n")[1]);
}
