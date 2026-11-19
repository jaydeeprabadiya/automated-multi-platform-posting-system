from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from app.platforms import instagram
from app.platforms.instagram import InstagramPlatform


class FakeResponse:
    """
    Mock HTTP response for Instagram API tests.
    """

    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code
        self.is_error = status_code >= 400

    def json(self):
        return self._data


class FakeAsyncClient:
    """
    Mock asynchronous HTTP client.

    Returns predefined responses without making real API requests.
    """

    def __init__(self, responses, **kwargs):
        self.responses = list(responses)
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    async def request(self, **kwargs):
        self.requests.append(kwargs)

        if not self.responses:
            raise AssertionError(
                "Unexpected HTTP request: no mock response available."
            )

        response = self.responses.pop(0)

        if isinstance(response, Exception):
            raise response

        return response


@pytest.fixture
def instagram_settings(monkeypatch):
    """
    Provide mock Instagram configuration.
    """

    settings = SimpleNamespace(
        instagram_user_id="17841462564684457",
        instagram_access_token=SecretStr("test_access_token"),
        http_timeout=30.0,
    )

    monkeypatch.setattr(
        instagram,
        "get_settings",
        lambda: settings,
    )

    return settings


@pytest.fixture
def instagram_platform(instagram_settings):
    """
    Create an Instagram platform instance.
    """

    return InstagramPlatform()


@pytest.mark.anyio
async def test_instagram_publish_media_success(
    instagram_platform,
    monkeypatch,
):
    """
    Verify successful Instagram image publishing.
    """

    responses = [
        FakeResponse({
            "id": "container_123",
        }),
        FakeResponse({
            "status_code": "FINISHED",
            "status": "Media processing completed.",
        }),
        FakeResponse({
            "id": "media_123",
        }),
        FakeResponse({
            "permalink": "https://www.instagram.com/p/test123/",
        }),
    ]

    mock_client = FakeAsyncClient(responses)

    monkeypatch.setattr(
        instagram.httpx,
        "AsyncClient",
        lambda **kwargs: mock_client,
    )

    result = await instagram_platform.publish_media(
        message="Test Instagram caption",
        media_url="https://example.com/image.jpg",
    )

    assert result["posted_url"] == (
        "https://www.instagram.com/p/test123/"
    )

    assert result["public_access"] is None
    assert result["date"] is not None
    assert result["time"] is not None

    assert len(mock_client.requests) == 4

    assert mock_client.requests[0]["method"] == "POST"
    assert mock_client.requests[1]["method"] == "GET"
    assert mock_client.requests[2]["method"] == "POST"
    assert mock_client.requests[3]["method"] == "GET"


@pytest.mark.anyio
async def test_instagram_rejects_invalid_media_url(
    instagram_platform,
    monkeypatch,
):
    """
    Reject non-HTTPS media URLs.
    """

    async def unexpected_client(**kwargs):
        raise AssertionError(
            "HTTP client should not be initialized."
        )

    monkeypatch.setattr(
        instagram.httpx,
        "AsyncClient",
        unexpected_client,
    )

    with pytest.raises(
        ValueError,
        match="valid public HTTPS URL",
    ):
        await instagram_platform.publish_media(
            message="Test caption",
            media_url="http://example.com/image.jpg",
        )


@pytest.mark.anyio
async def test_instagram_rejects_media_url_with_credentials(
    instagram_platform,
):
    """
    Reject media URLs containing username or password.
    """

    with pytest.raises(
        ValueError,
        match="valid public HTTPS URL",
    ):
        await instagram_platform.publish_media(
            message="Test caption",
            media_url="https://user:password@example.com/image.jpg",
        )


@pytest.mark.anyio
async def test_instagram_container_creation_api_error(
    instagram_platform,
    monkeypatch,
):
    """
    Handle Instagram media container creation errors.
    """

    mock_client = FakeAsyncClient([
        FakeResponse(
            {
                "error": {
                    "message": "Invalid image URL.",
                    "code": 9004,
                }
            },
            status_code=400,
        ),
    ])

    monkeypatch.setattr(
        instagram.httpx,
        "AsyncClient",
        lambda **kwargs: mock_client,
    )

    with pytest.raises(
        RuntimeError,
        match="Invalid image URL",
    ):
        await instagram_platform.publish_media(
            message="Test caption",
            media_url="https://example.com/image.jpg",
        )

    assert len(mock_client.requests) == 1


