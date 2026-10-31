# Demo

An invented manuscript and the three papers it cites, for trying Sextant without your own files. Every author, title, figure and DOI here is made up; the DOIs use Crossref's 10.5555 test prefix.

To open it, run `uv run sextant serve` and click **Open document**. Paste the full path to `examples/demo/manuscript.pdf`, press Enter, then click **Go**. Click a citation number, then the cited passage under **Details**, to see it highlighted in the paper. From the command line, `uv run sextant audit examples/demo/manuscript.tex` checks the same three figures.

`sources/` holds the LaTeX the cited papers were built from.
