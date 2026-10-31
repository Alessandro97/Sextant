"""HTTP access, injected so nothing in the test suite touches the network."""

import ipaddress
import os
import socket
import threading
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import urljoin, urlsplit

from sextant.safefs import write_file

#: The reader's own address, for the services that ask for one: Crossref and
#: PMC give politer service with it, Unpaywall refuses requests without it.
#: Those three are sent it as a parameter, and no other host. It must not
#: default to a person: baked in, every installation would identify as
#: whoever published the code.
CONTACT = os.environ.get("SEXTANT_CONTACT", "")

#: What every request says it is. Never the reader's address: in a header it
#: reached every host a metadata record names, and every host those redirect
#: to, with the reader's IP and the time -- a reviewer's, say.
USER_AGENT = "sextant/0.1 (+https://github.com/Alessandro97/Sextant)"


class Unavailable(Exception):
    """The source could not be asked: throttled, failing, refusing, or out of
    reach. Not an answer about the work, so never cached and never reported
    as one -- arXiv's 429s were once recorded as "no matching arxiv entry"."""


#: Least time between two requests to one host, in seconds, where the host
#: states one. Sextant is not a crawler, but published it is many readers, so
#: a robots.txt Crawl-delay is honoured as well as an API's own terms.
INTERVALS = {
    # "make no more than one request every three seconds"
    # (https://info.arxiv.org/help/api/tou.html). A cold fetch that ignored
    # it was answered with 429 after a handful of queries.
    "export.arxiv.org": 3.0,
    "arxiv.org": 15.0,              # robots.txt Crawl-delay
    "www.biorxiv.org": 7.0,         # robots.txt Crawl-delay
    "www.medrxiv.org": 7.0,         # robots.txt Crawl-delay
    "www.ebi.ac.uk": 10.0,          # robots.txt Crawl-Delay
    "pmc.ncbi.nlm.nih.gov": 1.0,    # robots.txt Crawl-delay
    # Public pool: 5 requests a second for one DOI, observed 1 for a search
    # (https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/).
    "api.crossref.org": 1.0,
    # Unauthenticated requests share one pool and "may be further throttled"
    # (https://www.semanticscholar.org/product/api).
    "api.semanticscholar.org": 1.0,
}

#: The longest Retry-After worth waiting out inside one reference. Longer, and
#: the reference is reported as worth trying again rather than stalling a run.
RETRY_AFTER_CAP = 30.0

#: Larger than any paper or specification archive. A download past it is
#: abandoned rather than held in memory.
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024

#: Seconds one download may take in all. The client's timeout applies to each
#: read, so a host sending a byte at a time could otherwise hold a fetch open
#: for as long as it liked.
DOWNLOAD_DEADLINE = 120.0

#: Hops a request may take. Each one is checked before it is made.
MAX_REDIRECTS = 5

#: When each host may next be asked, per clock: shared by every fetcher in
#: the process, since the viewer builds one per request and runs requests in
#: a thread pool. A turn is reserved under the lock and waited for outside it.
_TURNS: dict[Callable[[], float], dict[str, float]] = {}
_TURNS_LOCK = threading.Lock()

#: Statuses that answer the request: there is no such thing (404, 410), or no
#: such question (400 -- asking again later only gets refused again). Every
#: other failure says only that the source did not answer.
_NO_SUCH_THING = frozenset({400, 404, 410})


class Fetcher(Protocol):
    """What a resolver is allowed to do to the network.

    json and text return None when the source answers that there is nothing
    there, and raise Unavailable when it does not answer at all.
    """

    def json(self, url: str) -> dict | None: ...
    def text(self, url: str) -> str | None: ...
    def download(self, url: str, dest: Path, expect: bytes = b"%PDF") -> bool: ...


class _NotPublic(Exception):
    """A URL that would reach this machine or its network, or not over HTTP."""


