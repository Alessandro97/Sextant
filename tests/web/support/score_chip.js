/* What N says when hovered, in a list and on a judged card. */
const { loadApp } = require("./fake_dom.js");
loadApp();

try {
  console.log(`in a list :: ${noScoreChip({ chip: true }).title}`);
  console.log(`on a judged card :: ${noScoreChip().title}`);
} catch (e) {
  console.log(`THREW :: ${e.name}: ${e.message}`);
}
