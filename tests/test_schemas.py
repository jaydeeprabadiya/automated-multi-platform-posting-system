import pytest

from pydantic import ValidationError

from app.schemas import (
    MessageRequest,
    PlatformResult,
    PostingResponse,
    PostingStatus,
)


class TestMessageRequest:
    """Tests for message request validation."""

    def test_valid_https_message(self):
        request = MessageRequest(
            message="Grow your business https://example.com"
        )

        assert request.message == (
            "Grow your business https://example.com"
        )

    def test_valid_http_message(self):
        request = MessageRequest(
            message="Visit http://example.com"
        )

        assert request.message.startswith("Visit http://")

    def test_missing_url(self):
        with pytest.raises(ValidationError):
            MessageRequest(message="Hello World")

    def test_multiple_urls(self):
        with pytest.raises(ValidationError):
            MessageRequest(
                message="https://google.com https://example.com"
            )

    def test_invalid_url(self):
        with pytest.raises(ValidationError):
            MessageRequest(message="Visit https://")

    def test_empty_message(self):
        with pytest.raises(ValidationError):
            MessageRequest(message="")

    def test_message_exceeding_limit(self):
        message = "A" * 181 + " https://example.com"

        with pytest.raises(ValidationError):
            MessageRequest(message=message)

    def test_exactly_200_characters(self):
        message = "A" * 180 + " https://example.com"

        assert len(message) == 200

        request = MessageRequest(message=message)

        assert request.message == message

    def test_url_with_path(self):
        request = MessageRequest(
            message="Visit https://example.com/products"
        )

        assert request.message

    def test_url_with_query_parameters(self):
        request = MessageRequest(
            message="Visit https://example.com?ref=test"
        )

        assert request.message

    def test_url_with_trailing_punctuation(self):
        request = MessageRequest(
            message="Visit https://example.com."
        )

        assert request.message.endswith(".")

    def test_url_with_credentials_is_rejected(self):
        with pytest.raises(
            ValidationError,
            match="URLs containing credentials are not allowed"
        ):
            MessageRequest(
                message="Visit https://user:password@example.com"
            )    


class TestPlatformResult:
    """Tests for individual platform publishing results."""

    def test_successful_platform_result(self):
        result = PlatformResult(
            platform="Facebook",
            status=PostingStatus.SUCCESS,
            posted_url="https://facebook.com/post/123",
            public_access=True,
            error=None,
        )

        assert result.platform == "Facebook"
        assert result.status == PostingStatus.SUCCESS
        assert result.public_access is True

    def test_failed_platform_result(self):
        result = PlatformResult(
            platform="Instagram",
            status=PostingStatus.FAILED,
            error="Authentication failed",
        )

        assert result.status == PostingStatus.FAILED
        assert result.error == "Authentication failed"
        assert result.posted_url is None


class TestPostingResponse:
    """Tests for the overall posting response."""

    def test_posting_response(self):
        result = PlatformResult(
            platform="Facebook",
            status=PostingStatus.SUCCESS,
            posted_url="https://facebook.com/post/123",
            public_access=True,
        )

        response = PostingResponse(
            success=True,
            results=[result],
        )

        assert response.success is True
        assert len(response.results) == 1

    def test_empty_results(self):
        response = PostingResponse(success=False)

        assert response.results == []