def _public_only_backend(resolve: Callable[..., list]):
    """An httpcore backend that resolves each name itself, refuses unless
    every address is public, and connects to the address it checked -- so a
    name cannot turn private between the check and the connection (DNS
    rebinding). TLS still verifies and names the host, not the address."""
    import httpcore

    class PublicOnly(httpcore.SyncBackend):
        def connect_tcp(self, host, port, timeout=None, local_address=None,
                        socket_options=None):
            addresses = public_addresses(host, port, resolve)
            if not addresses:
                raise _NotPublic(host)
            failure: Exception | None = None
            for address in addresses:
                try:
                    return super().connect_tcp(address, port, timeout, local_address,
                                               socket_options)
                except httpcore.ConnectError as exc:
                    failure = exc
            raise failure

    return PublicOnly()


class HttpFetcher:
    """The real one. A download that fails returns False; a lookup the source
    did not answer raises Unavailable, which the chain turns into a reason.

    Resolvers run in a chain over dozens of references; one flaky host must
    not abort an acquisition run.

    Every URL here came from someone else's metadata, and so did every
    redirect: a PDF link once redirected to a LAN address, and the reader's
    machine sent the request. So redirects are followed by hand, and each hop
    must be http(s) to a host that resolves only to public addresses. (A name
    that re-resolves between the check and the connection is not covered.)
    """

    def __init__(
        self,
        timeout: float = 20.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        resolve: Callable[..., list] = socket.getaddrinfo,
    ) -> None:
        import httpx

        self._clock, self._sleep, self._resolve = clock, sleep, resolve
        # Redirects are followed by _open, hop by hop, never by httpx; each
        # connection is made by a backend that checks the address it uses.
        transport = httpx.HTTPTransport()
        transport._pool._network_backend = _public_only_backend(resolve)
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT},
                                    transport=transport)

    def json(self, url: str) -> dict | None:
        response = self._answer(url)
        if response is None:
            return None
        try:
            return response.json()
        except ValueError:
            # A proxy's error page, served as 200.
            raise Unavailable("an answer that is not JSON") from None

    def text(self, url: str) -> str | None:
        response = self._answer(url)
        return None if response is None else response.text

    def _answer(self, url: str):
        """The 200 response, None for "no such thing", else Unavailable."""
        import httpx

        try:
            response = self._get(url)
        except _NotPublic:
            return None
        except httpx.TimeoutException:
            raise Unavailable("timed out") from None
        except httpx.HTTPError as exc:
            raise Unavailable(type(exc).__name__) from None
        if response.status_code == 200:
            return response
        if response.status_code in _NO_SUCH_THING:
            return None
        raise Unavailable(f"HTTP {response.status_code}")

    def _get(self, url: str):
        """GET, waiting out one short Retry-After."""
        response = self._open(url)
        if response.status_code in (429, 503):
            delay = _retry_after(response.headers.get("retry-after"), time.time())
            if delay is not None and delay <= RETRY_AFTER_CAP:
                self._sleep(delay)
                response = self._open(url)
        return response

    def _open(self, url: str, stream: bool = False):
        """The response at the end of `url`'s redirects, every hop checked
        and taken in its host's turn."""
        for _ in range(MAX_REDIRECTS + 1):
            self._check(url)
            self._wait_turn(urlsplit(url).hostname or "")
            request = self._client.build_request("GET", url)
            response = self._client.send(request, stream=stream, follow_redirects=False)
            location = response.headers.get("location")
            if not (response.is_redirect and location):
                return response
            response.close()
            url = urljoin(str(response.url), location)
        raise Unavailable("too many redirects")

    def _check(self, url: str) -> None:
        try:
            parts = urlsplit(url)
            host, port = parts.hostname, parts.port
        except ValueError:  # a port past 65535, a broken IPv6 literal
            raise _NotPublic(url) from None
        if parts.scheme not in ("http", "https") or not host:
            raise _NotPublic(url)
        if not public_host(host, port or 443, self._resolve):
            raise _NotPublic(url)

    def _wait_turn(self, host: str) -> None:
        interval = INTERVALS.get(host, 0.0)
        if not interval:
            return
        with _TURNS_LOCK:
            turns = _TURNS.setdefault(self._clock, {})
            now = self._clock()
            turn = max(now, turns.get(host, now))
            turns[host] = turn + interval
        if turn > now:
            self._sleep(turn - now)

    def download(self, url: str, dest: Path, expect: bytes = b"%PDF") -> bool:
        """Save `url` at `dest` if it is what `expect` says it starts with.

        False when the host answered and the answer is not the file -- a
        refusal, a login page, nothing there -- which it will be again next
        time. Unavailable when it did not answer, which may change.
        """
        import httpx

        deadline = self._clock() + DOWNLOAD_DEADLINE
        try:
            response = self._open(url, stream=True)
        except _NotPublic:
            return False
        except httpx.TimeoutException:
            raise Unavailable("timed out") from None
        except httpx.HTTPError as exc:
            raise Unavailable(type(exc).__name__) from None
        try:
            if response.status_code != 200:
                if response.status_code == 429 or response.status_code >= 500:
                    raise Unavailable(f"HTTP {response.status_code}")
                return False
            body = bytearray()
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > MAX_DOWNLOAD_BYTES:
                    return False
                if len(body) >= len(expect) and not body.startswith(expect):
                    # A login wall or an HTML error page. Better no file than
                    # one that fails to index later, mysteriously.
                    return False
                if self._clock() > deadline:
                    raise Unavailable("too slow")
        except httpx.TimeoutException:
            raise Unavailable("timed out") from None
        except httpx.HTTPError as exc:
            raise Unavailable(type(exc).__name__) from None
        finally:
            response.close()
        if not body.startswith(expect):
            return False
        write_file(dest, body)
        return True

    def close(self) -> None:
        self._client.close()


