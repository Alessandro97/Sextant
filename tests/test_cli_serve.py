from typer.testing import CliRunner

from sextant.cli import app

runner = CliRunner()


def test_serve_is_a_registered_command():
    assert "serve" in runner.invoke(app, ["--help"]).output


def test_serve_builds_an_app_without_starting_a_server(tmp_path):
    """--check exercises the wiring without binding a port."""
    result = runner.invoke(app, ["serve", "--db", str(tmp_path / "p.db"), "--check"])

    assert result.exit_code == 0, result.output
    assert "ok" in result.output.lower()


def test_serve_defaults_to_loopback(tmp_path):
    """The library may hold unpublished work. Default must not be 0.0.0.0."""
    help_text = runner.invoke(app, ["serve", "--help"]).output

    assert "127.0.0.1" in help_text


def test_serve_tells_the_app_which_address_it_is_served_on(tmp_path, monkeypatch):
    """Requests addressed to any other name are refused, so the app has to
    know the one it was given."""
    import sextant.web.app as web

    seen = {}
    real = web.create_app

    def spy(**kwargs):
        seen.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(web, "create_app", spy)
    result = runner.invoke(app, ["serve", "--db", str(tmp_path / "p.db"),
                                 "--host", "192.168.1.5", "--check"])

    assert result.exit_code == 0, result.output
    assert seen["host"] == "192.168.1.5"


def test_serving_beyond_this_machine_says_there_is_no_login(tmp_path):
    result = runner.invoke(app, ["serve", "--db", str(tmp_path / "p.db"),
                                 "--host", "192.168.1.5", "--check"])

    assert "no login" in result.output


def test_serving_on_loopback_does_not_warn(tmp_path):
    result = runner.invoke(app, ["serve", "--db", str(tmp_path / "p.db"), "--check"])

    assert "no login" not in result.output


def test_a_wildcard_bind_is_refused_with_a_reason(tmp_path):
    """Requests must be addressed to the name served on, and 0.0.0.0 is no
    name a request carries: every one was refused while the warning said the
    viewer was open to anyone who could reach it."""
    for host in ("0.0.0.0", "::"):
        result = runner.invoke(app, ["serve", "--db", str(tmp_path / "p.db"),
                                     "--host", host, "--check"])
        assert result.exit_code != 0, host
        assert "address" in result.output, result.output
