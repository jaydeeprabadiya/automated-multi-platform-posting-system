import ipaddress
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

import httpx

from app.config import get_settings
from app.platforms.base import MediaPlatform


class TelegramPlatform(MediaPlatform):
    """
    Telegram channel publishing integration.

    Supports:
    - Text messages
    - Image messages with captions
    - Telegram Bot API
    - HTTPS media URL validation
    - API response validation
    - Timeout and connection error handling
    - Secure token handling
    """

    MAX_MESSAGE_LENGTH = 4096
    MAX_CAPTION_LENGTH = 1024

    def __init__(self) -> None:
        self.settings = get_settings()

        token_setting = self.settings.telegram_bot_token

        self.bot_token: Optional[str] = (
            token_setting.get_secret_value()
            if token_setting
            else None
        )

        self.channel_id = self.settings.telegram_channel_id
        self.timeout = self.settings.http_timeout

        if not self.bot_token:
            raise ValueError(
                "Telegram bot token is not configured."
            )

        if not self.channel_id:
            raise ValueError(
                "Telegram channel ID is not configured."
            )

        self.channel_id = self.channel_id.strip()

        self.base_url = (
            "https://api.telegram.org/"
            f"bot{self.bot_token}"
        )

    @property
    def platform_name(self) -> str:
        return "Telegram"

    # --------------------------------------------------
    # Message validation
    # --------------------------------------------------

    @staticmethod
    def _validate_message(message: str) -> None:
        """
        Validate text message.
        """

        if not isinstance(message, str):
            raise ValueError(
                "Telegram message must be a string."
            )

        if not message.strip():
            raise ValueError(
                "Telegram message cannot be empty."
            )

        if len(message) > TelegramPlatform.MAX_MESSAGE_LENGTH:
            raise ValueError(
                "Telegram message cannot exceed "
                f"{TelegramPlatform.MAX_MESSAGE_LENGTH} characters."
            )

    @staticmethod
    def _validate_caption(message: str) -> None:
        """
        Validate image caption.
        """

        if not isinstance(message, str):
            raise ValueError(
                "Telegram caption must be a string."
            )

        if not message.strip():
            raise ValueError(
                "Telegram caption cannot be empty."
            )

        if len(message) > TelegramPlatform.MAX_CAPTION_LENGTH:
            raise ValueError(
                "Telegram image caption cannot exceed "
                f"{TelegramPlatform.MAX_CAPTION_LENGTH} characters."
            )

    # --------------------------------------------------
    # Media URL validation
    # --------------------------------------------------

    @staticmethod
    def _validate_media_url(media_url: str) -> None:
        """
        Validate publicly accessible HTTPS media URL.

        Rejects:
        - Non-HTTPS URLs
        - Invalid URLs
        - URLs containing credentials
        - URLs containing fragments
        - Localhost hostnames
        - Private/reserved IP addresses
        - Non-standard HTTPS ports
        """

        if not isinstance(media_url, str):
            raise ValueError(
                "Telegram media URL must be a string."
            )

        if not media_url:
            raise ValueError(
                "Telegram media URL cannot be empty."
            )

        if any(character.isspace() for character in media_url):
            raise ValueError(
                "Telegram media URL contains invalid whitespace."
            )

        try:
            parsed_url = urlsplit(media_url)

            hostname = parsed_url.hostname
            port = parsed_url.port

        except ValueError:
            raise ValueError(
                "Telegram media URL must be a valid HTTPS URL."
            ) from None

        if (
            parsed_url.scheme.lower() != "https"
            or not parsed_url.netloc
            or not hostname
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.fragment
        ):
            raise ValueError(
                "Telegram media URL must be a valid "
                "public HTTPS URL."
            )

        # Only standard HTTPS port is allowed.
        if port not in (None, 443):
            raise ValueError(
                "Telegram media URL must use standard HTTPS port."
            )

        # Reject localhost and local development hostnames.
        normalized_hostname = hostname.lower().rstrip(".")

        if (
            normalized_hostname == "localhost"
            or normalized_hostname.endswith(".localhost")
        ):
            raise ValueError(
                "Telegram media URL must use a public hostname."
            )

        # Validate IP addresses.
        try:
            parsed_ip = ipaddress.ip_address(hostname)

        except ValueError:
            parsed_ip = None

        if parsed_ip is not None and not parsed_ip.is_global:
            raise ValueError(
                "Telegram media URL cannot reference "
                "a private or reserved IP address."
            )

    # --------------------------------------------------
    # Telegram API request
    # --------------------------------------------------

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        payload: Dict[str, Any],
        operation: str,
    ) -> Dict[str, Any]:
        """
        Perform Telegram API request and validate response.
        """

        endpoint = f"{self.base_url}/{method}"

        try:
            response = await client.post(
                endpoint,
                json=payload,
            )

        except httpx.TimeoutException:
            raise RuntimeError(
                f"Telegram API request timed out during {operation}."
            ) from None

        except httpx.RequestError:
            raise RuntimeError(
                f"Telegram API connection failed during {operation}."
            ) from None

        try:
            response_data = response.json()

        except ValueError:
            raise RuntimeError(
                "Telegram returned an invalid JSON response."
            ) from None

        if not isinstance(response_data, dict):
            raise RuntimeError(
                "Telegram returned an unexpected response format."
            )

        if response.is_error or not response_data.get("ok"):
            error_code = response_data.get(
                "error_code",
                response.status_code,
            )

            description = response_data.get(
                "description",
                "Unknown Telegram API error.",
            )

            raise RuntimeError(
                f"Telegram API error ({error_code}): "
                f"{description}"
            )

        result = response_data.get("result")

        if not isinstance(result, dict):
            raise RuntimeError(
                "Telegram API returned an invalid result."
            )

        return result

    # --------------------------------------------------
    # Channel username / post URL
    # --------------------------------------------------

    def _get_channel_username(self) -> Optional[str]:
        """
        Extract public username from instance channel configuration.

        Supported configuration:
            @channelusername

        Numeric private channel IDs cannot generate public links.
        """

        channel_id = self.channel_id

        if not channel_id:
            return None

        channel_id = channel_id.strip()

        if channel_id.startswith("@"):
            username = channel_id[1:].strip()

            if username:
                return username

        return None

    def _build_post_url(
        self,
        message_id: int,
    ) -> str:
        """
        Generate public Telegram channel message URL.
        """

        username = self._get_channel_username()

        if not username:
            raise RuntimeError(
                "Telegram channel username is not configured "
                "for generating public post URLs."
            )

        return (
            f"https://t.me/{username}/{message_id}"
        )

    def _build_result(
        self,
        message_id: int,
    ) -> Dict[str, Any]:
        """
        Build standardized platform publishing result.
        """

        posted_url = self._build_post_url(message_id)

        published_at = datetime.now(timezone.utc)

        return {
            "posted_url": posteded_url if False else posted_url,
            "public_access": True,
            "date": published_at.date(),
            "time": published_at.time().replace(
                tzinfo=None
            ),
        }

    # --------------------------------------------------
    # Text publishing
    # --------------------------------------------------

    async def publish(
        self,
        message: str,
    ) -> Dict[str, Any]:
        """
        Publish a text message to Telegram channel.
        """

        self._validate_message(message)

        payload = {
            "chat_id": self.channel_id,
            "text": message,
            "disable_web_page_preview": False,
        }

        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:

            result = await self._request(
                client=client,
                method="sendMessage",
                payload=payload,
                operation="publishing text message",
            )

        message_id = result.get("message_id")

        if (
            isinstance(message_id, bool)
            or not isinstance(message_id, int)
        ):
            raise RuntimeError(
                "Telegram did not return a valid message ID."
            )

        return self._build_result(message_id)

    # --------------------------------------------------
    # Image publishing
    # --------------------------------------------------

    async def publish_media(
        self,
        message: str,
        media_url: str,
    ) -> Dict[str, Any]:
        """
        Publish image with caption to Telegram channel.

        Telegram fetches the image using its publicly
        accessible HTTPS URL.
        """

        self._validate_caption(message)
        self._validate_media_url(media_url)

        payload = {
            "chat_id": self.channel_id,
            "photo": media_url,
            "caption": message,
        }

        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:

            result = await self._request(
                client=client,
                method="sendPhoto",
                payload=payload,
                operation="publishing image",
            )

        message_id = result.get("message_id")

        if (
            isinstance(message_id, bool)
            or not isinstance(message_id, int)
        ):
            raise RuntimeError(
                "Telegram did not return a valid message ID."
            )

        return self._build_result(message_id)