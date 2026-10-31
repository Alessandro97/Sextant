from pathlib import Path

import httpx
import pytest

from sextant.refs.http import FakeFetcher, HttpFetcher, Unavailable


def test_fake_returns_registered_json():
    f = FakeFetcher(json_by_url={"https://x/1": {"ok": True}})
    assert f.json("https://x/1") == {"ok": True}


def test_fake_returns_none_for_unregistered_urls():
    assert FakeFetcher().json("https://nope") is None


def test_fake_records_every_url_requested():
    f = FakeFetcher(json_by_url={"https://x/1": {}})
    f.json("https://x/1")
    f.json("https://x/2")
    assert f.calls == ["https://x/1", "https://x/2"]


def test_fake_download_writes_registered_bytes(tmp_path):
    f = FakeFetcher(bytes_by_url={"https://x/p.pdf": b"%PDF-1.7 fake"})
    dest = tmp_path / "out.pdf"
    assert f.download("https://x/p.pdf", dest) is True
    assert dest.read_bytes().startswith(b"%PDF")


def test_fake_download_returns_false_and_writes_nothing_when_absent(tmp_path):
    dest = tmp_path / "out.pdf"
    assert FakeFetcher().download("https://nope", dest) is False
    assert not dest.exists()


def test_fake_can_simulate_a_network_error():
    f = FakeFetcher(errors={"https://boom"})
    with pytest.raises(Unavailable):
        f.json("https://boom")
    with pytest.raises(Unavailable):
        f.text("https://boom")
    with pytest.raises(Unavailable):
        f.download("https://boom", Path("/nonexistent/x.pdf"))


def test_the_user_agent_names_the_real_repository():
    """API operators who want to complain about the traffic follow this link.
    It must lead to this project, not to a name anyone could register."""
    assert "https://github.com/Alessandro97/Sextant" in HttpFetcher()._client.headers["user-agent"]


class _Answering(httpx.BaseTransport):
    """Answers every request with one status, and counts them."""

    def __init__(self, status, body=b"{}", headers=None):
        self.status, self.body, self.headers, self.requests = status, body, headers or {}, 0

    def handle_request(self, request):
        self.requests += 1
        return httpx.Response(self.status, content=self.body, headers=self.headers)


PUBLIC = "93.184.216.34"


def _resolver(table=None):
    """getaddrinfo without the network: every name is public unless listed."""
    def resolve(host, port, *args, **kwargs):
        address = (table or {}).get(host, host if host[:1].isdigit() or ":" in host else PUBLIC)
        return [(2, 1, 6, "", (address, port))]
    return resolve


def _fetcher(transport, table=None):
    fetcher = HttpFetcher(resolve=_resolver(table))
    fetcher._client = httpx.Client(transport=transport)
    return fetcher


@pytest.mark.parametrize("status", [429, 500, 502, 503, 401, 403])
def test_a_source_that_does_not_answer_is_unavailable_not_empty(status):
    """arXiv answered a burst of queries with 429, and every one was recorded
    as "no matching arxiv entry" -- for papers that are on arXiv."""
    with pytest.raises(Unavailable, match=str(status)):
        _fetcher(_Answering(status)).json("https://api.example/x")
    with pytest.raises(Unavailable, match=str(status)):
        _fetcher(_Answering(status)).text("https://api.example/x")


@pytest.mark.parametrize("status", [404, 410])
def test_a_source_that_says_no_such_thing_is_an_answer(status):
    assert _fetcher(_Answering(status)).json("https://api.example/x") is None


def test_a_timeout_is_unavailable():
    class Slow(httpx.BaseTransport):
        def handle_request(self, request):
            raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(Unavailable, match="timed out"):
        _fetcher(Slow()).json("https://api.example/x")


def test_an_answer_that_is_not_json_is_unavailable():
    """A proxy's HTML error page arrives as 200 often enough."""
    with pytest.raises(Unavailable):
        _fetcher(_Answering(200, b"<html>maintenance</html>")).json("https://api.example/x")