#: IPv6 forms that carry an IPv4 address: NAT64 and the deprecated
#: IPv4-compatible block. Python calls 64:ff9b::7f00:1 global; it is 127.0.0.1.
_EMBEDS_IPV4 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("::/96"))


def _is_public(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if address.version == 6:
        if address.ipv4_mapped:
            return address.ipv4_mapped.is_global
        if any(address in block for block in _EMBEDS_IPV4):
            return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF).is_global
    return address.is_global


def public_host(host: str, port: int, resolve: Callable[..., list]) -> bool:
    """Whether `host` resolves, and only to public addresses."""
    return bool(public_addresses(host, port, resolve))


def public_addresses(host: str, port: int, resolve: Callable[..., list]) -> list[str]:
    """`host`'s addresses if every one is public, else none. Unavailable if
    it does not resolve at all."""
    try:
        found = resolve(host, port)
    except OSError:
        raise Unavailable(f"could not resolve {host}") from None
    addresses = [info[4][0].split("%")[0] for info in found]
    try:
        if addresses and all(_is_public(ipaddress.ip_address(a)) for a in addresses):
            return addresses
    except ValueError:
        pass
    return []


def _retry_after(value: str | None, now: float) -> float | None:
    """Seconds a Retry-After header asks for: a number, or an HTTP date."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        return max(0.0, parsedate_to_datetime(value).timestamp() - now)
    except (TypeError, ValueError):
        return None


class FakeFetcher:
    """Test double. Records every URL asked for."""

    def __init__(
        self,
        json_by_url: dict[str, dict] | None = None,
        text_by_url: dict[str, str] | None = None,
        bytes_by_url: dict[str, bytes] | None = None,
        errors: set[str] | None = None,
    ) -> None:
        self._json = json_by_url or {}
        self._text = text_by_url or {}
        self._bytes = bytes_by_url or {}
        self._errors = errors or set()
        self.calls: list[str] = []

    def json(self, url: str) -> dict | None:
        self.calls.append(url)
        if url in self._errors:
            raise Unavailable(f"simulated failure for {url}")
        return self._json.get(url)

    def text(self, url: str) -> str | None:
        self.calls.append(url)
        if url in self._errors:
            raise Unavailable(f"simulated failure for {url}")
        return self._text.get(url)

    def download(self, url: str, dest: Path, expect: bytes = b"%PDF") -> bool:
        self.calls.append(url)
        if url in self._errors:
            raise Unavailable(f"simulated failure for {url}")
        body = self._bytes.get(url)
        if body is None or not body.startswith(expect):
            return False
        write_file(dest, body)
        return True
