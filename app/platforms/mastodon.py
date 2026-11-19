import asyncio
import ipaddress
import socket
import uuid

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

import aiohttp
import httpx

from app.config import get_settings
from app.platforms.base import MediaPlatform


class PublicDNSResolver(aiohttp.abc.AbstractResolver):
    """
    Resolve hostnames and reject non-public IP addresses.

    The validated IP addresses are returned directly to aiohttp's
    connector, preventing a second DNS resolution during connection.
    """

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: int = socket.AF_UNSPEC,
    ) -> List[Dict[str, Any]]:

        try:
            loop = asyncio.get_running_loop()

            records = await loop.getaddrinfo(
                host,
                port,
                family=family,
                type=socket.SOCK_STREAM,
            )

        except (OSError, socket.gaierror):
            raise RuntimeError(
                "Unable to resolve image hostname."
            ) from None

        if not records:
            raise RuntimeError(
                "Image hostname did not resolve to an IP address."
            )

        validated_records = []
        seen_addresses = set()

        for record in records:
            address_family, socktype, proto, flags, sockaddr = record

            ip_address = sockaddr[0]

            try:
                parsed_ip = ipaddress.ip_address(ip_address)
            except ValueError:
                raise RuntimeError(
                    "DNS returned an invalid IP address."
                ) from None

            if not parsed_ip.is_global:
                raise ValueError(
                    "Image URL resolves to a non-public IP address."
                )

            normalized_ip = str(parsed_ip)

            if normalized_ip in seen_addresses:
                continue

            seen_addresses.add(normalized_ip)

            validated_records.append({
                "hostname": host,
                "host": normalized_ip,
                "port": port,
                "family": address_family,
                "proto": proto,
                "flags": flags,
            })

        if not validated_records:
            raise RuntimeError(
                "No valid public IP addresses were found."
            )

        return validated_records

    async def close(self) -> None:
        return None