class _Clock:
    """Time that passes only when someone sleeps."""

    def __init__(self):
        self.now, self.slept = 1000.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(round(seconds, 3))
        self.now += seconds


def _paced(transport, clock, **kwargs):
    fetcher = HttpFetcher(clock=clock, sleep=clock.sleep, resolve=_resolver(), **kwargs)
    fetcher._client = httpx.Client(transport=transport)
    return fetcher


def test_requests_to_arxiv_are_three_seconds_apart():
    """arXiv's API terms ask for one request every three seconds, and a cold
    fetch that sent them back to back was throttled within a few."""
    clock = _Clock()
    fetcher = _paced(_Answering(200, b"<feed/>"), clock)

    fetcher.text("https://export.arxiv.org/api/query?a")
    clock.now += 1.0
    fetcher.text("https://export.arxiv.org/api/query?b")

    assert clock.slept == [2.0]


def test_hosts_without_a_stated_limit_are_not_slowed():
    clock = _Clock()
    fetcher = _paced(_Answering(200), clock)

    fetcher.json("https://api.openalex.org/works/a")
    fetcher.json("https://api.openalex.org/works/b")

    assert clock.slept == []


def test_pacing_is_per_host():
    clock = _Clock()
    fetcher = _paced(_Answering(200, b"<feed/>"), clock)

    fetcher.text("https://export.arxiv.org/api/query?a")
    fetcher.text("https://api.openalex.org/works/a")

    assert clock.slept == []


def test_a_short_retry_after_is_waited_out_once():
    class ThenFine(httpx.BaseTransport):
        def __init__(self):
            self.requests = 0

        def handle_request(self, request):
            self.requests += 1
            if self.requests == 1:
                return httpx.Response(429, headers={"Retry-After": "5"})
            return httpx.Response(200, content=b"{}")

    clock, transport = _Clock(), ThenFine()

    assert _paced(transport, clock).json("https://api.example/x") == {}
    assert clock.slept == [5.0]
    assert transport.requests == 2


def test_a_long_retry_after_is_not_waited_for():
    """Minutes of silence inside one reference would stall the whole run;
    the reference is reported as worth trying again instead."""
    clock, transport = _Clock(), _Answering(429, headers={"Retry-After": "600"})

    with pytest.raises(Unavailable, match="429"):
        _paced(transport, clock).json("https://api.example/x")
    assert clock.slept == [] and transport.requests == 1


def test_a_second_refusal_is_not_retried_again():
    clock, transport = _Clock(), _Answering(503, headers={"Retry-After": "2"})

    with pytest.raises(Unavailable, match="503"):
        _paced(transport, clock).json("https://api.example/x")
    assert transport.requests == 2


def test_downloads_take_their_turn_too(tmp_path):
    clock = _Clock()
    fetcher = _paced(_Answering(200, b"%PDF-1.7 x"), clock)

    assert fetcher.download("https://arxiv.org/pdf/1", tmp_path / "a.pdf")
    assert fetcher.download("https://arxiv.org/pdf/2", tmp_path / "b.pdf")

    assert clock.slept == [15.0]


def test_a_download_is_kept_only_if_it_starts_as_expected(tmp_path):
    clock = _Clock()
    zipped = _paced(_Answering(200, b"PK\x03\x04 zip"), clock)
    html = _paced(_Answering(200, b"<html>login</html>"), clock)

    assert zipped.download("https://a/x.zip", tmp_path / "x.zip", expect=b"PK")
    assert not zipped.download("https://a/x.zip", tmp_path / "y.pdf")
    assert not html.download("https://a/x.pdf", tmp_path / "z.pdf")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.zip"]


def test_a_download_past_the_cap_is_abandoned(tmp_path, monkeypatch):
    import sextant.refs.http as http

    monkeypatch.setattr(http, "MAX_DOWNLOAD_BYTES", 100)
    fetcher = _paced(_Answering(200, b"%PDF" + b"0" * 500), _Clock())

    assert not fetcher.download("https://a/x.pdf", tmp_path / "x.pdf")
    assert not (tmp_path / "x.pdf").exists()


