/* The Note on a citation card, in the two states the card is painted in.
 * Printed as `label :: note` so the test can tell them apart. */
const { loadApp } = require("./fake_dom.js");
loadApp();

const marker = {
  status: "verified", quantity: { value: "12.4", unit: "Gbps" },
  cited_page: 7, reason: null,
};

const cases = [
  ["before an assessment", null],               // selectMarker's first paint
  ["assessment with no score", { score: null }],
];

// A reason the server wrote, when the test passes one: what it says has to
// survive the filter that drops reasons restating the note.
if (process.argv[2]) cases.push(["with the server's reason", null, process.argv[2]]);

for (const [label, assessment, reason] of cases) {
  try {
    console.log(`${label} :: ${noteFor({ ...marker, reason: reason || null }, assessment)}`);
  } catch (e) {
    console.log(`${label} :: THREW ${e.name}: ${e.message}`);
  }
}
