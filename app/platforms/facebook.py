import re
from datetime import datetime, timezone
from typing import Any, Dict
from urllib.parse import urlsplit

import httpx

from app.config import get_settings
from app.platforms.base import MediaPlatform


class FacebookPlatform(MediaPlatform):
    """
    Facebook Page publishing integration using Meta Graph API.
    Supports text/link posts and image posts with captions.
    """

    API_VERSION = "v27.0"
    BASE_URL = f"https://graph.facebook.com/{API_VERSION}"

    def __init__(self) -> None:
        self.settings = get_settings()

        self.page_id = self.settings.facebook_page_id
        self.access_token = (
            self.settings.facebook_access_token.get_secret_value()
        )

        self.timeout = self.settings.http_timeout

        if not self.page_id or not self.access_token:
            raise ValueError(
                "Facebook Page ID or Access Token is not configured."
            )

    @property
    def platform_name(self) -> str:
        return "Facebook"

    @staticmethod
    def _extract_url(message: str) -> str:
        urls = re.findall(
            r"https?://[^\s<>\"']+",
            message,
            re.IGNORECASE,
        )

        if len(urls) != 1:
            raise ValueError(
                "Facebook requires exactly one CTA URL."
            )

        url = urls[0].rstrip(".,!?;:)")

        parsed_url = urlsplit(url)

        if parsed_url.scheme not in ("http", "https"):
            raise ValueError("Invalid Facebook CTA URL.")

        if not parsed_url.hostname:
            raise ValueError("Invalid Facebook CTA URL.")

        if parsed_url.username or parsed_url.password:
            raise ValueError("Invalid Facebook CTA URL.")

        return url

    @staticmethod
    def _validate_media_url(media_url: str) -> str:
        parsed_url = urlsplit(media_url)

        if parsed_url.scheme != "https":
            raise ValueError(
                "Facebook media URL must use HTTPS."
            )

        if not parsed_url.hostname:
            raise ValueError(
                "Invalid Facebook media URL."
            )

        if parsed_url.username or parsed_url.password:
            raise ValueError(
                "Invalid Facebook media URL."
            )

        return media_url

    async def _get_permalink(
        self,
        client: httpx.AsyncClient,
        post_id: str,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
        }

        response = await client.get(
            f"{self.BASE_URL}/{post_id}",
            headers=headers,
            params={"fields": "permalink_url"},
        )

        try:
            response_data = response.json()
        except ValueError:
            raise RuntimeError(
                "Facebook returned an invalid permalink response. "
                "The post may already have been published."
            ) from None

        if response.is_error:
            error = response_data.get("error", {})
            error_message = error.get(
                "message",
                "Could not retrieve Facebook post permalink.",
            )

            raise RuntimeError(
                f"Facebook permalink API Error: {error_message}. "
                "The post may already have been published."
            )

        posted_url = response_data.get("permalink_url")

        if not posted_url:
            raise RuntimeError(
                "Facebook did not return permalink_url. "
                "The post may already have been published."
            )

        return posted_url

    @staticmethod
    def _published_result(posted_url: str) -> Dict[str, Any]:
        published_at = datetime.now(timezone.utc)

        return {
            "posted_url": posteded_url if False else posted_url,
            "public_access": None,
            "date": published_at.date(),
            "time": published_at.time().replace(tzinfo=None),
        }

    async def publish(self, message: str) -> Dict[str, Any]:
        """
        Publish a text/link post to a Facebook Page.
        """

        cta_url = self._extract_url(message)

        endpoint = f"{self.BASE_URL}/{self.page_id}/feed"

        headers = {
            "Authorization": f"Bearer {self.access_token}",
        }

        payload = {
            "message": message,
            "link": cta_url,
        }

        async with httpx.AsyncClient(
            timeout=self.timeout
        ) as client:

            response = await client.post(
                endpoint,
                headers=headers,
                data=payload,
            )

            try:
                response_data = response.json()
            except ValueError:
                raise RuntimeError(
                    "Facebook returned an invalid publishing response."
                ) from None

            if response.is_error:
                error = response_data.get("error", {})
                error_message = error.get(
                    "message",
                    "Facebook publishing failed.",
                )

                raise RuntimeError(
                    f"Facebook API Error: {error_message}"
                )

            post_id = response_data.get("id")

            if not post_id:
                raise RuntimeError(
                    "Facebook API did not return a post ID."
                )

            posted_url = await self._get_permalink(
                client,
                post_id,
            )

        return self._published_result(posted_url)

    async def publish_media(
        self,
        message: str,
        media_url: str,
    ) -> Dict[str, Any]:
        """
        Publish an image with a caption to a Facebook Page.
        """

        media_url = self._validate_media_url(media_url)

        endpoint = f"{self.BASE_URL}/{self.page_id}/photos"

        headers = {
            "Authorization": f"Bearer {self.access_token}",
        }

        payload = {
            "url": media_url,
            "caption": message,
        }

        async with httpx.AsyncClient(
            timeout=self.timeout
        ) as client:

            response = await client.post(
                endpoint,
                headers=headers,
                data=payload,
            )

            try:
                response_data = response.json()
            except ValueError:
                raise RuntimeError(
                    "Facebook returned an invalid image publishing response."
                ) from None

            if response.is_error:
                error = response_data.get("error", {})
                error_message = error.get(
                    "message",
                    "Facebook image publishing failed.",
                )

                raise RuntimeError(
                    f"Facebook Image API Error: {error_message}"
                )

            # Facebook may return a photo ID and a post ID.
            # Prefer post_id for permalink lookup.
            post_id = response_data.get("post_id")

            if not post_id:
                post_id = response_data.get("id")

            if not post_id:
                raise RuntimeError(
                    "Facebook API did not return a photo or post ID."
                )

            posted_url = await self._get_permalink(
                client,
                post_id,
            )

        return self._published_result(posted_url)