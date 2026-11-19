from datetime import date, time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from app.platforms.facebook import FacebookPlatform


class MockResponse:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data
        self.is_error = status_code >= 400

    def json(self):
        return self._data


class MockAsyncClient:
    def __init__(self, *args, **kwargs):
        self.post = AsyncMock()
        self.get = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


@pytest.fixture
def facebook_settings(monkeypatch):
    settings = SimpleNamespace(
        facebook_page_id="110336252973182",
        facebook_access_token=SecretStr("test_access_token"),
        http_timeout=30,
    )

    monkeypatch.setattr(
        "app.platforms.facebook.get_settings",
        lambda: settings,
    )

    return settings


def mock_client(monkeypatch, client):
    monkeypatch.setattr(
        "app.platforms.facebook.httpx.AsyncClient",
        lambda **kwargs: client,
    )


@pytest.mark.anyio
async def test_facebook_publish_success(
    facebook_settings,
    monkeypatch,
):
    client = MockAsyncClient()

    client.post.return_value = MockResponse(
        200,
        {"id": "110336252973182_123456"},
    )

    client.get.return_value = MockResponse(
        200,
        {
            "permalink_url": (
                "https://www.facebook.com/dudesndivas.amd/posts/123456"
            )
        },
    )

    mock_client(monkeypatch, client)

    platform = FacebookPlatform()

    result = await platform.publish(
        "Grow your business https://example.com"
    )

    assert result["posted_url"] == (
        "https://www.facebook.com/dudesndivas.amd/posts/123456"
    )

    assert result["public_access"] is None
    assert isinstance(result["date"], date)
    assert isinstance(result["time"], time)

    client.post.assert_awaited_once()
    client.get.assert_awaited_once()

    assert client.get.await_args.kwargs["params"] == {
        "fields": "permalink_url"
    }


@pytest.mark.anyio
async def test_facebook_publish_api_error(
    facebook_settings,
    monkeypatch,
):
    client = MockAsyncClient()

    client.post.return_value = MockResponse(
        400,
        {
            "error": {
                "message": "Invalid access token"
            }
        },
    )

    mock_client(monkeypatch, client)

    platform = FacebookPlatform()

    with pytest.raises(
        RuntimeError,
        match="Invalid access token",
    ):
        await platform.publish(
            "Grow your business https://example.com"
        )

    client.get.assert_not_awaited()


@pytest.mark.anyio
async def test_facebook_publish_missing_post_id(
    facebook_settings,
    monkeypatch,
):
    client = MockAsyncClient()

    client.post.return_value = MockResponse(
        200,
        {},
    )

    mock_client(monkeypatch, client)

    platform = FacebookPlatform()

    with pytest.raises(
        RuntimeError,
        match="did not return a post ID",
    ):
        await platform.publish(
            "Grow your business https://example.com"
        )

    client.get.assert_not_awaited()


@pytest.mark.anyio
async def test_facebook_publish_invalid_response(
    facebook_settings,
    monkeypatch,
):
    client = MockAsyncClient()

    response = MockResponse(200, {})
    response.json = lambda: (_ for _ in ()).throw(
        ValueError("Invalid JSON")
    )

    client.post.return_value = response

    mock_client(monkeypatch, client)

    platform = FacebookPlatform()

    with pytest.raises(
        RuntimeError,
        match="invalid publishing response",
    ):
        await platform.publish(
            "Grow your business https://example.com"
        )


@pytest.mark.anyio
async def test_facebook_permalink_api_error(
    facebook_settings,
    monkeypatch,
):
    client = MockAsyncClient()

    client.post.return_value = MockResponse(
        200,
        {"id": "110336252973182_123456"},
    )

    client.get.return_value = MockResponse(
        400,
        {
            "error": {
                "message": "Permission denied"
            }
        },
    )

    mock_client(monkeypatch, client)

    platform = FacebookPlatform()

    with pytest.raises(
        RuntimeError,
        match="Permission denied",
    ):
        await platform.publish(
            "Grow your business https://example.com"
        )


@pytest.mark.anyio
async def test_facebook_permalink_missing(
    facebook_settings,
    monkeypatch,
):
    client = MockAsyncClient()

    client.post.return_value = MockResponse(
        200,
        {"id": "110336252973182_123456"},
    )

    client.get.return_value = MockResponse(
        200,
        {},
    )

    mock_client(monkeypatch, client)

    platform = FacebookPlatform()

    with pytest.raises(
        RuntimeError,
        match="did not return permalink_url",
    ):
        await platform.publish(
            "Grow your business https://example.com"
        )


