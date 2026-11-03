"""Public-source retrieval boundaries with synthetic DNS, TLS and HTTP fixtures.

Inputs: Fake public/private addresses and bounded responses. Outputs: Assertions.
No external traffic or credentials. Author: Carter Tan.
"""
from email.message import Message
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from src.app import create_app, source_register
from src.web_evidence import MAX_BYTES, PublicHTTPS, fetch_public_page


def response_fixture(content: bytes = b'<h1>Public source</h1><script>ignore this</script><p>Wallet consent.</p>', status: int = 200, content_type: str = 'text/html') -> Mock:
    """Build bounded streaming response without sockets."""
    response = Mock(status=status)
    response.headers = Message()
    response.headers['Content-Type'] = content_type
    response.getheader.side_effect = lambda key, default=None: response.headers.get(key, default)
    parts = [content[i:i + 8192] for i in range(0, len(content), 8192)] + [b'']
    response.read1.side_effect = parts
    return response


@pytest.mark.parametrize('url', ['http://example.org', 'https://user:secret@example.org', 'https://example.org:8443/',
    'https://example.org/?secret=hidden', 'https://example.org/#fragment', 'https://127.0.0.1/', 'https://example.org/\n'])
def test_web_rejects_unsafe_url_before_dns(url: str) -> None:
    """Unsupported forms never reach DNS or the wire."""
    with patch('src.web_evidence.socket.getaddrinfo') as dns:
        with pytest.raises(ValueError):
            fetch_public_page(url)
        dns.assert_not_called()


@pytest.mark.parametrize('address', ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', 'fc00::1', '224.0.0.1'])
def test_web_rejects_nonpublic_dns(address: str) -> None:
    """Hostnames resolving to private/metadata/multicast destinations are blocked."""
    with patch('src.web_evidence.socket.getaddrinfo', return_value=[(2, 1, 6, '', (address, 443))]), patch('src.web_evidence.PublicHTTPS') as connection:
        with pytest.raises(ValueError, match='public'):
            fetch_public_page('https://example.org/page')
        connection.assert_not_called()


@pytest.mark.parametrize('variant', ['valid', 'redirect', 'binary', 'compressed', 'oversize', 'bad_encoding'])
def test_web_response_limits_and_no_redirects(variant: str) -> None:
    """Responses are bounded and readable; failed requests never become evidence."""
    response = response_fixture()
    if variant == 'redirect':
        response.status = 302
    elif variant == 'binary':
        response.headers.replace_header('Content-Type', 'application/pdf')
    elif variant == 'compressed':
        response.headers['Content-Encoding'] = 'gzip'
    elif variant == 'oversize':
        response = response_fixture(b'x' * (MAX_BYTES + 1), content_type='text/plain')
    elif variant == 'bad_encoding':
        response = response_fixture(b'\xff', content_type='text/plain')
    with patch('src.web_evidence.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443))]), patch('src.web_evidence.PublicHTTPS') as connection:
        connection.return_value.getresponse.return_value = response
        if variant == 'valid':
            result = fetch_public_page('https://example.org/page')
            assert result['text'] == 'Public source\nWallet consent.'
            connection.assert_called_once_with('example.org', '93.184.216.34')
            args = connection.return_value.request.call_args
            assert args.args == ('GET', '/page')
            assert 'Cookie' not in args.kwargs['headers'] and 'Authorization' not in args.kwargs['headers']
        else:
            with pytest.raises(ValueError):
                fetch_public_page('https://example.org/page')
        connection.return_value.close.assert_called_once()


def test_public_connection_pins_address_and_verifies_hostname() -> None:
    """TLS validates the original authority while TCP uses only the checked IP."""
    with patch('src.web_evidence.ssl.create_default_context') as context, patch('src.web_evidence.socket.create_connection') as connect:
        connection = PublicHTTPS('example.org', '93.184.216.34')
        connection.connect()
        connect.assert_called_once_with(('93.184.216.34', 443), timeout=15)
        context.return_value.wrap_socket.assert_called_once_with(connect.return_value, server_hostname='example.org')


@pytest.mark.parametrize('length', [100, 6001])
def test_public_evidence_records_retrieval_and_truncation(tmp_path, length: int) -> None:
    """Only explicit successful retrieval persists evidence; it remains local-only."""
    app = create_app(tmp_path / 'web.sqlite3')
    page = {'text': 'x' * length, 'source_url': 'https://example.org/page', 'retrieved_bytes': length, 'scope': 'static text'}
    with TestClient(app) as client, patch('src.web_evidence.fetch_public_page', return_value=page) as fetch:
        client.headers['x-bulter-token'] = app.state.csrf
        result = client.post('/api/connectors/web/read', json={'url': page['source_url']})
        assert result.status_code == 200
        evidence = result.json()
        assert evidence['local_only'] and evidence['truncated'] == (length > 6000)
        assert len(evidence['content']) == min(length, 6000)
        assert evidence['provenance'] == 'public_https_fetch; static_text_only'
        assert source_register([], [evidence])[0]['retrieved_at'] == evidence['retrieved_at']
        fetch.assert_called_once_with(page['source_url'])
        fetch.side_effect = ValueError('The public source could not be retrieved securely or decoded.')
        assert client.post('/api/connectors/web/read', json={'url': page['source_url']}).status_code == 400
        assert len(app.state.store.all('connector_evidence')) == 1


def test_web_expired_request_stops_before_reading_response() -> None:
    """A slow connect/request cannot leave a fresh response deadline."""
    with patch('src.web_evidence.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443))]), patch('src.web_evidence.PublicHTTPS') as connection, patch('src.web_evidence.time.monotonic', side_effect=[0, 16]):
        with pytest.raises(ValueError, match='time limit'):
            fetch_public_page('https://example.org/')
        connection.return_value.getresponse.assert_not_called()
        connection.return_value.close.assert_called_once()


def test_web_rejects_mixed_public_private_resolution() -> None:
    """A public first answer does not excuse a private alternative address."""
    answers = [(2, 1, 6, '', (ip, 443)) for ip in ['93.184.216.34', '10.0.0.1']]
    with patch('src.web_evidence.socket.getaddrinfo', return_value=answers), patch('src.web_evidence.PublicHTTPS') as connection:
        with pytest.raises(ValueError, match='public'):
            fetch_public_page('https://example.org/')
        connection.assert_not_called()


def test_source_labels_distinguish_retrieved_from_pasted_evidence() -> None:
    """The browser must not label fetched evidence as an unfetched pasted excerpt."""
    import json
    import re
    import subprocess
    from pathlib import Path
    source = Path('src/static/connectors.js').read_text()
    function = re.search(r'function sourceEvidenceLabel\(item\) \{.*?\n\}', source, re.S).group(0)
    inputs = [{'provenance': 'public_https_fetch; static_text_only', 'retrieved_at': '2026-11-03'},
              {'provenance': 'user_provided; page_not_fetched'}, {}]
    result = subprocess.run(['node', '-e', function + '\nconsole.log(JSON.stringify(' + json.dumps(inputs) + '.map(sourceEvidenceLabel)))'], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == ['retrieved 2026-11-03; static text only',
        'user-provided; page not fetched', 'user-provided; page not fetched']
