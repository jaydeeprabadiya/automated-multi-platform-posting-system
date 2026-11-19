import socket

from datetime import date, time
from types import SimpleNamespace

import aiohttp
import httpx
import pytest

from pydantic import SecretStr

from app.platforms import mastodon
from app.platforms.mastodon import (
    MastodonPlatform,
    PublicDNSResolver,
)


# ============================================================
# HTTP MOCKS
# ============================================================

class FakeResponse:
    def __init__(self, data, status_code=200, headers=None):
        self._data = data
        self.status_code = status_code
        self.is_error = status_code >= 400
        self.is_redirect = 300 <= status_code < 400
        self.headers = headers or {}

    def json(self):
        return self._data


class FakeAsyncClient:
    def __init__(self, responses=None, **kwargs):
        self.responses = list(responses or [])
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    async def request(self, **kwargs):
        self.requests.append(kwargs)

        if not self.responses:
            raise AssertionError("Unexpected HTTP request.")

        response = self.responses.pop(0)

        if isinstance(response, Exception):
            raise response

        return response

    async def get(self, *args, **kwargs):
        self.requests.append({
            "method": "GET",
            "url": args[0],
            **kwargs,
        })

        if not self.responses:
            raise AssertionError("Unexpected GET request.")

        response = self.responses.pop(0)

        if isinstance(response, Exception):
            raise response

        return response


# ============================================================
# AIOHTTP MOCKS
# ============================================================

class FakeAiohttpContent:
    def __init__(self, content):
        self.content = content

    async def iter_chunked(self, chunk_size):
        for index in range(0, len(self.content), chunk_size):
            yield self.content[index:index + chunk_size]


class FakeAiohttpResponse:
    def __init__(
        self,
        content=b"\xff\xd8\xfffake-image-data",
        status=200,
        content_type="image/jpeg",
        headers=None,
    ):
        self.status = status
        self.headers = headers or {
            "content-type": content_type,
            "content-length": str(len(content)),
        }

        self.content = FakeAiohttpContent(content)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


class FakeAiohttpSession:
    def __init__(self, response):
        self.response = response
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    def get(self, url, **kwargs):
        self.requests.append({
            "url": url,
            **kwargs,
        })

        return self.response


def mock_aiohttp_download(monkeypatch, response):
    session = FakeAiohttpSession(response)

    monkeypatch.setattr(
        mastodon.aiohttp,
        "TCPConnector",
        lambda **kwargs: object(),
    )

    monkeypatch.setattr(
        mastodon.aiohttp,
        "ClientSession",
        lambda **kwargs: session,
    )

    return session


# ============================================================
# DNS RESOLVER MOCK
# ============================================================

class FakeDNSLoop:
    def __init__(self, records=None, error=None):
        self.records = records or []
        self.error = error

    async def getaddrinfo(self, *args, **kwargs):
        if self.error:
            raise self.error

        return self.records


def dns_record(ip_address):
    parsed_ip = socket.getaddrinfo(
        ip_address,
        443,
        type=socket.SOCK_STREAM,
    )[0]

    return (
        parsed_ip[0],
        parsed_ip[1],
        parsed_ip[2],
        "",
        parsed_ip[4],
    )


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def mastodon_settings(monkeypatch):
    settings = SimpleNamespace(
        mastodon_base_url="https://mastodon.social",
        mastodon_client_id="test_client_id",
        mastodon_client_secret=SecretStr("test_client_secret"),
        mastodon_access_token=SecretStr("test_access_token"),
        http_timeout=30.0,
    )

    monkeypatch.setattr(
        mastodon,
        "get_settings",
        lambda: settings,
    )

    return settings


@pytest.fixture
def mastodon_platform(mastodon_settings):
    return MastodonPlatform()


# ============================================================
# BASIC PLATFORM TESTS
# ============================================================

def test_platform_name(mastodon_platform):
    assert mastodon_platform.platform_name == "Mastodon"


def test_missing_access_token(monkeypatch):
    settings = SimpleNamespace(
        mastodon_base_url="https://mastodon.social",
        mastodon_access_token=None,
        http_timeout=30.0,
    )

    monkeypatch.setattr(
        mastodon,
        "get_settings",
        lambda: settings,
    )

    with pytest.raises(
        ValueError,
        match="Access Token is not configured",
    ):
        MastodonPlatform()


def test_invalid_base_url(monkeypatch):
    settings = SimpleNamespace(
        mastodon_base_url="http://mastodon.social",
        mastodon_access_token=SecretStr("test_token"),
        http_timeout=30.0,
    )

    monkeypatch.setattr(
        mastodon,
        "get_settings",
        lambda: settings,
    )

    with pytest.raises(ValueError, match="HTTPS URL"):
        MastodonPlatform()


