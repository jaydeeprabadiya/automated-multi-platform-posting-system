from typing import List, Mapping, Optional

from app.platforms.base import BasePlatform, MediaPlatform
from app.schemas import (
    PlatformResult,
    PostingResponse,
    PostingStatus,
)
from app.services.posting_repository import PostingRepository


class PostingService:
    """
    Coordinates publishing across multiple platforms.

    Features:
    - Persistent duplicate protection
    - Per-platform publishing history
    - Successful platform preservation
    - Failed platform retry support
    - Concurrent duplicate request protection
    """

    def __init__(
        self,
        platforms: List[BasePlatform],
        repository: Optional[PostingRepository] = None,
    ) -> None:
        self.platforms = list(platforms)
        self.repository = repository or PostingRepository()

    @staticmethod
    def _get_platform_name(platform: BasePlatform) -> str:
        try:
            name = platform.platform_name

            if isinstance(name, str) and name.strip():
                return name.strip()

        except Exception:
            pass

        return platform.__class__.__name__

    async def publish_to_all(
        self,
        message: str,
        media_url: Optional[str] = None,
    ) -> PostingResponse:

        fingerprint = self.repository.create_fingerprint(
            message=message,
            media_url=media_url,
        )

        existing_request = self.repository.get_request(fingerprint)

        if existing_request is None:
            created = self.repository.create_request(
                fingerprint=fingerprint,
                message=message,
                media_url=media_url,
            )

            if not created:
                existing_request = self.repository.get_request(fingerprint)

        stored_results = self.repository.get_platform_results(fingerprint)

        results: List[PlatformResult] = []

        for platform in self.platforms:
            platform_name = self._get_platform_name(platform)

            previous_result = stored_results.get(platform_name)

            # Never republish platforms that already succeeded.
            if previous_result and previous_result["status"] == "success":
                results.append(
                    PlatformResult(
                        platform=platform_name,
                        status=PostingStatus.SUCCESS,
                        posted_url=previous_result.get("posted_url"),
                    )
                )
                continue

            # Claim the platform atomically.
            # Prevents simultaneous requests from publishing
            # to the same platform for the same content.
            claimed = self.repository.claim_platform(
                fingerprint=fingerprint,
                platform=platform_name,
            )

            if not claimed:
                if previous_result:
                    results.append(
                        PlatformResult(
                            platform=platform_name,
                            status=PostingStatus.FAILED,
                            error=(
                                previous_result.get("error")
                                or "Platform is already processing or cannot be retried."
                            ),
                        )
                    )
                else:
                    results.append(
                        PlatformResult(
                            platform=platform_name,
                            status=PostingStatus.FAILED,
                            error="Publishing is already in progress.",
                        )
                    )
                continue

            try:
                if isinstance(platform, MediaPlatform):
                    if not media_url:
                        raise ValueError(
                            f"{platform_name} requires a media URL."
                        )

                    response = await platform.publish_media(
                        message=message,
                        media_url=media_url,
                    )
                else:
                    response = await platform.publish(message)

                if not isinstance(response, Mapping):
                    raise ValueError(
                        "Platform returned an invalid response format."
                    )

                posted_url = response.get("posted_url")

                self.repository.save_platform_result(
                    fingerprint=fingerprint,
                    platform=platform_name,
                    status="success",
                    posted_url=posted_url,
                )

                results.append(
                    PlatformResult(
                        platform=platform_name,
                        status=PostingStatus.SUCCESS,
                        posted_url=posted_url,
                        public_access=response.get("public_access"),
                        date=response.get("date"),
                        time=response.get("time"),
                    )
                )

            except Exception as exc:
                error_message = str(exc) or "Unknown publishing error."

                self.repository.save_platform_result(
                    fingerprint=fingerprint,
                    platform=platform_name,
                    status="failed",
                    error=error_message,
                )

                results.append(
                    PlatformResult(
                        platform=platform_name,
                        status=PostingStatus.FAILED,
                        error=error_message,
                    )
                )

        stored_results = self.repository.get_platform_results(fingerprint)

        all_completed = all(
            stored_results.get(self._get_platform_name(platform), {}).get("status")
            in ("success", "failed")
            for platform in self.platforms
        )

        any_success = any(
            result.status == PostingStatus.SUCCESS
            for result in results
        )

        request_status = (
            "completed"
            if all_completed
            else "processing"
        )

        self.repository.update_request_status(
            fingerprint=fingerprint,
            status=request_status,
        )

        return PostingResponse(
            success=any_success,
            results=results,
        )