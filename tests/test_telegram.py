import pytest
import httpx

from unittest.mock import AsyncMock, MagicMock

from app.platforms.telegram import TelegramPlatform


@pytest.fixture
def telegram():
    return TelegramPlatform()


def test_platform_name(telegram):
    assert telegram.platform_name == "Telegram"


def test_validate_message_success():
    TelegramPlatform._validate_message("Hello Telegram!")


def test_validate_empty_message():
    with pytest.raises(ValueError):
        TelegramPlatform._validate_message("")


def test_validate_whitespace_message():
    with pytest.raises(ValueError):
        TelegramPlatform._validate_message("   ")


def test_validate_message_too_long():
    message = "a" * (TelegramPlatform.MAX_MESSAGE_LENGTH + 1)

    with pytest.raises(ValueError):
        TelegramPlatform._validate_message(message)


def test_validate_caption_success():
    TelegramPlatform._validate_caption("Test caption")


def test_validate_empty_caption():
    with pytest.raises(ValueError):
        TelegramPlatform._validate_caption("")


def test_validate_caption_too_long():
    caption = "a" * (TelegramPlatform.MAX_CAPTION_LENGTH + 1)

    with pytest.raises(ValueError):
        TelegramPlatform._validate_caption(caption)


@pytest.mark.parametrize(
    "media_url",
    [
        "https://example.com/image.jpg",
        "https://cdn.example.com/images/photo.png",
    ],
)
def test_validate_media_url_success(media_url):
    TelegramPlatform._validate_media_url(media_url)


@pytest.mark.parametrize(
    "media_url",
    [
        "http://example.com/image.jpg",
        "ftp://example.com/image.jpg",
        "",
        "not-a-url",
        "https://user:password@example.com/image.jpg",
        "https://example.com/image.jpg#fragment",
        "https://127.0.0.1/image.jpg",
        "https://localhost/image.jpg",
        "https://192.168.1.10/image.jpg",
    ],
)
def test_validate_media_url_invalid(media_url):
    with pytest.raises(ValueError):
        TelegramPlatform._validate_media_url(media_url)


def test_build_post_url(telegram):
    assert (
        telegram._build_post_url(123)
        == "https://t.me/dudesdivasofficial/123"
    )


def test_build_result(telegram):
    result = telegram._build_result(123)

    assert result["posted_url"] == (
        "https://t.me/dudesdivasofficial/123"
    )
    assert result["public_access"] is True
    assert result["date"] is not None
    assert result["time"] is not None

    assert result["posted_url"] == (
        "https://t.me/dudesdivasofficial/123"
    )
    assert result["public_access"] is True
    assert result["date"] is not None
    assert result["time"] is not None


@pytest.mark.asyncio
async def test_publish_success(telegram, monkeypatch):
    expected_result = {
        "message_id": 123,
    }

    request_mock = AsyncMock(return_value=expected_result)

    monkeypatch.setattr(
        telegram,
        "_request",
        request_mock,
    )

    result = await telegram.publish(
        "Hello Telegram!"
    )

    assert result["posted_url"] == (
        "https://t.me/dudesdivasofficial/123"
    )

    assert result["public_access"] is True

    request_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_media_success(telegram, monkeypatch):
    expected_result = {
        "message_id": 456,
    }

    request_mock = AsyncMock(return_value=expected_result)

    monkeypatch.setattr(
        telegram,
        "_request",
        request_mock,
    )

    result = await telegram.publish_media(
        message="Test image caption",
        media_url="https://example.com/image.jpg",
    )

    assert result["posted_url"] == (
        "https://t.me/dudesdivasofficial/456"
    )

    assert result["public_access"] is True

    request_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_rejects_invalid_message(telegram):
    with pytest.raises(ValueError):
        await telegram.publish("")


@pytest.mark.asyncio
async def test_publish_media_rejects_invalid_caption(telegram):
    with pytest.raises(ValueError):
        await telegram.publish_media(
            message="",
            media_url="https://example.com/image.jpg",
        )


@pytest.mark.asyncio
async def test_publish_media_rejects_invalid_url(telegram):
    with pytest.raises(ValueError):
        await telegram.publish_media(
            message="Caption",
            media_url="http://example.com/image.jpg",
        )


@pytest.mark.asyncio
async def test_request_api_error(telegram):
    response = MagicMock()

    response.is_error = True
    response.json.return_value = {
        "ok": False,
        "error_code": 400,
        "description": "Bad Request",
    }

    client = MagicMock()

    client.post = AsyncMock(
        return_value=response
    )

    with pytest.raises(RuntimeError, match="Telegram API error"):
        await telegram._request(
            client=client,
            method="sendMessage",
            payload={
                "chat_id": telegram.channel_id,
                "text": "Test",
            },
            operation="testing",
        )


@pytest.mark.asyncio
async def test_request_invalid_json(telegram):
    response = MagicMock()

    response.is_error = False
    response.json.side_effect = ValueError

    client = MagicMock()

    client.post = AsyncMock(
        return_value=response
    )

    with pytest.raises(RuntimeError, match="invalid JSON"):
        await telegram._request(
            client=client,
            method="sendMessage",
            payload={
                "chat_id": telegram.channel_id,
                "text": "Test",
            },
            operation="testing",
        )


@pytest.mark.asyncio
async def test_request_invalid_result(telegram):
    response = MagicMock()

    response.is_error = False
    response.json.return_value = {
        "ok": True,
        "result": "invalid",
    }

    client = MagicMock()

    client.post = AsyncMock(
        return_value=response
    )

    with pytest.raises(RuntimeError, match="invalid result"):
        await telegram._request(
            client=client,
            method="sendMessage",
            payload={
                "chat_id": telegram.channel_id,
                "text": "Test",
            },
            operation="testing",
        )


@pytest.mark.asyncio
async def test_request_timeout(telegram):
    client = MagicMock()

    client.post = AsyncMock(
        side_effect=httpx.TimeoutException("Timeout")
    )

    with pytest.raises(RuntimeError, match="timed out"):
        await telegram._request(
            client=client,
            method="sendMessage",
            payload={
                "chat_id": telegram.channel_id,
                "text": "Test",
            },
            operation="testing",
        )


@pytest.mark.asyncio
async def test_request_network_error(telegram):
    client = MagicMock()

    client.post = AsyncMock(
        side_effect=httpx.RequestError("Network failure")
    )

    with pytest.raises(RuntimeError, match="connection failed"):
        await telegram._request(
            client=client,
            method="sendMessage",
            payload={
                "chat_id": telegram.channel_id,
                "text": "Test",
            },
            operation="testing",
        )


@pytest.mark.asyncio
async def test_publish_invalid_message_id(telegram, monkeypatch):
    request_mock = AsyncMock(
        return_value={
            "message_id": "invalid",
        }
    )

    monkeypatch.setattr(
        telegram,
        "_request",
        request_mock,
    )

    with pytest.raises(RuntimeError, match="valid message ID"):
        await telegram.publish("Test message")


@pytest.mark.asyncio
async def test_publish_media_invalid_message_id(telegram, monkeypatch):
    request_mock = AsyncMock(
        return_value={
            "message_id": "invalid",
        }
    )

    monkeypatch.setattr(
        telegram,
        "_request",
        request_mock,
    )

    with pytest.raises(RuntimeError, match="valid message ID"):
        await telegram.publish_media(
            message="Test caption",
            media_url="https://example.com/image.jpg",
        )