class MastodonPlatform(MediaPlatform):
    """
    Mastodon publishing integration.

    Supports:
    - Public text posts.
    - Public image posts.
    - Public HTTPS image downloads.
    - DNS-level SSRF protection.
    - DNS rebinding protection through validated IP resolution.
    - Redirect protection.
    - Environment proxy bypass.
    - Image signature validation.
    - Media processing polling.
    """

    MAX_MESSAGE_LENGTH = 500
    MAX_MEDIA_SIZE = 8 * 1024 * 1024

    ALLOWED_IMAGE_TYPES = {
        "image/jpeg": "image.jpg",
        "image/png": "image.png",
        "image/gif": "image.gif",
        "image/webp": "image.webp",
    }

    IMAGE_SIGNATURES = {
        "image/jpeg": (
            lambda data: data.startswith(b"\xff\xd8\xff")
        ),
        "image/png": (
            lambda data: data.startswith(
                b"\x89PNG\r\n\x1a\n"
            )
        ),
        "image/gif": (
            lambda data: data.startswith(
                (b"GIF87a", b"GIF89a")
            )
        ),
        "image/webp": (
            lambda data: (
                len(data) >= 12
                and data.startswith(b"RIFF")
                and data[8:12] == b"WEBP"
            )
        ),
    }

    POLL_INTERVAL_SECONDS = 2
    MAX_POLL_ATTEMPTS = 15

    def __init__(self) -> None:
        self.settings = get_settings()

        self.base_url = (
            self.settings.mastodon_base_url.rstrip("/")
        )

        self.access_token: Optional[str] = None

        if self.settings.mastodon_access_token:
            self.access_token = (
                self.settings.mastodon_access_token.get_secret_value()
            )

        self.timeout = self.settings.http_timeout

        parsed_base_url = urlsplit(self.base_url)

        if (
            parsed_base_url.scheme != "https"
            or not parsed_base_url.netloc
            or parsed_base_url.username is not None
            or parsed_base_url.password is not None
            or parsed_base_url.query
            or parsed_base_url.fragment
            or parsed_base_url.path not in ("", "/")
        ):
            raise ValueError(
                "Mastodon base URL must be a valid HTTPS URL."
            )

        if not self.access_token:
            raise ValueError(
                "Mastodon Access Token is not configured."
            )

    @property
    def platform_name(self) -> str:
        return "Mastodon"

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
        }

    @classmethod
    def _validate_message(cls, message: str) -> None:
        if not isinstance(message, str):
            raise ValueError(
                "Mastodon message must be a string."
            )

        if not message.strip():
            raise ValueError(
                "Mastodon message cannot be empty."
            )

        if len(message) > cls.MAX_MESSAGE_LENGTH:
            raise ValueError(
                f"Mastodon message cannot exceed "
                f"{cls.MAX_MESSAGE_LENGTH} characters."
            )

    @staticmethod
    def _validate_media_url(media_url: str) -> None:
        if not isinstance(media_url, str):
            raise ValueError(
                "Mastodon media URL must be a string."
            )

        try:
            parsed_url = urlsplit(media_url)

            hostname = parsed_url.hostname
            port = parsed_url.port

        except ValueError:
            raise ValueError(
                "Mastodon media URL must be a valid public HTTPS URL."
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
                "Mastodon media URL must be a valid public HTTPS URL."
            )

        if port not in (None, 443):
            raise ValueError(
                "Mastodon media URL must use the standard HTTPS port."
            )

        if any(
            character.isspace()
            for character in media_url
        ):
            raise ValueError(
                "Mastodon media URL contains invalid whitespace."
            )

        try:
            literal_ip = ipaddress.ip_address(hostname)

        except ValueError:
            literal_ip = None

        if literal_ip is not None and not literal_ip.is_global:
            raise ValueError(
                "Image URL cannot reference a private or reserved IP address."
            )

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        method: str,
        endpoint: str,
        operation: str,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:

        request_headers = self._get_headers()

        if headers:
            request_headers.update(headers)

        try:
            response = await client.request(
                method=method,
                url=endpoint,
                headers=request_headers,
                data=data,
                files=files,
            )

        except httpx.TimeoutException:
            raise RuntimeError(
                f"Mastodon API request timed out during {operation}."
            ) from None

        except httpx.RequestError:
            raise RuntimeError(
                f"Mastodon API connection failed during {operation}."
            ) from None

        try:
            response_data = response.json()

        except ValueError:
            raise RuntimeError(
                f"Mastodon returned an invalid response during {operation}."
            ) from None

        if not isinstance(response_data, dict):
            raise RuntimeError(
                f"Mastodon returned an unexpected response during {operation}."
            )

        if response.is_error:
            error_message = response_data.get(
                "error",
                "Unknown Mastodon API error.",
            )

            raise RuntimeError(
                f"Mastodon API Error ({response.status_code}): "
                f"{error_message}"
            )

        return response_data

    @staticmethod
    def _validate_image_signature(
        image_data: bytes,
        content_type: str,
    ) -> None:

        signature_validator = (
            MastodonPlatform.IMAGE_SIGNATURES.get(content_type)
        )

        if signature_validator is None:
            raise ValueError(
                f"Unsupported image content type: {content_type}."
            )

        if not signature_validator(image_data):
            raise ValueError(
                "Image file signature does not match its content type."
            )

    async def _download_image(
        self,
        media_url: str,
    ) -> tuple:

        self._validate_media_url(media_url)

        resolver = PublicDNSResolver()

        connector = aiohttp.TCPConnector(
            resolver=resolver,
            use_dns_cache=False,
            ssl=True,
        )

        timeout = aiohttp.ClientTimeout(
            total=self.timeout,
        )

        try:
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                trust_env=False,
            ) as session:

                async with session.get(
                    media_url,
                    allow_redirects=False,
                ) as response:

                    if 300 <= response.status < 400:
                        raise RuntimeError(
                            "Image URL redirects are not supported."
                        )

                    if response.status != 200:
                        raise RuntimeError(
                            "Unable to download image. "
                            f"HTTP status: {response.status}."
                        )

                    content_type = (
                        response.headers.get(
                            "content-type",
                            "",
                        )
                        .split(";")[0]
                        .strip()
                        .lower()
                    )

                    if content_type not in self.ALLOWED_IMAGE_TYPES:
                        raise ValueError(
                            "Unsupported image content type: "
                            f"{content_type or 'unknown'}."
                        )

                    content_length = response.headers.get(
                        "content-length"
                    )

                    if content_length:
                        try:
                            declared_size = int(content_length)
                        except ValueError:
                            raise RuntimeError(
                                "Image server returned an invalid content length."
                            ) from None

                        if (
                            declared_size < 0
                            or declared_size > self.MAX_MEDIA_SIZE
                        ):
                            raise ValueError(
                                "Image exceeds the maximum allowed size."
                            )

                    chunks = []
                    total_size = 0

                    async for chunk in response.content.iter_chunked(
                        64 * 1024
                    ):
                        total_size += len(chunk)

                        if total_size > self.MAX_MEDIA_SIZE:
                            raise ValueError(
                                "Image exceeds the maximum allowed size."
                            )

                        chunks.append(chunk)

                    image_data = b"".join(chunks)

                    if not image_data:
                        raise ValueError(
                            "Downloaded image is empty."
                        )

                    self._validate_image_signature(
                        image_data,
                        content_type,
                    )

                    return (
                        image_data,
                        content_type,
                        self.ALLOWED_IMAGE_TYPES[content_type],
                    )

        except asyncio.TimeoutError:
            raise RuntimeError(
                "Image download timed out."
            ) from None

        except aiohttp.ClientError:
            raise RuntimeError(
                "Image download connection failed."
            ) from None

        finally:
            await resolver.close()

    async def _upload_media(
        self,
        client: httpx.AsyncClient,
        media_url: str,
    ) -> str:

        (
            image_data,
            content_type,
            filename,
        ) = await self._download_image(media_url)

        response_data = await self._request_json(
            client=client,
            method="POST",
            endpoint=f"{self.base_url}/api/v2/media",
            operation="uploading image",
            files={
                "file": (
                    filename,
                    image_data,
                    content_type,
                )
            },
        )

        media_id = response_data.get("id")

        if not media_id:
            raise RuntimeError(
                "Mastodon did not return a media attachment ID."
            )

        await self._wait_for_media(
            client=client,
            media_id=media_id,
        )

        return media_id

    async def _wait_for_media(
        self,
        client: httpx.AsyncClient,
        media_id: str,
    ) -> None:

        endpoint = (
            f"{self.base_url}/api/v1/media/{media_id}"
        )

        for attempt in range(self.MAX_POLL_ATTEMPTS):

            try:
                response = await client.get(
                    endpoint,
                    headers=self._get_headers(),
                )

            except httpx.TimeoutException:
                raise RuntimeError(
                    "Mastodon media status request timed out."
                ) from None

            except httpx.RequestError:
                raise RuntimeError(
                    "Mastodon media status connection failed."
                ) from None

            if response.status_code == 206:
                if attempt < self.MAX_POLL_ATTEMPTS - 1:
                    await asyncio.sleep(
                        self.POLL_INTERVAL_SECONDS
                    )
                    continue

                break

            try:
                response_data = response.json()

            except ValueError:
                raise RuntimeError(
                    "Mastodon returned an invalid media status response."
                ) from None

            if response.is_error:
                raise RuntimeError(
                    "Mastodon media processing check failed. "
                    f"HTTP status: {response.status_code}."
                )

            if not isinstance(response_data, dict):
                raise RuntimeError(
                    "Mastodon returned an unexpected media response."
                )

            if response_data.get("url"):
                return

            if attempt < self.MAX_POLL_ATTEMPTS - 1:
                await asyncio.sleep(
                    self.POLL_INTERVAL_SECONDS
                )

        raise TimeoutError(
            "Mastodon media processing did not finish within "
            f"{self.MAX_POLL_ATTEMPTS * self.POLL_INTERVAL_SECONDS} seconds."
        )

    async def _create_status(
        self,
        client: httpx.AsyncClient,
        message: str,
        media_id: Optional[str] = None,
    ) -> Dict[str, Any]:

        idempotency_key = str(uuid.uuid4())

        data: Dict[str, Any] = {
            "status": message,
            "visibility": "public",
        }

        if media_id:
            data["media_ids[]"] = media_id

        return await self._request_json(
            client=client,
            method="POST",
            endpoint=f"{self.base_url}/api/v1/statuses",
            operation="publishing status",
            data=data,
            headers={
                "Idempotency-Key": idempotency_key,
            },
        )

    @staticmethod
    def _build_result(
        response_data: Dict[str, Any],
    ) -> Dict[str, Any]:

        posted_url = response_data.get("url")

        if not posted_url:
            raise RuntimeError(
                "Mastodon may have published the post, "
                "but did not return its public URL."
            )

        published_at = datetime.now(timezone.utc)

        return {
            "posted_url": posted_url,
            "public_access": True,
            "date": published_at.date(),
            "time": published_at.time().replace(tzinfo=None),
        }

    async def publish(
        self,
        message: str,
    ) -> Dict[str, Any]:

        self._validate_message(message)

        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:

            response_data = await self._create_status(
                client=client,
                message=message,
            )

        return self._build_result(response_data)

    async def publish_media(
        self,
        message: str,
        media_url: str,
    ) -> Dict[str, Any]:

        self._validate_message(message)
        self._validate_media_url(media_url)

        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:

            media_id = await self._upload_media(
                client=client,
                media_url=media_url,
            )

            response_data = await self._create_status(
                client=client,
                message=message,
                media_id=media_id,
            )

        return self._build_result(response_data)