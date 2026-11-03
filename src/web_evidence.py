"""Retrieve one explicitly selected public HTTPS page as bounded reference text.

Inputs: Public HTTPS URL without credentials, query or fragment. Outputs: Text
and source scope; never executes scripts, follows redirects, or sends cookies.
Assumptions: System TLS trust and DNS. Addresses are checked then pinned for the
connection to prevent DNS rebinding. No new dependencies. Author: Carter Tan.
"""
import http.client
import ipaddress
import socket
import ssl
import time
import threading
from html.parser import HTMLParser
from urllib.parse import urlsplit

from src.attachments import citation_target_allowed

MAX_BYTES = 262144
TIMEOUT = 15


class PageText(HTMLParser):
    """Extract readable static text, excluding script, style and template content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.excluded: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {'script', 'style', 'template', 'noscript'}:
            self.excluded.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.excluded and tag == self.excluded[-1]:
            self.excluded.pop()

    def handle_data(self, data: str) -> None:
        if not self.excluded and data.strip():
            self.parts.append(' '.join(data.split()))


class PublicHTTPS(http.client.HTTPSConnection):
    """Connect to the checked numeric address while verifying the original host."""

    def __init__(self, hostname: str, address: str) -> None:
        super().__init__(hostname, timeout=TIMEOUT, context=ssl.create_default_context())
        self.address = address

    def connect(self) -> None:
        raw = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def fetch_public_page(url: str) -> dict:
    """Fetch one bounded static page; all failures have fixed, safe messages."""
    connection = None
    response = None
    deadline_timer = None
    try:
        parsed = urlsplit(url)
        if (not citation_target_allowed(url) or parsed.query or parsed.fragment
                or len(url) > 2048 or not url.isascii() or any(ord(c) < 33 for c in url)):
            raise ValueError('Use a public HTTPS URL without credentials, query, fragment or custom port.')
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses:
            raise ValueError('The source host has no public address.')
        for entry in addresses:
            address = ipaddress.ip_address(entry[4][0])
            if not address.is_global or address.is_multicast:
                raise ValueError('Only public internet source addresses are allowed.')
        connection = PublicHTTPS(parsed.hostname, addresses[0][4][0])
        deadline = time.monotonic() + TIMEOUT
        connection.request('GET', parsed.path or '/', headers={
            'Accept': 'text/html, text/plain', 'Accept-Encoding': 'identity',
            'User-Agent': 'MyButlerEvidence/1.0', 'Connection': 'close'})
        network_socket = connection.sock
        def abort_response() -> None:
            """Interrupt trickling headers/body at the response deadline."""
            try:
                if network_socket:
                    network_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # The request may have completed as the timer fired.
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('The source request exceeded its time limit.')
        deadline_timer = threading.Timer(remaining, abort_response)
        deadline_timer.daemon = True
        deadline_timer.start()
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError('The page did not return HTTP 200. Redirects and sign-in pages are not followed.')
        if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
            raise ValueError('Compressed page responses are not supported.')
        content_type = response.getheader('Content-Type', '').split(';', 1)[0].strip().lower()
        if content_type not in {'text/html', 'text/plain'}:
            raise ValueError('Only static HTML and plain-text pages are supported.')
        chunks, size = [], 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError('The source request exceeded its time limit.')
            if connection.sock:
                connection.sock.settimeout(remaining)
            chunk = response.read1(min(8192, MAX_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError('The page exceeds the 256 KiB retrieval limit.')
        charset = response.headers.get_content_charset() or 'utf-8'
        document = b''.join(chunks).decode(charset, errors='strict')
        if content_type == 'text/html':
            parser = PageText()
            parser.feed(document)
            document = '\n'.join(parser.parts)
        if not document.strip():
            raise ValueError('The page contains no usable static text.')
        return {'text': document, 'source_url': url, 'retrieved_bytes': size,
                'scope': 'static page text only; scripts, linked pages and images not retrieved'}
    except (OSError, http.client.HTTPException, UnicodeError, LookupError):
        raise ValueError('The public source could not be retrieved securely or decoded.') from None
    finally:
        if deadline_timer:
            deadline_timer.cancel()
        if response:
            response.close()
        if connection:
            connection.close()
