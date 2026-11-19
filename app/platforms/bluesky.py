import asyncio
import ipaddress
import logging
import re
import socket
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

import httpx
from atproto import Client, models
from atproto.exceptions import AtProtocolError
from atproto_client.utils.text_builder import TextBuilder

from app.config import get_settings
from app.platforms.base import MediaPlatform


logger = logging.getLogger(__name__)


class BlueskyPlatform(MediaPlatform):
    """
    Bluesky publishing integration using the official AT Protocol SDK.

    Features:
    - Secure App Password authentication.
    - Text publishing.
    - Image publishing.
    - Clickable URL facets.
    - Maximum 200-character application limit.
    - Secure HTTPS image downloads.
    - SSRF protection.
    - Maximum 2 MB image size.
    - Async-compatible SDK execution.
    """

    MAX_MESSAGE_LENGTH = 200
    MAX_IMAGE_SIZE = 2 * 1024 * 1024

    ALLOWED_IMAGE_TYPES = {
        "image/jpeg": (b"\xff\xd8\xff",),
        "image/png": (b"\x89PNG\r\n\x1a\n",),
        "image/webp": (b"RIFF",),
    }

    URL_PATTERN = re.compile(
        r"https?://[^\s<>]+",
        re.IGNORECASE,
    )

    TRAILING_URL_PUNCTUATION = ".,!?;:)]}"

    def __init__(self) -> None:
        self.settings = get_settings()
        self.handle = self.settings.bluesky_handle

        self.app_password: Optional[str] = None

        if self.settings.bluesky_app_password:
            self.app_password = (
                self.settings.bluesky_app_password.get_secret_value()
            )

        if not self.handle or not self.app_password:
            raise ValueError(
                "Bluesky handle or App Password is not configured."
            )

    @property
    def platform_name(self) -> str:
        return "Bluesky"

    @classmethod
    def _validate_message(cls, message: str) -> None:
        if not isinstance(message, str):
            raise ValueError(
                "Bluesky message must be a string."
            )

        if not message.strip():
            raise ValueError(
                "Bluesky message cannot be empty."
            )

        if len(message) > cls.MAX_MESSAGE_LENGTH:
            raise ValueError(
                "Bluesky message cannot exceed "
                f"{cls.MAX_MESSAGE_LENGTH} characters."
            )

    @classmethod
    def _build_post_text(cls, message: str) -> Any:
        matches = list(cls.URL_PATTERN.finditer(message))

        if not matches:
            return message

        builder = TextBuilder()
        cursor = 0

        for match in matches:
            raw_url = match.group(0)

            url = raw_url.rstrip(
                cls.TRAILING_URL_PUNCTUATION
            )

            trailing_text = raw_url[len(url):]

            if not url:
                continue

            parsed_url = urlsplit(url)

            if (
                parsed_url.scheme not in ("http", "https")
                or not parsed_url.netloc
                or parsed_url.username is not None
                or parsed_url.password is not None
            ):
                continue

            if match.start() > cursor:
                builder.text(
                    message[cursor:match.start()]
                )

            builder.link(
                text=url,
                url=url,
            )

            if trailing_text:
                builder.text(trailing_text)

            cursor = match.end()

        if cursor < len(message):
            builder.text(
                message[cursor:]
            )

        return builder

    @staticmethod
    def _get_post_url(
        post_uri: str,
        handle: str,
    ) -> str:
        if not isinstance(post_uri, str):
            raise RuntimeError(
                "Bluesky returned an invalid post URI."
            )

        parsed = urlsplit(post_uri)
        path_parts = parsed.path.strip("/").split("/")

        if (
            parsed.scheme != "at"
            or not parsed.netloc
            or len(path_parts) != 2
            or path_parts[0] != "app.bsky.feed.post"
            or not path_parts[1]
            or not handle
        ):
            raise RuntimeError(
                "Bluesky returned an unexpected post URI."
            )

        record_key = path_parts[1]

        return (
            f"https://bsky.app/profile/"
            f"{handle}/post/{record_key}"
        )

    @classmethod
    def _validate_image_url(
        cls,
        media_url: str,
    ) -> str:
        if not isinstance(media_url, str):
            raise ValueError(
                "Image URL must be a string."
            )

        parsed = urlsplit(media_url)

        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError(
                "Image URL must be a valid HTTPS URL."
            )

        if parsed.port not in (None, 443):
            raise ValueError(
                "Image URL uses an unsupported port."
            )

        hostname = parsed.hostname.lower()

        if hostname in (
            "localhost",
            "localhost.localdomain",
        ):
            raise ValueError(
                "Private or local image URLs are not allowed."
            )

        try:
            ip_address = ipaddress.ip_address(hostname)

            if not ip_address.is_global:
                raise ValueError(
                    "Private or local image URLs are not allowed."
                )

        except ValueError as exc:
            if "not allowed" in str(exc):
                raise

            if "unsupported" in str(exc):
                raise

            if "valid HTTPS" in str(exc):
                raise

            if hostname.startswith("127."):
                raise ValueError(
                    "Private or local image URLs are not allowed."
                )

        return media_url

    @classmethod
    def _validate_image_data(
        cls,
        image_data: bytes,
        content_type: str,
    ) -> str:
        if not image_data:
            raise ValueError(
                "Downloaded image is empty."
            )

        if len(image_data) > cls.MAX_IMAGE_SIZE:
            raise ValueError(
                "Bluesky image cannot exceed 2 MB."
            )

        content_type = (
            content_type.lower()
            .split(";")[0]
            .strip()
        )

        signatures = cls.ALLOWED_IMAGE_TYPES.get(
            content_type
        )

        if not signatures:
            raise ValueError(
                "Unsupported image type. "
                "Only JPEG, PNG, and WebP are supported."
            )

        if content_type == "image/webp":
            valid_signature = (
                len(image_data) >= 12
                and image_data[:4] == b"RIFF"
                and image_data[8:12] == b"WEBP"
            )
        else:
            valid_signature = any(
                image_data.startswith(signature)
                for signature in signatures
            )

        if not valid_signature:
            raise ValueError(
                "Image content does not match its declared type."
            )

        return content_type

    @classmethod
    def _is_public_ip(
        cls,
        hostname: str,
    ) -> bool:
        try:
            results = socket.getaddrinfo(
                hostname,
                443,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror:
            raise ValueError(
                "Unable to resolve image host."
            ) from None

        if not results:
            raise ValueError(
                "Image host did not resolve."
            )

        for result in results:
            address = result[4][0]

            try:
                ip = ipaddress.ip_address(address)
            except ValueError:
                return False

            if not ip.is_global:
                return False

        return True

    @classmethod
    def _download_image_sync(
        cls,
        media_url: str,
    ) -> tuple[bytes, str]:
        media_url = cls._validate_image_url(
            media_url
        )

        parsed = urlsplit(media_url)
        hostname = parsed.hostname

        if not hostname:
            raise ValueError(
                "Invalid image hostname."
            )

        if not cls._is_public_ip(hostname):
            raise ValueError(
                "Private or non-public image hosts are not allowed."
            )

        timeout = httpx.Timeout(
            15.0,
            connect=5.0,
        )

        limits = httpx.Limits(
            max_connections=1,
            max_keepalive_connections=0,
        )

        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            limits=limits,
        ) as client:

            with client.stream(
                "GET",
                media_url,
                headers={
                    "Accept": "image/jpeg,image/png,image/webp",
                    "User-Agent": "AutomatedPosting/1.0",
                },
            ) as response:

                if response.status_code != 200:
                    raise RuntimeError(
                        "Image download failed with HTTP "
                        f"{response.status_code}."
                    )

                content_type = response.headers.get(
                    "content-type",
                    "",
                )

                content_length = response.headers.get(
                    "content-length"
                )

                if content_length:
                    try:
                        if int(content_length) > cls.MAX_IMAGE_SIZE:
                            raise ValueError(
                                "Bluesky image cannot exceed 2 MB."
                            )
                    except ValueError as exc:
                        if "cannot exceed" in str(exc):
                            raise

                image_data = bytearray()

                for chunk in response.iter_bytes():
                    image_data.extend(chunk)

                    if len(image_data) > cls.MAX_IMAGE_SIZE:
                        raise ValueError(
                            "Bluesky image cannot exceed 2 MB."
                        )

        validated_type = cls._validate_image_data(
            bytes(image_data),
            content_type,
        )

        return bytes(image_data), validated_type

    @staticmethod
    def _get_aspect_ratio(
        image_data: bytes,
    ) -> Optional[Any]:
        try:
            from PIL import Image
            import io

            with Image.open(
                io.BytesIO(image_data)
            ) as image:
                width, height = image.size

            if width <= 0 or height <= 0:
                return None

            return models.AppBskyEmbedDefs.AspectRatio(
                width=width,
                height=height,
            )

        except Exception:
            return None

    def _publish_sync(
        self,
        message: str,
    ) -> Dict[str, Any]:
        client = Client()

        try:
            client.login(
                login=self.handle,
                password=self.app_password,
            )

            post_text = self._build_post_text(
                message
            )

            response = client.send_post(
                text=post_text,
                langs=["en"],
            )

            post_uri = getattr(
                response,
                "uri",
                None,
            )

            if not post_uri:
                raise RuntimeError(
                    "Bluesky did not return a post URI. "
                    "Publishing outcome may be uncertain."
                )

            posted_url = self._get_post_url(
                post_uri,
                self.handle,
            )

            published_at = datetime.now(
                timezone.utc
            )

            return {
                "posted_url": posted_url,
                "public_access": True,
                "date": published_at.date(),
                "time": published_at.time().replace(
                    tzinfo=None
                ),
            }

        except AtProtocolError as exc:
            raise RuntimeError(
                "Bluesky API request failed: "
                f"{type(exc).__name__}."
            ) from None

        except RuntimeError:
            raise

        except Exception as exc:
            logger.exception(
                "Bluesky text publishing failed: %s",
                exc,
            )

            raise RuntimeError(
                "Bluesky publishing failed due to an unexpected "
                f"{type(exc).__name__} error: {exc}"
            ) from None

    def _publish_media_sync(
        self,
        message: str,
        media_url: str,
    ) -> Dict[str, Any]:
        client = Client()

        try:
            image_data, content_type = (
                self._download_image_sync(
                    media_url
                )
            )

            client.login(
                login=self.handle,
                password=self.app_password,
            )

            upload_response = client.upload_blob(
                image_data
            )

            blob = getattr(
                upload_response,
                "blob",
                None,
            )

            if blob is None:
                raise RuntimeError(
                    "Bluesky image upload returned no blob."
                )

            aspect_ratio = self._get_aspect_ratio(
                image_data
            )

            image_item = models.AppBskyEmbedImages.Image(
                image=blob,
                alt="Image attached to this post",
                aspect_ratio=aspect_ratio,
            )

            embed = models.AppBskyEmbedImages.Main(
                images=[image_item]
            )

            post_text = self._build_post_text(
                message
            )

            response = client.send_post(
                text=post_text,
                embed=embed,
                langs=["en"],
            )

            post_uri = getattr(
                response,
                "uri",
                None,
            )

            if not post_uri:
                raise RuntimeError(
                    "Bluesky did not return a post URI. "
                    "Publishing outcome may be uncertain."
                )

            posted_url = self._get_post_url(
                post_uri,
                self.handle,
            )

            published_at = datetime.now(
                timezone.utc
            )

            return {
                "posted_url": posted_url,
                "public_access": True,
                "date": published_at.date(),
                "time": published_at.time().replace(
                    tzinfo=None
                ),
            }

        except AtProtocolError as exc:
            logger.exception(
                "Bluesky API media publishing failed: %s",
                exc,
            )

            raise RuntimeError(
                "Bluesky API request failed: "
                f"{type(exc).__name__}: {exc}"
            ) from None

        except RuntimeError:
            raise

        except Exception as exc:
            logger.exception(
                "Bluesky media publishing failed: %s",
                exc,
            )

            raise RuntimeError(
                "Bluesky media publishing failed due to an unexpected "
                f"{type(exc).__name__} error: {exc}"
            ) from None

    async def publish(
        self,
        message: str,
    ) -> Dict[str, Any]:
        self._validate_message(message)

        return await asyncio.to_thread(
            self._publish_sync,
            message,
        )

    async def publish_media(
        self,
        message: str,
        media_url: str,
    ) -> Dict[str, Any]:
        self._validate_message(message)

        self._validate_image_url(
            media_url
        )

        return await asyncio.to_thread(
            self._publish_media_sync,
            message,
            media_url,
        )