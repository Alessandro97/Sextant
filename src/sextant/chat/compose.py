"""Turn retrieved excerpts into an answer.

Three backends, tried in this order:

  cli   `claude -p` -- the user's own Claude Code login. Default. No API key
        and no cost beyond the subscription they already have.
  api   ANTHROPIC_API_KEY, only when the CLI is unavailable or `prefer="api"`.
  copy  Neither present: return the grounded prompt for the user to paste.

The prompt goes to the subprocess on stdin and the subprocess is invoked with
an argument list, never through a shell. The question is untrusted text and
this runs on the user's own machine.

This is deliberately NOT the same as reading ~/.claude/.credentials.json and
constructing raw API calls from the token, which bypasses the product.
Invoking a documented non-interactive CLI the user installed and logged into
is using their own tool as intended.
"""

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence

from sextant.chat.retrieve import Excerpt
from sextant.dotenv import child_env

MODEL = "claude-opus-5"
CLI_TIMEOUT = 180

_INSTRUCTION = (
    "Answer the question using ONLY the excerpts below. Cite the page number "
    "for every claim, like (p. 4). If the excerpts do not contain the answer, "
    "say so plainly instead of guessing."
)


def build_prompt(question: str, title: str, excerpts: Sequence[Excerpt]) -> str:
    lines = [_INSTRUCTION, "", f"Paper: {title}", ""]
    for excerpt in excerpts:
        lines.append(f"[p. {excerpt.page}] {excerpt.text}")
        lines.append("")
    lines.append(f"Question: {question}")
    return "\n".join(lines)


def cli_available() -> bool:
    return shutil.which("claude") is not None


#: Claude Code with nothing to act with. The prompt carries text from PDFs
#: off the internet, and an instruction hidden in one must find no tool, no
#: MCP server, and no project folder to act on. Nor should each question leave
#: a saved session, manuscript text and all, in the reader's own history.
CLI_ARGS = ["claude", "-p", "--tools", "", "--strict-mcp-config",
            "--no-session-persistence"]


def ask_cli(prompt: str) -> str:
    """Run the prompt through the user's Claude Code login."""
    # An empty folder, not wherever `sextant serve` was started: that one's
    # CLAUDE.md and project settings would come along.
    with tempfile.TemporaryDirectory(prefix="sextant-") as empty:
        result = subprocess.run(
            CLI_ARGS,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=CLI_TIMEOUT,
            check=False,
            cwd=empty,
            env=child_env(),
        )
    if result.returncode != 0:
        # The CLI reports usage limits and auth problems on stdout, not
        # stderr, so taking stderr alone left the reader with a bare
        # "claude -p failed" and nothing to act on.
        detail = (result.stderr.strip() or result.stdout.strip())[:400]
        raise RuntimeError(detail or f"claude -p exited {result.returncode}")
    return result.stdout.strip()


def backends() -> dict:
    """What the server can currently use. Shown in the interface."""
    return {
        "cli": cli_available(),
        "api": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


def answer(
    question: str,
    title: str,
    excerpts: Sequence[Excerpt],
    api_key: str | None = None,
    prefer: str | None = None,
) -> dict:
    """Answer the question, or hand back the prompt if nothing can run it."""
    payload = {
        "excerpts": [
            {"page": e.page, "text": e.text, "score": round(e.score, 3)}
            for e in excerpts
        ],
        "text": "",
        "prompt": "",
        "error": "",
    }

    if not excerpts:
        return {**payload, "mode": "no-context"}

    prompt = build_prompt(question, title, excerpts)
    payload["prompt"] = prompt

    if prefer != "api" and cli_available():
        try:
            return {**payload, "mode": "cli", "text": ask_cli(prompt)}
        except (subprocess.TimeoutExpired, RuntimeError, OSError) as exc:
            # Fall through rather than lose the retrieval work.
            payload["error"] = f"claude -p failed: {exc}"

    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if key:
        try:
            return {**payload, "mode": "api", "text": _anthropic_call(key, prompt)}
        except Exception as exc:  # noqa: BLE001 - surfaced to the user as text
            payload["error"] = f"API call failed: {exc}"

    return {**payload, "mode": "copy"}


def _anthropic_call(api_key: str, prompt: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in response.content if b.type == "text")