def test_a_request_the_source_calls_malformed_is_an_answer_not_an_outage():
    """arXiv answered 400 to a query built from a title with no Latin words.
    Trying again later would only be refused again."""
    assert _fetcher(_Answering(400)).json("https://api.example/x") is None


@pytest.mark.parametrize("host, seconds", [
    ("arxiv.org", 15.0), ("www.biorxiv.org", 7.0), ("www.medrxiv.org", 7.0),
    ("pmc.ncbi.nlm.nih.gov", 1.0), ("www.ebi.ac.uk", 10.0)])
def test_hosts_are_asked_no_faster_than_their_robots_txt_allows(host, seconds):
    """Sextant is not a crawler, but published, it is many readers at once."""
    from sextant.refs.http import INTERVALS

    assert INTERVALS[host] == seconds


def test_the_readers_address_is_not_sent_to_every_host():
    """It went in the User-Agent, so every host a metadata record names -- and
    every host those redirect to -- learned it, with the reader's IP and when.
    Crossref, PMC and Unpaywall are sent it as a parameter instead."""
    import sextant.refs.http as http

    assert "mailto" not in http.USER_AGENT and "@" not in http.USER_AGENT


@pytest.mark.parametrize("status", [429, 500, 503])
def test_a_download_the_host_did_not_answer_is_unavailable(tmp_path, status):
    with pytest.raises(Unavailable, match=str(status)):
        _paced(_Answering(status), _Clock()).download("https://a/x.pdf", tmp_path / "x.pdf")


@pytest.mark.parametrize("status", [401, 403, 404, 410])
def test_a_download_the_host_refused_is_just_false(tmp_path, status):
    """A publisher that refuses scripts will refuse them tomorrow too."""
    assert not _paced(_Answering(status), _Clock()).download("https://a/x.pdf", tmp_path / "x.pdf")


def test_a_download_that_trickles_past_the_deadline_is_abandoned(tmp_path, monkeypatch):
    """A host sending one byte every few seconds held a fetch for as long as
    it liked; the read timeout applies to each read, not the whole."""
    import sextant.refs.http as http

    class Trickle(httpx.BaseTransport):
        def handle_request(self, request):
            def body():
                for _ in range(10):
                    clock.now += 30
                    yield b"%PDF"
            return httpx.Response(200, content=body())

    clock = _Clock()
    monkeypatch.setattr(http, "DOWNLOAD_DEADLINE", 100)
    with pytest.raises(Unavailable, match="too slow"):
        _paced(Trickle(), clock).download("https://a/x.pdf", tmp_path / "x.pdf")



class _Redirecting(httpx.BaseTransport):
    """One public host that redirects; records every URL actually requested."""

    def __init__(self, to):
        self.to, self.requested = to, []

    def handle_request(self, request):
        self.requested.append(str(request.url))
        if request.url.host == "public.example":
            return httpx.Response(302, headers={"Location": self.to})
        return httpx.Response(200, content=b"%PDF-1.7 internal")


@pytest.mark.parametrize("target", [
    "http://127.0.0.1:8765/api/browse?dir=/",
    "http://192.168.1.1/admin?reboot=1",
    "http://[::1]:631/",
    "http://router.lan/x",
])
def test_a_redirect_cannot_reach_this_machine_or_its_network(tmp_path, target):
    """A metadata record's PDF link redirected to a LAN address, and the
    reader's machine sent the request: blind, but a GET can still act."""
    transport = _Redirecting(target)
    fetcher = _fetcher(transport, {"router.lan": "10.0.0.1"})

    assert not fetcher.download("https://public.example/paper.pdf", tmp_path / "x.pdf")
    assert transport.requested == ["https://public.example/paper.pdf"]