def test_authentication_header(mastodon_platform):
    assert mastodon_platform._get_headers() == {
        "Authorization": "Bearer test_access_token",
    }


# ============================================================
# MESSAGE VALIDATION
# ============================================================

def test_empty_message_rejected(mastodon_platform):
    with pytest.raises(ValueError, match="cannot be empty"):
        mastodon_platform._validate_message("")


def test_whitespace_message_rejected(mastodon_platform):
    with pytest.raises(ValueError, match="cannot be empty"):
        mastodon_platform._validate_message("   ")


def test_500_character_message_accepted(mastodon_platform):
    mastodon_platform._validate_message("A" * 500)


def test_501_character_message_rejected(mastodon_platform):
    with pytest.raises(ValueError, match="500 characters"):
        mastodon_platform._validate_message("A" * 501)


# ============================================================
# MEDIA URL VALIDATION
# ============================================================

def test_valid_public_https_url_accepted(mastodon_platform):
    mastodon_platform._validate_media_url(
        "https://example.com/image.jpg"
    )


def test_invalid_media_url_rejected(mastodon_platform):
    with pytest.raises(ValueError, match="HTTPS URL"):
        mastodon_platform._validate_media_url(
            "http://example.com/image.jpg"
        )


def test_media_url_with_credentials_rejected(mastodon_platform):
    with pytest.raises(ValueError, match="HTTPS URL"):
        mastodon_platform._validate_media_url(
            "https://user:password@example.com/image.jpg"
        )


def test_media_url_with_nonstandard_port_rejected(
    mastodon_platform,
):
    with pytest.raises(ValueError, match="standard HTTPS port"):
        mastodon_platform._validate_media_url(
            "https://example.com:8443/image.jpg"
        )


def test_private_ip_url_rejected(mastodon_platform):
    with pytest.raises(ValueError, match="private or reserved"):
        mastodon_platform._validate_media_url(
            "https://127.0.0.1/image.jpg"
        )


def test_loopback_ipv6_url_rejected(mastodon_platform):
    with pytest.raises(ValueError, match="private or reserved"):
        mastodon_platform._validate_media_url(
            "https://[::1]/image.jpg"
        )


def test_private_network_url_rejected(mastodon_platform):
    with pytest.raises(ValueError, match="private or reserved"):
        mastodon_platform._validate_media_url(
            "https://192.168.1.10/image.jpg"
        )


def test_invalid_port_rejected(mastodon_platform):
    with pytest.raises(ValueError, match="valid public HTTPS URL"):
        mastodon_platform._validate_media_url(
            "https://example.com:invalid/image.jpg"
        )


def test_media_url_with_fragment_rejected(mastodon_platform):
    with pytest.raises(ValueError, match="valid public HTTPS URL"):
        mastodon_platform._validate_media_url(
            "https://example.com/image.jpg#fragment"
        )


# ============================================================
# DNS SECURITY TESTS
# ============================================================

@pytest.mark.anyio
async def test_public_dns_address_accepted(monkeypatch):
    loop = FakeDNSLoop(
        records=[
            dns_record("8.8.8.8"),
        ]
    )

    monkeypatch.setattr(
        mastodon.asyncio,
        "get_running_loop",
        lambda: loop,
    )

    resolver = PublicDNSResolver()

    results = await resolver.resolve(
        "example.com",
        443,
    )

    assert len(results) == 1
    assert results[0]["host"] == "8.8.8.8"


@pytest.mark.anyio
async def test_private_dns_address_rejected(monkeypatch):
    loop = FakeDNSLoop(
        records=[
            dns_record("192.168.1.10"),
        ]
    )

    monkeypatch.setattr(
        mastodon.asyncio,
        "get_running_loop",
        lambda: loop,
    )

    resolver = PublicDNSResolver()

    with pytest.raises(ValueError, match="non-public IP"):
        await resolver.resolve("example.com", 443)


@pytest.mark.anyio
async def test_loopback_dns_address_rejected(monkeypatch):
    loop = FakeDNSLoop(
        records=[
            dns_record("127.0.0.1"),
        ]
    )

    monkeypatch.setattr(
        mastodon.asyncio,
        "get_running_loop",
        lambda: loop,
    )

    resolver = PublicDNSResolver()

    with pytest.raises(ValueError, match="non-public IP"):
        await resolver.resolve("example.com", 443)


