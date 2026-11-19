import pytest
from datetime import date, time

from app.services.posting_service import PostingService
from app.services.posting_repository import PostingRepository
from app.schemas import PostingStatus


@pytest.fixture
def repository(tmp_path):
    return PostingRepository(
        database_path=tmp_path / "posting_history.db"
    )


class MockPlatform:

    def __init__(self, name, response=None, error=None):
        self._name = name
        self.response = response
        self.error = error
        self.publish_calls = 0

    @property
    def platform_name(self):
        return self._name

    async def publish(self, message):
        self.publish_calls += 1

        if self.error:
            raise self.error

        return self.response


@pytest.mark.anyio
async def test_all_platforms_publish_successfully(repository):

    platforms = [
        MockPlatform(
            "Facebook",
            {
                "posted_url": "https://facebook.com/post/123",
                "public_access": True,
                "date": date.today(),
                "time": time(10, 30),
            },
        ),
        MockPlatform(
            "LinkedIn",
            {
                "posted_url": "https://linkedin.com/post/456",
                "public_access": True,
            },
        ),
    ]

    service = PostingService(platforms, repository=repository)

    result = await service.publish_to_all(
        "Hello https://example.com"
    )

    assert result.success is True
    assert len(result.results) == 2

    assert all(
        item.status == PostingStatus.SUCCESS
        for item in result.results
    )


@pytest.mark.anyio
async def test_one_platform_failure_does_not_stop_others(repository):

    platforms = [
        MockPlatform(
            "Facebook",
            error=Exception("Facebook API error"),
        ),
        MockPlatform(
            "LinkedIn",
            {"posted_url": "https://linkedin.com/post/123"},
        ),
    ]

    service = PostingService(platforms, repository=repository)

    result = await service.publish_to_all(
        "Hello https://example.com"
    )

    assert len(result.results) == 2
    assert result.results[0].status == PostingStatus.FAILED
    assert result.results[1].status == PostingStatus.SUCCESS
    assert result.success is True


@pytest.mark.anyio
async def test_all_platforms_failure(repository):

    platforms = [
        MockPlatform("Facebook", error=Exception("Facebook failed")),
        MockPlatform("LinkedIn", error=Exception("LinkedIn failed")),
    ]

    service = PostingService(platforms, repository=repository)

    result = await service.publish_to_all(
        "Hello https://example.com"
    )

    assert result.success is False
    assert len(result.results) == 2

    assert all(
        item.status == PostingStatus.FAILED
        for item in result.results
    )


@pytest.mark.anyio
async def test_empty_platform_list(repository):

    service = PostingService([], repository=repository)

    result = await service.publish_to_all(
        "Hello https://example.com"
    )

    assert result.success is False
    assert result.results == []


@pytest.mark.anyio
async def test_failed_platform_contains_error_message(repository):

    platforms = [
        MockPlatform(
            "Reddit",
            error=Exception("Authentication failed"),
        )
    ]

    service = PostingService(platforms, repository=repository)

    result = await service.publish_to_all(
        "Hello https://example.com"
    )

    assert result.results[0].error == "Authentication failed"
    assert result.results[0].status == PostingStatus.FAILED


@pytest.mark.anyio
async def test_invalid_platform_response_is_handled(repository):

    platforms = [
        MockPlatform("Facebook", response=None),
        MockPlatform(
            "LinkedIn",
            {"posted_url": "https://linkedin.com/post/123"},
        ),
    ]

    service = PostingService(platforms, repository=repository)

    result = await service.publish_to_all(
        "Hello https://example.com"
    )

    assert result.results[0].status == PostingStatus.FAILED
    assert result.results[1].status == PostingStatus.SUCCESS


@pytest.mark.anyio
async def test_platform_name_exception_is_handled(repository):

    class BrokenNamePlatform:

        @property
        def platform_name(self):
            raise RuntimeError("Platform name unavailable")

        async def publish(self, message):
            return {
                "posted_url": "https://example.com/post/123"
            }

    service = PostingService(
        [BrokenNamePlatform()],
        repository=repository,
    )

    result = await service.publish_to_all(
        "Hello https://example.com"
    )

    assert result.results[0].platform == "BrokenNamePlatform"
    assert result.results[0].status == PostingStatus.SUCCESS


@pytest.mark.anyio
async def test_list_response_is_rejected(repository):

    platforms = [
        MockPlatform("Facebook", response=["invalid", "response"])
    ]

    service = PostingService(platforms, repository=repository)

    result = await service.publish_to_all(
        "Hello https://example.com"
    )

    assert result.results[0].status == PostingStatus.FAILED
    assert "invalid response format" in result.results[0].error

@pytest.mark.anyio
async def test_successful_platform_is_not_published_twice(repository):

    facebook = MockPlatform(
        "Facebook",
        {"posted_url": "https://facebook.com/post/123"},
    )

    service = PostingService([facebook], repository=repository)

    first_result = await service.publish_to_all("Duplicate protection test")
    second_result = await service.publish_to_all("Duplicate protection test")

    assert first_result.results[0].status == PostingStatus.SUCCESS
    assert second_result.results[0].status == PostingStatus.SUCCESS

    # Facebook should only be called once.
    assert facebook.publish_calls == 1


@pytest.mark.anyio
async def test_failed_platform_can_be_retried(repository):

    facebook = MockPlatform(
        "Facebook",
        error=Exception("Temporary failure"),
    )

    service = PostingService([facebook], repository=repository)

    first_result = await service.publish_to_all("Retry protection test")

    assert first_result.results[0].status == PostingStatus.FAILED
    assert facebook.publish_calls == 1

    # Fix the simulated platform failure.
    facebook.error = None
    facebook.response = {
        "posted_url": "https://facebook.com/post/retry123"
    }

    second_result = await service.publish_to_all("Retry protection test")

    assert second_result.results[0].status == PostingStatus.SUCCESS
    assert facebook.publish_calls == 2


@pytest.mark.anyio
async def test_successful_platform_skipped_when_other_platform_retries(repository):

    facebook = MockPlatform(
        "Facebook",
        {"posted_url": "https://facebook.com/post/123"},
    )

    instagram = MockPlatform(
        "Instagram",
        error=Exception("Instagram temporarily unavailable"),
    )

    service = PostingService(
        [facebook, instagram],
        repository=repository,
    )

    first_result = await service.publish_to_all(
        "Multi-platform retry test"
    )

    assert first_result.results[0].status == PostingStatus.SUCCESS
    assert first_result.results[1].status == PostingStatus.FAILED

    facebook.error = None
    instagram.error = None
    instagram.response = {
        "posted_url": "https://instagram.com/p/retry123"
    }

    second_result = await service.publish_to_all(
        "Multi-platform retry test"
    )

    assert second_result.results[0].status == PostingStatus.SUCCESS
    assert second_result.results[1].status == PostingStatus.SUCCESS

    # Facebook must not be reposted.
    assert facebook.publish_calls == 1

    # Instagram should be retried.
    assert instagram.publish_calls == 2


@pytest.mark.anyio
async def test_different_content_creates_separate_post(repository):

    facebook = MockPlatform(
        "Facebook",
        {"posted_url": "https://facebook.com/post/123"},
    )

    service = PostingService([facebook], repository=repository)

    await service.publish_to_all("First unique message")
    await service.publish_to_all("Second unique message")

    assert facebook.publish_calls == 2