def test_a_link_straight_to_a_private_address_is_not_requested(tmp_path):
    transport = _Redirecting("unused")
    fetcher = _fetcher(transport)

    assert not fetcher.download("http://10.1.2.3/x.pdf", tmp_path / "x.pdf")
    assert fetcher.json("http://127.0.0.1:8765/api/health") is None
    assert transport.requested == []


def test_a_redirect_to_a_public_host_is_followed(tmp_path):
    transport = _Redirecting("https://mirror.example/x.pdf")
    fetcher = _fetcher(transport)

    assert fetcher.download("https://public.example/x.pdf", tmp_path / "x.pdf")
    assert transport.requested[-1] == "https://mirror.example/x.pdf"


def test_redirects_do_not_go_on_for_ever(tmp_path):
    class Loop(httpx.BaseTransport):
        requests = 0

        def handle_request(self, request):
            Loop.requests += 1
            return httpx.Response(302, headers={"Location": "https://public.example/again"})

    with pytest.raises(Unavailable, match="redirects"):
        _fetcher(Loop()).download("https://public.example/x.pdf", tmp_path / "x.pdf")
    assert Loop.requests == 6


def test_only_http_is_spoken(tmp_path):
    transport = _Redirecting("unused")
    fetcher = _fetcher(transport)

    assert not fetcher.download("ftp://public.example/x.pdf", tmp_path / "x.pdf")
    assert fetcher.json("gopher://public.example/x") is None


def test_pacing_is_shared_by_every_fetcher(monkeypatch):
    """The viewer builds a fetcher per request and runs requests in a thread
    pool, so two fetches at once each kept their own turns."""
    clock = _Clock()
    first = _paced(_Answering(200, b"<feed/>"), clock)
    second = _paced(_Answering(200, b"<feed/>"), clock)

    first.text("https://export.arxiv.org/api/query?a")
    second.text("https://export.arxiv.org/api/query?b")

    assert clock.slept == [3.0]


@pytest.mark.parametrize("address", ["64:ff9b::7f00:1", "::ffff:7f00:1", "::127.0.0.1", "::ffff:10.0.0.1"])
def test_an_ipv6_spelling_of_a_private_ipv4_address_is_private(tmp_path, address):
    """NAT64 and IPv4-mapped forms report is_global for 127.0.0.1."""
    transport = _Redirecting("unused")
    fetcher = _fetcher(transport, {"sneaky.example": address})

    assert not fetcher.download("https://sneaky.example/x.pdf", tmp_path / "x.pdf")
    assert transport.requested == []


@pytest.mark.parametrize("url", ["https://public.example:99999/x.pdf", "https://[::zz]/x.pdf"])
def test_a_malformed_url_is_refused_quietly(tmp_path, url):
    assert not _fetcher(_Redirecting("unused")).download(url, tmp_path / "x.pdf")


class _Connections:
    """Stands in for opening sockets: records where each would have gone."""

    def __init__(self, monkeypatch):
        import httpcore

        self.made = []

        def connect(backend, host, port, *args, **kwargs):
            self.made.append(host)
            raise httpcore.ConnectError("no network in tests")

        monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", connect)


def test_a_name_that_turns_private_between_check_and_connect_is_refused(tmp_path, monkeypatch):
    """DNS rebinding: public when checked, 127.0.0.1 when connected to."""
    answers = iter(["93.184.216.34", "127.0.0.1", "127.0.0.1"])
    connections = _Connections(monkeypatch)
    fetcher = HttpFetcher(resolve=lambda host, port, *a, **k: [(2, 1, 6, "", (next(answers), port))])

    assert not fetcher.download("https://rebind.example/x.pdf", tmp_path / "x.pdf")
    assert connections.made == []


def test_the_address_connected_to_is_the_address_checked(monkeypatch):
    connections = _Connections(monkeypatch)
    fetcher = HttpFetcher(resolve=_resolver())

    with pytest.raises(Unavailable):
        fetcher.json("https://public.example/x")

    assert connections.made and set(connections.made) == {PUBLIC}
