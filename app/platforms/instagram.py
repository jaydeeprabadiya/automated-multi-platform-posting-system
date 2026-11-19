import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

import httpx

from app.config import get_settings
from app.platforms.base import MediaPlatform


class InstagramPlatform(MediaPlatform):
    """
    Instagram publishing integration using Meta Graph API.

    Supports publishing single JPEG images with captions.
    """

    API_VERSION = "v27.0"
    BASE_URL = f"https://graph.facebook.com/{API_VERSION}"

    POLL_INTERVAL_SECONDS = 5
    MAX_POLL_ATTEMPTS = 12

    def __init__(self) -> None:
        self.settings = get_settings()

        self.instagram_user_id = self.settings.instagram_user_id

        access_token: Optional[str] = None

        if self.settings.instagram_access_token:
            access_token = (
                self.settings.instagram_access_token.get_secret_value()
            )

        self.access_token = access_token
        self.timeout = self.settings.http_timeout

        if not self.instagram_user_id or not self.access_token:
            raise ValueError(
                "Instagram User ID or Access Token is not configured."
            )

    @property
    def platform_name(self) -> str:
        return "Instagram"

    async def publish(self, message: str) -> Dict[str, Any]:
        """
        Instagram requires media content for publishing.

        Use publish_media() instead.
        """

        raise ValueError(
            "Instagram requires a media URL. "
            "Use publish_media() to publish content."
        )

    @staticmethod
    def _validate_media_url(media_url: str) -> None:
        """
        Validate the publicly accessible media URL.
        """

        parsed_url = urlsplit(media_url)

        if (
            parsed_url.scheme != "https"
            or not parsed_url.netloc
            or parsed_url.username is not None
            or parsed_url.password is not None
        ):
            raise ValueError(
                "Instagram media URL must be a valid public HTTPS URL."
            )

    def _get_headers(self) -> Dict[str, str]:
        """
        Return authorization headers.
        """

        return {
            "Authorization": f"Bearer {self.access_token}",
        }

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        method: str,
        endpoint: str,
        operation: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute an Instagram API request and validate its response.

        POST requests are not automatically retried because doing so
        could create duplicate containers or publish duplicate posts.
        """

        try:
            response = await client.request(
                method=method,
                url=endpoint,
                headers=self._get_headers(),
                data=data,
                params=params,
            )

        except httpx.TimeoutException:
            raise RuntimeError(
                f"Instagram API request timed out during {operation}."
            ) from None

        except httpx.RequestError:
            raise RuntimeError(
                f"Instagram API connection failed during {operation}."
            ) from None

        try:
            response_data = response.json()

        except ValueError:
            raise RuntimeError(
                f"Instagram returned an invalid response during {operation}."
            ) from None

        if not isinstance(response_data, dict):
            raise RuntimeError(
                f"Instagram returned an unexpected response during {operation}."
            )

        if response.is_error or "error" in response_data:
            error = response_data.get("error", {})

            if not isinstance(error, dict):
                error = {}

            error_message = error.get(
                "message",
                "Unknown Instagram API error.",
            )

            error_code = error.get("code")

            if error_code is not None:
                raise RuntimeError(
                    f"Instagram API Error ({error_code}): {error_message}"
                )

            raise RuntimeError(
                f"Instagram API Error: {error_message}"
            )

        return response_data

    async def _wait_for_container(
        self,
        client: httpx.AsyncClient,
        container_id: str,
    ) -> None:
        """
        Wait until Instagram finishes processing the media container.

        Publishing is allowed only when status_code is FINISHED.
        """

        endpoint = f"{self.BASE_URL}/{container_id}"

        for attempt in range(self.MAX_POLL_ATTEMPTS):

            status_data = await self._request_json(
                client=client,
                method="GET",
                endpoint=endpoint,
                operation="checking media container status",
                params={
                    "fields": "status_code,status",
                },
            )

            status_code = status_data.get("status_code")
            status_message = status_data.get("status", "")

            if status_code == "FINISHED":
                return

            if status_code == "ERROR":
                raise RuntimeError(
                    "Instagram media processing failed: "
                    f"{status_message or 'Unknown processing error.'}"
                )

            if status_code == "EXPIRED":
                raise RuntimeError(
                    "Instagram media container has expired."
                )

            if status_code == "PUBLISHED":
                raise RuntimeError(
                    "Instagram media container is already published."
                )

            if status_code != "IN_PROGRESS":
                raise RuntimeError(
                    "Instagram returned an unexpected container status: "
                    f"{status_code}"
                )

            if attempt < self.MAX_POLL_ATTEMPTS - 1:
                await asyncio.sleep(self.POLL_INTERVAL_SECONDS)

        raise TimeoutError(
            "Instagram media processing did not finish within "
            f"{self.MAX_POLL_ATTEMPTS * self.POLL_INTERVAL_SECONDS} seconds."
        )

    async def publish_media(
        self,
        message: str,
        media_url: str,
    ) -> Dict[str, Any]:
        """
        Publish an image with a caption to Instagram.

        Publishing flow:
        1. Create media container.
        2. Wait for media processing.
        3. Publish the media container.
        4. Retrieve the actual Instagram permalink.
        """

        self._validate_media_url(media_url)

        if len(message) > 2200:
            raise ValueError(
                "Instagram caption cannot exceed 2200 characters."
            )

        async with httpx.AsyncClient(
            timeout=self.timeout
        ) as client:

            # Step 1: Create Instagram media container.

            container_response = await self._request_json(
                client=client,
                method="POST",
                endpoint=f"{self.BASE_URL}/{self.instagram_user_id}/media",
                operation="creating media container",
                data={
                    "image_url": media_url,
                    "caption": message,
                },
            )

            container_id = container_response.get("id")

            if not container_id:
                raise RuntimeError(
                    "Instagram did not return a media container ID."
                )

            # Step 2: Wait for media processing to finish.

            await self._wait_for_container(
                client=client,
                container_id=container_id,
            )

            # Step 3: Publish the processed media container.

            publish_response = await self._request_json(
                client=client,
                method="POST",
                endpoint=(
                    f"{self.BASE_URL}/"
                    f"{self.instagram_user_id}/media_publish"
                ),
                operation="publishing Instagram media",
                data={
                    "creation_id": container_id,
                },
            )

            media_id = publish_response.get("id")

            if not media_id:
                raise RuntimeError(
                    "Instagram did not return a published media ID. "
                    "The publishing outcome may be uncertain."
                )

            # Step 4: Retrieve the actual published post permalink.

            try:
                permalink_response = await self._request_json(
                    client=client,
                    method="GET",
                    endpoint=f"{self.BASE_URL}/{media_id}",
                    operation="retrieving published post permalink",
                    params={
                        "fields": "permalink",
                    },
                )

            except RuntimeError as exc:
                raise RuntimeError(
                    "Instagram post may already be published. "
                    f"Media ID: {media_id}. "
                    f"Permalink retrieval failed: {exc}"
                ) from exc

            posted_url = permalink_response.get("permalink")

            if not posted_url:
                raise RuntimeError(
                    "Instagram published the media but did not return "
                    f"a permalink. Media ID: {media_id}."
                )

        published_at = datetime.now(timezone.utc)

        return {
            "posted_url": posted_url,
            "public_access": None,
            "date": published_at.date(),
            "time": published_at.time().replace(tzinfo=None),
        }