@pytest.mark.anyio
async def test_mixed_public_and_private_dns_rejected(monkeypatch):
    loop = FakeDNSLoop(
        records=[
            dns_record("8.8.8.8"),
            dns_record("10.0.0.1"),
        ]
    )

    monkeypatch.setattr(
        mastodon.asyncio,
        "get_running_loop",
        lambda: loop,
    )

    resolver = PublicDNSResolver()

    with pytest.raises(ValueError, match="non-public IP"):
        await resolver.resolve("example.com", 443)


@pytest.mark.anyio
async def test_dns_resolution_failure(monkeypatch):
    loop = FakeDNSLoop(
        error=socket.gaierror("DNS failure"),
    )

    monkeypatch.setattr(
        mastodon.asyncio,
        "get_running_loop",
        lambda: loop,
    )

    resolver = PublicDNSResolver()

    with pytest.raises(RuntimeError, match="Unable to resolve"):
        await resolver.resolve("example.com", 443)


@pytest.mark.anyio
async def test_dns_empty_result_rejected(monkeypatch):
    loop = FakeDNSLoop(records=[])

    monkeypatch.setattr(
        mastodon.asyncio,
        "get_running_loop",
        lambda: loop,
    )

    resolver = PublicDNSResolver()

    with pytest.raises(RuntimeError, match="did not resolve"):
        await resolver.resolve("example.com", 443)


@pytest.mark.anyio
async def test_dns_duplicate_addresses_removed(monkeypatch):
    loop = FakeDNSLoop(
        records=[
            dns_record("8.8.8.8"),
            dns_record("8.8.8.8"),
        ]
    )

    monkeypatch.setattr(
        mastodon.asyncio,
        "get_running_loop",
        lambda: loop,
    )

    resolver = PublicDNSResolver()

    results = await resolver.resolve(
        "example.com",
        443,
    )

    assert len(results) == 1


# ============================================================
# IMAGE SIGNATURE VALIDATION
# ============================================================

def test_valid_jpeg_signature_accepted():
    MastodonPlatform._validate_image_signature(
        b"\xff\xd8\xfffake-image",
        "image/jpeg",
    )


def test_valid_png_signature_accepted():
    MastodonPlatform._validate_image_signature(
        b"\x89PNG\r\n\x1a\nfake-image",
        "image/png",
    )


def test_valid_gif_signature_accepted():
    MastodonPlatform._validate_image_signature(
        b"GIF89afake-image",
        "image/gif",
    )


def test_valid_webp_signature_accepted():
    MastodonPlatform._validate_image_signature(
        b"RIFFxxxxWEBPfake-image",
        "image/webp",
    )


def test_invalid_image_signature_rejected():
    with pytest.raises(ValueError, match="signature"):
        MastodonPlatform._validate_image_signature(
            b"this-is-not-an-image",
            "image/jpeg",
        )


def test_image_content_type_mismatch_rejected():
    with pytest.raises(ValueError, match="signature"):
        MastodonPlatform._validate_image_signature(
            b"\x89PNG\r\n\x1a\nfake-image",
            "image/jpeg",
        )


# ============================================================
# TEXT PUBLISHING
# ============================================================

@pytest.mark.anyio
async def test_successful_text_publish(
    mastodon_platform,
    monkeypatch,
):
    mock_client = FakeAsyncClient([
        FakeResponse({
            "id": "12345",
            "url": "https://mastodon.social/@dudesanddivas/12345",
        }),
    ])

    monkeypatch.setattr(
        mastodon.httpx,
        "AsyncClient",
        lambda **kwargs: mock_client,
    )

    result = await mastodon_platform.publish(
        "Hello from Dude's & Diva's"
    )

    assert result["posted_url"] == (
        "https://mastodon.social/@dudesanddivas/12345"
    )

    assert result["public_access"] is True
    assert isinstance(result["date"], date)
    assert isinstance(result["time"], time)

    assert len(mock_client.requests) == 1

    request = mock_client.requests[0]

    assert request["method"] == "POST"
    assert request["url"] == (
        "https://mastodon.social/api/v1/statuses"
    )

    assert request["data"]["status"] == (
        "Hello from Dude's & Diva's"
    )

    assert request["data"]["visibility"] == "public"
    assert "Idempotency-Key" in request["headers"]


@pytest.mark.anyio
async def test_text_publish_api_error(
    mastodon_platform,
    monkeypatch,
):
    mock_client = FakeAsyncClient([
        FakeResponse(
            {"error": "Unauthorized"},
            status_code=401,
        ),
    ])

    monkeypatch.setattr(
        mastodon.httpx,
        "AsyncClient",
        lambda **kwargs: mock_client,
    )

    with pytest.raises(RuntimeError, match="Unauthorized"):
        await mastodon_platform.publish("Test post")


