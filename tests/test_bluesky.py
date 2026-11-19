from datetime import date, datetime, time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.platforms.bluesky import BlueskyPlatform


@pytest.fixture
def platform(monkeypatch):
    settings = SimpleNamespace(
        bluesky_handle="dudesanddivas.bsky.social",
        bluesky_app_password=SimpleNamespace(
            get_secret_value=lambda: "test-app-password"
        ),
    )

    monkeypatch.setattr(
        "app.platforms.bluesky.get_settings",
        lambda: settings,
    )

    return BlueskyPlatform()


def test_platform_name(platform):
    assert platform.platform_name == "Bluesky"


def test_missing_credentials(monkeypatch):
    settings = SimpleNamespace(
        bluesky_handle=None,
        bluesky_app_password=None,
    )

    monkeypatch.setattr(
        "app.platforms.bluesky.get_settings",
        lambda: settings,
    )

    with pytest.raises(
        ValueError,
        match="not configured",
    ):
        BlueskyPlatform()


def test_empty_message_rejected(platform):
    with pytest.raises(
        ValueError,
        match="cannot be empty",
    ):
        platform._validate_message("")


def test_whitespace_message_rejected(platform):
    with pytest.raises(
        ValueError,
        match="cannot be empty",
    ):
        platform._validate_message("   ")


def test_200_character_message_accepted(platform):
    message = "A" * 200

    platform._validate_message(message)


def test_201_character_message_rejected(platform):
    message = "A" * 201

    with pytest.raises(
        ValueError,
        match="200 characters",
    ):
        platform._validate_message(message)


def test_unicode_and_emoji_message(platform):
    message = "Hello 👋 Dude's & Diva's"

    platform._validate_message(message)


def test_url_is_converted_to_clickable_facet(platform):
    message = "Visit https://example.com today"

    result = platform._build_post_text(message)

    assert result.build_text() == message

    facets = result.build_facets()

    assert len(facets) == 1


def test_multiple_urls_are_supported(platform):
    message = (
        "Visit https://example.com "
        "and https://example.org"
    )

    result = platform._build_post_text(message)

    facets = result.build_facets()

    assert len(facets) == 2


def test_message_without_url_remains_plain_text(platform):
    message = "Hello from Dude's & Diva's"

    result = platform._build_post_text(message)

    assert result == message


def test_trailing_punctuation_is_not_part_of_url(platform):
    message = "Visit https://example.com."

    result = platform._build_post_text(message)

    assert result.build_text() == message

    facets = result.build_facets()

    assert len(facets) == 1


def test_invalid_post_uri_rejected(platform):
    with pytest.raises(
        RuntimeError,
        match="unexpected post URI",
    ):
        platform._get_post_url(
            "invalid-uri",
            "dudesanddivas.bsky.social",
        )


def test_post_url_generation(platform):
    url = platform._get_post_url(
        "at://did:plc:example/app.bsky.feed.post/abc123",
        "dudesanddivas.bsky.social",
    )

    assert url == (
        "https://bsky.app/profile/"
        "dudesanddivas.bsky.social/post/abc123"
    )


@pytest.mark.anyio
async def test_successful_publish(platform, monkeypatch):
    response = SimpleNamespace(
        uri=(
            "at://did:plc:example/"
            "app.bsky.feed.post/abc123"
        )
    )

    mock_client = MagicMock()

    mock_client.login.return_value = None
    mock_client.send_post.return_value = response

    monkeypatch.setattr(
        "app.platforms.bluesky.Client",
        lambda: mock_client,
    )

    result = await platform.publish(
        "Hello from Dude's & Diva's"
    )

    assert result["posted_url"] == (
        "https://bsky.app/profile/"
        "dudesanddivas.bsky.social/post/abc123"
    )

    assert result["public_access"] is True

    assert isinstance(result["date"], date)
    assert isinstance(result["time"], time)

    mock_client.login.assert_called_once_with(
        login="dudesanddivas.bsky.social",
        password="test-app-password",
    )

    mock_client.send_post.assert_called_once()


@pytest.mark.anyio
async def test_invalid_message_does_not_call_api(
    platform,
    monkeypatch,
):
    mock_client = MagicMock()

    monkeypatch.setattr(
        "app.platforms.bluesky.Client",
        lambda: mock_client,
    )

    with pytest.raises(
        ValueError,
        match="200 characters",
    ):
        await platform.publish("A" * 201)

    mock_client.login.assert_not_called()


@pytest.mark.anyio
async def test_missing_post_uri_raises_error(
    platform,
    monkeypatch,
):
    mock_client = MagicMock()

    mock_client.login.return_value = None
    mock_client.send_post.return_value = SimpleNamespace(
        uri=None
    )

    monkeypatch.setattr(
        "app.platforms.bluesky.Client",
        lambda: mock_client,
    )

    with pytest.raises(
        RuntimeError,
        match="post URI",
    ):
        await platform.publish("Test message")


@pytest.mark.anyio
async def test_authentication_failure(
    platform,
    monkeypatch,
):
    mock_client = MagicMock()

    mock_client.login.side_effect = Exception(
        "Authentication failed"
    )

    monkeypatch.setattr(
        "app.platforms.bluesky.Client",
        lambda: mock_client,
    )

    with pytest.raises(
        RuntimeError,
        match="unexpected Exception",
    ):
        await platform.publish("Test message")


@pytest.mark.anyio
async def test_publishing_failure(
    platform,
    monkeypatch,
):
    mock_client = MagicMock()

    mock_client.login.return_value = None
    mock_client.send_post.side_effect = Exception(
        "Publishing failed"
    )

    monkeypatch.setattr(
        "app.platforms.bluesky.Client",
        lambda: mock_client,
    )

    with pytest.raises(
        RuntimeError,
        match="unexpected Exception",
    ):
        await platform.publish("Test message")