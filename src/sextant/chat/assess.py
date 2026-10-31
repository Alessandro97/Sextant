"""Judge whether a cited paper is relevant to the sentence citing it.

For a citation carrying no quantity there is nothing to screen mechanically,
but the citation can still be right or wrong. Two things happen here, and they
are deliberately kept apart:

RETRIEVAL is free and instant, and produces the best-aligned passages. It is
shown as a place to look, never as a verdict. Measured on the real manuscript:
term overlap scores a claim against its own cited paper (median 0.27) exactly
the same as against a random other paper from the same library (median 0.28).
Every paper in a focused bibliography shares vocabulary, so overlap cannot
tell a real citation from a plausible substitute. Any threshold over it would
be a coin flip wearing a percentage.

JUDGEMENT costs a model call and is therefore on demand. Measured: asked about
a statement on wetland bird counts, the model returned `unrelated` for protein
folding, for a bond-pricing paper, and for a soil-moisture sensor survey -- so
it is not a yes-machine -- while returning `supports` with page evidence for
the paper actually cited.
"""

import re
from collections.abc import Callable, Sequence

from sextant.chat.retrieve import Excerpt

VERDICTS = ("supports", "related", "unrelated", "unclear")

_PROMPT = """You are checking one citation in an academic manuscript.

MANUSCRIPT: {title}
The sentence below ends with citation {marker}, so that citation is offered \
as the support for this sentence specifically -- not for the paragraph, and \
not for the manuscript's topic in general.

SENTENCE BEING CHECKED:
{claim}
{context}{finding}{rebuttal}
{source_label}
{body}

Judge only whether the CITED PAPER supports THIS SENTENCE, using only what is \
shown above. Two papers in the same field are not interchangeable: a paper that \
merely discusses the topic does not support a specific assertion about it.

Reply in exactly this form and nothing else:
VERDICT: supports | related | unrelated | unclear
SCORE: <0-5>
WHY: <two or three sentences: what the cited paper does and does not \
establish for this sentence, and what you would do about it>
QUOTE: <p. N> <a sentence copied VERBATIM from the excerpts that carries the \
support, or the single word NONE>

"supports" -- an excerpt states or clearly entails the sentence.
"related" -- the paper is on this topic but no excerpt backs this sentence.
"unrelated" -- the paper is about something else.
"unclear" -- the excerpts are boilerplate, front matter, or plainly missed \
the subject, so they say nothing either way about this paper. Prefer this to \
"unrelated" whenever the retrieval looks to have failed rather than the \
citation: judging a paper you were shown the wrong pages of is worse than \
admitting you cannot tell.

SCORE is how well this citation is doing its job:
5 -- an excerpt states the sentence outright; an ideal citation.
4 -- clearly supports it, with a small detail unevidenced.
3 -- supports the general point, but the specifics in this sentence are not \
in the excerpts.
2 -- the paper is on the topic and no more; a reader would want a better \
source for this sentence.
1 -- barely relevant; likely the wrong reference.
0 -- unrelated; remove or replace it.
Use 0 only when you are confident the paper does not belong here. If the \
excerpts look like the wrong pages rather than the wrong paper, that is \
"unclear" and no score is meaningful -- write SCORE: -1.

The QUOTE must be copied character for character from an excerpt above. Do \
not paraphrase it, do not join fragments, do not add ellipses. It is used to \
highlight the passage in the paper, so an inexact quote highlights nothing."""

_VERDICT_LINE = re.compile(r"VERDICT:\s*([a-z]+)", re.I)
_SCORE_LINE = re.compile(r"SCORE:\s*(-?\d)", re.I)
#: Stops at the next labelled line. With DOTALL it swallowed the QUOTE
#: lines below it and printed "QUOTE: NONE" as part of the reasoning.
_WHY_LINE = re.compile(r"WHY:\s*(.+?)(?=\n\s*(?:QUOTE|VERDICT|SCORE):|\Z)",
                       re.I | re.S)


#: A quoted supporting sentence: "QUOTE: <p. 7> Restored wetlands host ..."
_QUOTE_LINE = re.compile(r"^QUOTE:\s*(?:<?\s*p\.?\s*(\d+)\s*>?)?\s*(.+)$",
                         re.I | re.M)


#: Shown when the whole paper fits in the prompt, instead of the keyword
#: excerpts. Retrieval picking the passages meant a claim could be judged
#: absent because the abstract lost a keyword race -- measured: a manuscript
#: citing "3 Mbit/s" against a paper whose abstract says "3 Mbps" retrieved
#: neither the number nor the unit, and the citation was reported unsupported.
_WHOLE = "THE CITED PAPER IN FULL, one entry per page:"
_PARTIAL = ("EXCERPTS FROM THE CITED PAPER (retrieved by keyword overlap, so "
            "some may be irrelevant -- ignore those):")