@pytest.mark.anyio
async def test_text_publish_timeout(
    mastodon_platform,
    monkeypatch,
):
    mock_client = FakeAsyncClient([
        httpx.TimeoutException("Request timed out"),
    ])

    monkeypatch.setattr(
        mastodon.httpx,
        "AsyncClient",
        lambda **kwargs: mock_client,
    )

    with pytest.raises(RuntimeError, match="timed out"):
        await mastodon_platform.publish("Test post")


@pytest.mark.anyio
async def test_missing_post_url(
    mastodon_platform,
    monkeypatch,
):
    mock_client = FakeAsyncClient([
        FakeResponse({
            "id": "12345",
        }),
    ])

    monkeypatch.setattr(
        mastodon.httpx,
        "AsyncClient",
        lambda **kwargs: mock_client,
    )

    with pytest.raises(RuntimeError, match="public URL"):
        await mastodon_platform.publish("Test post")


# ============================================================
# IMAGE DOWNLOAD TESTS
# ============================================================

@pytest.mark.anyio
async def test_successful_image_download(
    mastodon_platform,
    monkeypatch,
):
    image_data = b"\xff\xd8\xfffake-image-data"

    response = FakeAiohttpResponse(
        content=image_data,
        content_type="image/jpeg",
    )

    session = mock_aiohttp_download(
        monkeypatch,
        response,
    )

    result = await mastodon_platform._download_image(
        "https://example.com/image.jpg"
    )

    assert result[0] == image_data
    assert result[1] == "image/jpeg"
    assert result[2] == "image.jpg"

    assert session.requests[0]["allow_redirects"] is False


@pytest.mark.anyio
async def test_image_redirect_rejected(
    mastodon_platform,
    monkeypatch,
):
    response = FakeAiohttpResponse(
        content=b"",
        status=302,
    )

    mock_aiohttp_download(monkeypatch, response)

    with pytest.raises(RuntimeError, match="redirects"):
        await mastodon_platform._download_image(
            "https://example.com/image.jpg"
        )


@pytest.mark.anyio
async def test_unsupported_image_type(
    mastodon_platform,
    monkeypatch,
):
    response = FakeAiohttpResponse(
        content=b"%PDF-fake",
        content_type="application/pdf",
    )

    mock_aiohttp_download(monkeypatch, response)

    with pytest.raises(
        ValueError,
        match="Unsupported image content type",
    ):
        await mastodon_platform._download_image(
            "https://example.com/file.pdf"
        )


@pytest.mark.anyio
async def test_image_size_limit(
    mastodon_platform,
    monkeypatch,
):
    response = FakeAiohttpResponse(
        content=b"\xff\xd8\xff" + (
            b"A" * (mastodon_platform.MAX_MEDIA_SIZE + 1)
        ),
        content_type="image/jpeg",
    )

    mock_aiohttp_download(monkeypatch, response)

    with pytest.raises(
        ValueError,
        match="maximum allowed size",
    ):
        await mastodon_platform._download_image(
            "https://example.com/large.jpg"
        )


@pytest.mark.anyio
async def test_invalid_image_signature_rejected(
    mastodon_platform,
    monkeypatch,
):
    response = FakeAiohttpResponse(
        content=b"not-a-real-jpeg",
        content_type="image/jpeg",
    )

    mock_aiohttp_download(monkeypatch, response)

    with pytest.raises(ValueError, match="signature"):
        await mastodon_platform._download_image(
            "https://example.com/fake.jpg"
        )


@pytest.mark.anyio
async def test_invalid_content_length_rejected(
    mastodon_platform,
    monkeypatch,
):
    response = FakeAiohttpResponse(
        content=b"\xff\xd8\xfffake",
        headers={
            "content-type": "image/jpeg",
            "content-length": "invalid",
        },
    )

    mock_aiohttp_download(monkeypatch, response)

    with pytest.raises(RuntimeError, match="content length"):
        await mastodon_platform._download_image(
            "https://example.com/image.jpg"
        )


@pytest.mark.anyio
async def test_empty_image_rejected(
    mastodon_platform,
    monkeypatch,
):
    response = FakeAiohttpResponse(
        content=b"",
        content_type="image/jpeg",
    )

    mock_aiohttp_download(monkeypatch, response)

    with pytest.raises(ValueError, match="empty"):
        await mastodon_platform._download_image(
            "https://example.com/empty.jpg"
        )