@pytest.mark.anyio
async def test_instagram_missing_container_id(
    instagram_platform,
    monkeypatch,
):
    """
    Handle missing media container ID.
    """

    mock_client = FakeAsyncClient([
        FakeResponse({}),
    ])

    monkeypatch.setattr(
        instagram.httpx,
        "AsyncClient",
        lambda **kwargs: mock_client,
    )

    with pytest.raises(
        RuntimeError,
        match="media container ID",
    ):
        await instagram_platform.publish_media(
            message="Test caption",
            media_url="https://example.com/image.jpg",
        )


@pytest.mark.anyio
async def test_instagram_media_processing_error(
    instagram_platform,
    monkeypatch,
):
    """
    Handle Instagram media processing failures.
    """

    mock_client = FakeAsyncClient([
        FakeResponse({
            "id": "container_123",
        }),
        FakeResponse({
            "status_code": "ERROR",
            "status": "Image processing failed.",
        }),
    ])

    monkeypatch.setattr(
        instagram.httpx,
        "AsyncClient",
        lambda **kwargs: mock_client,
    )

    with pytest.raises(
        RuntimeError,
        match="Image processing failed",
    ):
        await instagram_platform.publish_media(
            message="Test caption",
            media_url="https://example.com/image.jpg",
        )

    assert len(mock_client.requests) == 2


@pytest.mark.anyio
async def test_instagram_processing_timeout(
    instagram_platform,
    monkeypatch,
):
    """
    Handle media processing timeout.
    """

    instagram_platform.MAX_POLL_ATTEMPTS = 2
    instagram_platform.POLL_INTERVAL_SECONDS = 0

    async def mock_sleep(seconds):
        return None

    monkeypatch.setattr(
        instagram.asyncio,
        "sleep",
        mock_sleep,
    )

    mock_client = FakeAsyncClient([
        FakeResponse({
            "id": "container_123",
        }),
        FakeResponse({
            "status_code": "IN_PROGRESS",
        }),
        FakeResponse({
            "status_code": "IN_PROGRESS",
        }),
    ])

    monkeypatch.setattr(
        instagram.httpx,
        "AsyncClient",
        lambda **kwargs: mock_client,
    )

    with pytest.raises(
        TimeoutError,
        match="did not finish",
    ):
        await instagram_platform.publish_media(
            message="Test caption",
            media_url="https://example.com/image.jpg",
        )

    assert len(mock_client.requests) == 3


@pytest.mark.anyio
async def test_instagram_missing_published_media_id(
    instagram_platform,
    monkeypatch,
):
    """
    Handle missing published media ID.
    """

    mock_client = FakeAsyncClient([
        FakeResponse({
            "id": "container_123",
        }),
        FakeResponse({
            "status_code": "FINISHED",
        }),
        FakeResponse({}),
    ])

    monkeypatch.setattr(
        instagram.httpx,
        "AsyncClient",
        lambda **kwargs: mock_client,
    )

    with pytest.raises(
        RuntimeError,
        match="published media ID",
    ):
        await instagram_platform.publish_media(
            message="Test caption",
            media_url="https://example.com/image.jpg",
        )

    assert len(mock_client.requests) == 3


@pytest.mark.anyio
async def test_instagram_publish_without_media(
    instagram_platform,
):
    """
    Instagram must reject text-only publishing.
    """

    with pytest.raises(
        ValueError,
        match="requires a media URL",
    ):
        await instagram_platform.publish(
            message="Text-only Instagram post",
        )


@pytest.mark.anyio
async def test_instagram_rejects_caption_over_2200_characters(
    instagram_platform,
):
    """
    Reject captions exceeding Instagram's 2200-character limit.
    """

    with pytest.raises(
        ValueError,
        match="2200 characters",
    ):
        await instagram_platform.publish_media(
            message="A" * 2201,
            media_url="https://example.com/image.jpg",
        )


def test_instagram_requires_configuration(monkeypatch):
    """
    Instagram initialization must fail without credentials.
    """

    settings = SimpleNamespace(
        instagram_user_id=None,
        instagram_access_token=None,
        http_timeout=30.0,
    )

    monkeypatch.setattr(
        instagram,
        "get_settings",
        lambda: settings,
    )

    with pytest.raises(
        ValueError,
        match="not configured",
    ):
        InstagramPlatform()