def build_prompt(
    claim: str,
    excerpts: Sequence[Excerpt],
    *,
    title: str = "an academic manuscript",
    marker: str = "this citation",
    context: str = "",
    finding: str = "",
    rebuttal: str = "",
    whole_paper: bool = False,
) -> str:
    """Frame the question the way a reader would ask it.

    The earlier prompt handed over a bare sentence and some passages. It never
    said what the citing manuscript was, which citation was being checked, or
    that the passages came from keyword matching and might be noise -- and it
    asked for a verdict without asking what the verdict rested on.
    """
    body = "\n\n".join(f"[p. {e.page}] {e.text}" for e in excerpts)
    surrounding = ""
    if context and context.strip() and context.strip() != claim.strip():
        surrounding = f"\nPRECEDED BY: {context.strip()}\n"

    # What the mechanical check already established. A located figure is
    # evidence, not proof: a broad survey really does contain "21 GHz"
    # somewhere unrelated to the sentence citing it.
    mechanical = f"\nALREADY CHECKED: {finding.strip()}\n" if finding.strip() else ""

    # The author's case for the citation. Weighed, not obeyed: they know their
    # field and their intent, and they are also the person who wants the
    # citation to stand. If the excerpts do not bear them out, say so.
    argument = ""
    if rebuttal.strip():
        argument = (
            "\nTHE AUTHOR ARGUES THIS CITATION IS APT:\n"
            f"{rebuttal.strip()}\n\n"
            "Take that seriously -- they know the field and what they meant. "
            "But judge it against the excerpts, not instead of them. If it "
            "explains something you had missed, say so and revise. If the "
            "excerpts still do not carry the sentence, say that plainly and "
            "keep your score; agreeing to be agreeable helps nobody.\n"
        )

    return _PROMPT.format(
        claim=claim.strip(), body=body, title=title, marker=marker,
        context=surrounding, finding=mechanical, rebuttal=argument,
        source_label=_WHOLE if whole_paper else _PARTIAL,
    )


def quotes(reply: str) -> list[tuple[int | None, str]]:
    """(page, verbatim sentence) pairs the model offered as its evidence."""
    found: list[tuple[int | None, str]] = []
    for page, text in _QUOTE_LINE.findall(reply or ""):
        cleaned = " ".join(text.split()).strip("\u201c\u201d\"'")
        if not cleaned or cleaned.upper().startswith("NONE"):
            continue
        found.append((int(page) if page else None, cleaned))
    return found


def parse(reply: str) -> tuple[str, str, int | None]:
    """(verdict, why, score) from the model's reply.

    An unparseable reply becomes "unclear" rather than a guess: showing the
    wrong verdict is worse than showing none. A score outside 0-5 becomes
    None, which the interface renders as no score rather than as zero -- and
    zero means "remove this citation", which is not a thing to say by
    accident.
    """
    match = _VERDICT_LINE.search(reply or "")
    verdict = (match.group(1).lower() if match else "unclear")
    if verdict not in VERDICTS:
        verdict = "unclear"

    found = _SCORE_LINE.search(reply or "")
    score = int(found.group(1)) if found else None
    if score is not None and not 0 <= score <= 5:
        score = None

    why_match = _WHY_LINE.search(reply or "")
    why = " ".join(why_match.group(1).split()) if why_match else (reply or "").strip()
    return verdict, why[:900], score


def assess(
    claim: str,
    excerpts: Sequence[Excerpt],
    ask: Callable[[str], str],
    *,
    title: str = "an academic manuscript",
    marker: str = "this citation",
    context: str = "",
    finding: str = "",
    rebuttal: str = "",
    shown: Sequence[Excerpt] | None = None,
    whole_paper: bool = False,
) -> dict:
    """Ask the model whether the cited paper is relevant to `claim`.

    `excerpts` is what the model judges from. `shown` is what the reader is
    given as a place to look, and defaults to the same thing. They separate
    when the whole paper fits in the prompt: the model should not have to find
    the answer inside a keyword window, but four ranked passages are still a
    better thing to put in front of a person than forty pages.
    """
    if not claim.strip():
        return {"verdict": "unclear", "why": "no claim text at this citation",
                "excerpts": [], "quotes": [], "score": None}
    if not excerpts:
        return {"verdict": "unclear",
                "why": "nothing in the cited paper matched this sentence",
                "excerpts": [], "quotes": [], "score": None}

    try:
        reply = ask(build_prompt(claim, excerpts, title=title, marker=marker,
                                 context=context, finding=finding,
                                 rebuttal=rebuttal, whole_paper=whole_paper))
    except Exception as exc:  # noqa: BLE001 - surfaced to the user as text
        # Retryable, unlike the two returns above. Those are settled facts
        # about the citation; this is a blip on the way to asking, and
        # caching it as an answer left one bad moment stuck to a citation
        # for the life of the workspace.
        return {"verdict": "unclear", "why": f"could not reach Claude: {exc}",
                "excerpts": _rows(shown or excerpts), "quotes": [], "score": None,
                "failed": True}

    verdict, why, score = parse(reply)
    return {"verdict": verdict, "why": why, "score": score,
            "excerpts": _rows(shown or excerpts),
            "quotes": [{"page": p, "text": q} for p, q in quotes(reply)]}


def _rows(excerpts: Sequence[Excerpt]) -> list[dict]:
    return [{"page": e.page, "text": e.text, "score": round(e.score, 3)}
            for e in excerpts]