@pytest.mark.anyio
async def test_download_private_ip_rejected_before_network(
    mastodon_platform,
    monkeypatch,
):
    def unexpected_session(**kwargs):
        raise AssertionError(
            "Network session must not be initialized."
        )

    monkeypatch.setattr(
        mastodon.aiohttp,
        "ClientSession",
        unexpected_session,
    )

    with pytest.raises(ValueError, match="private or reserved"):
        await mastodon_platform._download_image(
            "https://127.0.0.1/image.jpg"
        )


# ============================================================
# COMPLETE IMAGE PUBLISHING
# ============================================================

@pytest.mark.anyio
async def test_successful_image_publish(
    mastodon_platform,
    monkeypatch,
):
    image_response = FakeAiohttpResponse(
        content=b"\xff\xd8\xfffake-image-data",
        content_type="image/jpeg",
    )

    mock_aiohttp_download(
        monkeypatch,
        image_response,
    )

    mock_client = FakeAsyncClient(
        responses=[
            FakeResponse({
                "id": "media_123",
            }),
            FakeResponse({
                "url": "https://mastodon.social/media/image.jpg",
            }),
            FakeResponse({
                "id": "status_123",
                "url": "https://mastodon.social/@dudesanddivas/123",
            }),
        ],
    )

    monkeypatch.setattr(
        mastodon.httpx,
        "AsyncClient",
        lambda **kwargs: mock_client,
    )

    result = await mastodon_platform.publish_media(
        message="Dude's & Diva's image post",
        media_url="https://example.com/image.jpg",
    )

    assert result["posted_url"] == (
        "https://mastodon.social/@dudesanddivas/123"
    )

    assert result["public_access"] is True
    assert len(mock_client.requests) == 3

    upload_request = mock_client.requests[0]

    assert upload_request["method"] == "POST"
    assert upload_request["url"] == (
        "https://mastodon.social/api/v2/media"
    )

    assert "file" in upload_request["files"]

    status_request = mock_client.requests[2]

    assert status_request["method"] == "POST"
    assert status_request["data"]["visibility"] == "public"
    assert status_request["data"]["media_ids[]"] == "media_123"


@pytest.mark.anyio
async def test_missing_media_id(
    mastodon_platform,
    monkeypatch,
):
    image_response = FakeAiohttpResponse()

    mock_aiohttp_download(
        monkeypatch,
        image_response,
    )

    mock_client = FakeAsyncClient([
        FakeResponse({}),
    ])

    monkeypatch.setattr(
        mastodon.httpx,
        "AsyncClient",
        lambda **kwargs: mock_client,
    )

    with pytest.raises(RuntimeError, match="media attachment ID"):
        await mastodon_platform.publish_media(
            "Image post",
            "https://example.com/image.jpg",
        )


# ============================================================
# MEDIA PROCESSING
# ============================================================

@pytest.mark.anyio
async def test_media_processing_timeout(
    mastodon_platform,
    monkeypatch,
):
    mastodon_platform.MAX_POLL_ATTEMPTS = 2
    mastodon_platform.POLL_INTERVAL_SECONDS = 0

    async def mock_sleep(seconds):
        return None

    monkeypatch.setattr(
        mastodon.asyncio,
        "sleep",
        mock_sleep,
    )

    mock_client = FakeAsyncClient([
        FakeResponse({}, status_code=206),
        FakeResponse({}, status_code=206),
    ])

    with pytest.raises(TimeoutError, match="did not finish"):
        await mastodon_platform._wait_for_media(
            mock_client,
            "media_123",
        )

    assert len(mock_client.requests) == 2


# ============================================================
# INVALID INPUT MUST NOT CALL EXTERNAL SERVICES
# ============================================================

@pytest.mark.anyio
async def test_invalid_message_does_not_call_api(
    mastodon_platform,
    monkeypatch,
):
    def unexpected_client(**kwargs):
        raise AssertionError(
            "HTTP client must not be initialized."
        )

    monkeypatch.setattr(
        mastodon.httpx,
        "AsyncClient",
        unexpected_client,
    )

    with pytest.raises(ValueError, match="500 characters"):
        await mastodon_platform.publish("A" * 501)


@pytest.mark.anyio
async def test_invalid_media_url_does_not_call_api(
    mastodon_platform,
    monkeypatch,
):
    def unexpected_client(**kwargs):
        raise AssertionError(
            "HTTP client must not be initialized."
        )

    monkeypatch.setattr(
        mastodon.httpx,
        "AsyncClient",
        unexpected_client,
    )

    with pytest.raises(ValueError, match="HTTPS URL"):
        await mastodon_platform.publish_media(
            "Test image",
            "http://example.com/image.jpg",
        )