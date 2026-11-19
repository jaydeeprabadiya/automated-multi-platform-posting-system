import concurrent.futures

import pytest

from app.services.posting_repository import PostingRepository


@pytest.fixture
def repository(tmp_path):
    database_path = tmp_path / "posting_history.db"
    return PostingRepository(database_path=str(database_path))


def test_same_content_generates_same_fingerprint():
    first = PostingRepository.create_fingerprint("Hello world")
    second = PostingRepository.create_fingerprint("Hello world")

    assert first == second


def test_different_message_generates_different_fingerprint():
    first = PostingRepository.create_fingerprint("Hello world")
    second = PostingRepository.create_fingerprint("Hello again")

    assert first != second


def test_different_media_generates_different_fingerprint():
    first = PostingRepository.create_fingerprint(
        "Hello world",
        "https://example.com/image1.jpg",
    )
    second = PostingRepository.create_fingerprint(
        "Hello world",
        "https://example.com/image2.jpg",
    )

    assert first != second


def test_create_request_saves_record(repository):
    fingerprint = repository.create_fingerprint("Hello world")

    assert repository.create_request(fingerprint, "Hello world", None) is True

    request = repository.get_request(fingerprint)

    assert request is not None
    assert request["message"] == "Hello world"
    assert request["status"] == "processing"


def test_duplicate_request_is_not_inserted_again(repository):
    fingerprint = repository.create_fingerprint("Hello world")

    assert repository.create_request(fingerprint, "Hello world", None) is True
    assert repository.create_request(fingerprint, "Hello world", None) is False


def test_platform_result_is_saved(repository):
    fingerprint = repository.create_fingerprint("Hello world")
    repository.create_request(fingerprint, "Hello world", None)

    repository.save_platform_result(
        fingerprint=fingerprint,
        platform="Facebook",
        status="success",
        posted_url="https://facebook.com/test",
    )

    results = repository.get_platform_results(fingerprint)

    assert results["Facebook"]["status"] == "success"
    assert results["Facebook"]["posted_url"] == "https://facebook.com/test"


def test_platform_result_can_be_updated(repository):
    fingerprint = repository.create_fingerprint("Hello world")
    repository.create_request(fingerprint, "Hello world", None)

    repository.save_platform_result(
        fingerprint=fingerprint,
        platform="Facebook",
        status="failed",
        error="Temporary error",
    )

    repository.save_platform_result(
        fingerprint=fingerprint,
        platform="Facebook",
        status="success",
        posted_url="https://facebook.com/test",
    )

    results = repository.get_platform_results(fingerprint)

    assert results["Facebook"]["status"] == "success"
    assert results["Facebook"]["posted_url"] == "https://facebook.com/test"
    assert results["Facebook"]["error"] is None


def test_request_status_can_be_updated(repository):
    fingerprint = repository.create_fingerprint("Hello world")
    repository.create_request(fingerprint, "Hello world", None)

    repository.update_request_status(fingerprint, "completed")

    assert repository.get_request(fingerprint)["status"] == "completed"


def test_concurrent_duplicate_requests_only_create_one_record(repository):
    message = "Concurrent duplicate test"
    fingerprint = repository.create_fingerprint(message)

    def create_request(_):
        return repository.create_request(fingerprint, message, None)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(create_request, range(20)))

    assert results.count(True) == 1
    assert results.count(False) == 19


def test_platform_can_be_claimed_once(repository):
    fingerprint = repository.create_fingerprint("Claim test")
    repository.create_request(fingerprint, "Claim test", None)

    assert repository.claim_platform(fingerprint, "Facebook") is True
    assert repository.claim_platform(fingerprint, "Facebook") is False


def test_failed_platform_can_be_reclaimed(repository):
    fingerprint = repository.create_fingerprint("Retry test")
    repository.create_request(fingerprint, "Retry test", None)

    assert repository.claim_platform(fingerprint, "Instagram") is True

    repository.save_platform_result(
        fingerprint,
        "Instagram",
        "failed",
        error="Temporary failure",
    )

    assert repository.claim_platform(fingerprint, "Instagram") is True


def test_successful_platform_cannot_be_reclaimed(repository):
    fingerprint = repository.create_fingerprint("Success test")
    repository.create_request(fingerprint, "Success test", None)

    assert repository.claim_platform(fingerprint, "Facebook") is True

    repository.save_platform_result(
        fingerprint,
        "Facebook",
        "success",
        posted_url="https://facebook.com/test",
    )

    assert repository.claim_platform(fingerprint, "Facebook") is False


def test_concurrent_platform_claim_only_succeeds_once(repository):
    fingerprint = repository.create_fingerprint("Concurrent claim")
    repository.create_request(fingerprint, "Concurrent claim", None)

    def claim(_):
        return repository.claim_platform(fingerprint, "Facebook")

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(claim, range(20)))

    assert results.count(True) == 1
    assert results.count(False) == 19