@pytest.mark.anyio
async def test_facebook_publish_image_success(
    facebook_settings,
    monkeypatch,
):
    client = MockAsyncClient()

    client.post.return_value = MockResponse(
        200,
        {
            "id": "photo_98765",
            "post_id": "110336252973182_98765",
        },
    )

    client.get.return_value = MockResponse(
        200,
        {
            "permalink_url": (
                "https://www.facebook.com/"
                "dudesndivas.amd/posts/98765"
            )
        },
    )

    mock_client(monkeypatch, client)

    platform = FacebookPlatform()

    result = await platform.publish_media(
        message="Testing image https://example.com",
        media_url="https://example.com/image.jpg",
    )

    assert result["posted_url"].endswith("/98765")
    assert result["public_access"] is None
    assert isinstance(result["date"], date)
    assert isinstance(result["time"], time)

    client.post.assert_awaited_once()
    client.get.assert_awaited_once()

    post_call = client.post.await_args

    assert post_call.args[0].endswith("/110336252973182/photos")

    assert post_call.kwargs["data"] == {
        "url": "https://example.com/image.jpg",
        "caption": "Testing image https://example.com",
    }

    assert client.get.await_args.kwargs["params"] == {
        "fields": "permalink_url"
    }


@pytest.mark.anyio
async def test_facebook_image_uses_photo_id_when_post_id_missing(
    facebook_settings,
    monkeypatch,
):
    client = MockAsyncClient()

    client.post.return_value = MockResponse(
        200,
        {"id": "photo_12345"},
    )

    client.get.return_value = MockResponse(
        200,
        {"permalink_url": "https://facebook.com/photo/12345"},
    )

    mock_client(monkeypatch, client)

    platform = FacebookPlatform()

    result = await platform.publish_media(
        message="Image test https://example.com",
        media_url="https://example.com/image.jpg",
    )

    assert result["posted_url"] == "https://facebook.com/photo/12345"

    assert client.get.await_args.args[0].endswith(
        "/photo_12345"
    )


@pytest.mark.anyio
async def test_facebook_image_api_error(
    facebook_settings,
    monkeypatch,
):
    client = MockAsyncClient()

    client.post.return_value = MockResponse(
        400,
        {
            "error": {
                "message": "Invalid image URL"
            }
        },
    )

    mock_client(monkeypatch, client)

    platform = FacebookPlatform()

    with pytest.raises(
        RuntimeError,
        match="Invalid image URL",
    ):
        await platform.publish_media(
            message="Image test https://example.com",
            media_url="https://example.com/image.jpg",
        )

    client.get.assert_not_awaited()


@pytest.mark.anyio
async def test_facebook_image_invalid_response(
    facebook_settings,
    monkeypatch,
):
    client = MockAsyncClient()

    response = MockResponse(200, {})
    response.json = lambda: (_ for _ in ()).throw(
        ValueError("Invalid JSON")
    )

    client.post.return_value = response

    mock_client(monkeypatch, client)

    platform = FacebookPlatform()

    with pytest.raises(
        RuntimeError,
        match="invalid image publishing response",
    ):
        await platform.publish_media(
            message="Image test https://example.com",
            media_url="https://example.com/image.jpg",
        )


@pytest.mark.anyio
async def test_facebook_image_missing_post_id(
    facebook_settings,
    monkeypatch,
):
    client = MockAsyncClient()

    client.post.return_value = MockResponse(
        200,
        {},
    )

    mock_client(monkeypatch, client)

    platform = FacebookPlatform()

    with pytest.raises(
        RuntimeError,
        match="did not return a photo or post ID",
    ):
        await platform.publish_media(
            message="Image test https://example.com",
            media_url="https://example.com/image.jpg",
        )

    client.get.assert_not_awaited()


@pytest.mark.anyio
async def test_facebook_rejects_http_media_url(
    facebook_settings,
):
    platform = FacebookPlatform()

    with pytest.raises(
        ValueError,
        match="must use HTTPS",
    ):
        platform._validate_media_url(
            "http://example.com/image.jpg"
        )


@pytest.mark.anyio
async def test_facebook_rejects_invalid_media_url(
    facebook_settings,
):
    platform = FacebookPlatform()

    invalid_urls = [
        "not-a-url",
        "https://",
        "ftp://example.com/image.jpg",
        "https://user:password@example.com/image.jpg",
    ]

    for url in invalid_urls:
        with pytest.raises(ValueError):
            platform._validate_media_url(url)


def test_facebook_rejects_missing_url(facebook_settings):
    platform = FacebookPlatform()

    with pytest.raises(
        ValueError,
        match="exactly one CTA URL",
    ):
        platform._extract_url("Grow your business")


def test_facebook_rejects_multiple_urls(facebook_settings):
    platform = FacebookPlatform()

    with pytest.raises(
        ValueError,
        match="exactly one CTA URL",
    ):
        platform._extract_url(
            "Visit https://example.com and https://google.com"
        )