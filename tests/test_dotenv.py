"""Reading a key out of .env.

The file was documented in the README, promised in .env.example and created by
readers for months, and nothing ever read it. The error message then told them
to create it. These are the properties that make the promise true.
"""

import os

import pytest

from sextant.dotenv import load_env, parse_env


def test_a_key_in_the_file_reaches_the_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-ant-from-file\n")

    applied = load_env(env)

    assert applied == {"ANTHROPIC_API_KEY": "sk-ant-from-file"}
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-from-file"


def test_an_explicit_variable_beats_the_file(tmp_path, monkeypatch):
    """`KEY=... sextant ask` is an instruction for this one run. A file left
    over from last month must not quietly overrule it."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-explicit")
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-ant-stale\n")

    assert load_env(env) == {}
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-explicit"


def test_override_is_available_but_not_the_default(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-explicit")
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-ant-file\n")

    load_env(env, override=True)

    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-file"


def test_a_missing_file_is_not_an_error(tmp_path):
    """Most runs need no key at all -- the viewer needs none ever."""
    assert load_env(tmp_path / "nothing-here") == {}


def test_a_directory_where_the_file_should_be_is_not_an_error(tmp_path):
    (tmp_path / ".env").mkdir()

    assert load_env(tmp_path / ".env") == {}


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("KEY=plain", {"KEY": "plain"}),
        ('KEY="double quoted"', {"KEY": "double quoted"}),
        ("KEY='single quoted'", {"KEY": "single quoted"}),
        ("export KEY=exported", {"KEY": "exported"}),
        ("  KEY = spaced  ", {"KEY": "spaced"}),
        ("# KEY=commented", {}),
        ("", {}),
        ("no-equals-sign", {}),
        ("=novalue", {}),
    ],
)
def test_the_format_it_accepts(line, expected):
    assert parse_env(line) == expected


def test_a_value_containing_an_equals_sign_survives():
    """Base64 and query strings both carry them; splitting on every one would
    truncate the key to nonsense."""
    assert parse_env("KEY=abc=def==") == {"KEY": "abc=def=="}


def test_comments_and_blanks_do_not_disturb_the_keys():
    assert parse_env(
        "# a comment\n\nANTHROPIC_API_KEY=sk-ant-x\n\n# trailing note\n"
    ) == {"ANTHROPIC_API_KEY": "sk-ant-x"}


@pytest.fixture
def restored_environ():
    """load_env writes os.environ directly; put it back afterwards."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.mark.parametrize("name", ["LD_PRELOAD", "NODE_OPTIONS", "ANTHROPIC_BASE_URL",
                                  "PATH", "DATABASE_URL"])
def test_only_the_key_is_read_from_the_file(tmp_path, restored_environ, name):
    """A .env usually belongs to some other project too, and one sitting next
    to a manuscript someone sent could set LD_PRELOAD for every program this
    one starts, or send the real key to another host."""
    before = os.environ.get(name)
    env = tmp_path / ".env"
    env.write_text(f"{name}=/tmp/from-the-file\nANTHROPIC_API_KEY=sk-ant-file\n")

    applied = load_env(env, override=True)

    assert os.environ.get(name) == before
    assert applied == {"ANTHROPIC_API_KEY": "sk-ant-file"}


def test_a_key_from_the_file_is_not_handed_to_other_programs(tmp_path, monkeypatch,
                                                            restored_environ):
    """The promise .env.example makes. It also matters for cost: Claude Code
    given a key in its environment uses it instead of the reader's login."""
    from sextant.dotenv import child_env

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-ant-file\n")
    load_env(env)

    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-file"
    assert "ANTHROPIC_API_KEY" not in child_env()
    assert child_env()["PATH"] == os.environ["PATH"]


def test_a_key_the_reader_exported_themselves_is_passed_on(monkeypatch, restored_environ):
    """Their shell's claude sees it too. Not ours to take away."""
    from sextant.dotenv import child_env

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-exported")

    assert child_env()["ANTHROPIC_API_KEY"] == "sk-ant-exported"


def test_a_key_exported_and_also_in_the_file_is_passed_on(tmp_path, monkeypatch):
    """The exported one wins, so it is the reader's own, not the file's."""
    import sextant.dotenv as dotenv

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-exported")
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-file\n")
    dotenv.load_env(tmp_path / ".env")

    assert dotenv.child_env()["ANTHROPIC_API_KEY"] == "sk-ant-exported"
