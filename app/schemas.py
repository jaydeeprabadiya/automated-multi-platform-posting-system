import re
from datetime import date as Date
from datetime import time as Time
from enum import Enum
from typing import ClassVar, List, Optional
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    TypeAdapter,
    ValidationError,
    field_validator,
)


class MessageRequest(BaseModel):
    """
    Request schema for multi-platform message publishing.
    """

    URL_PATTERN: ClassVar[re.Pattern] = re.compile(
        r"https?://[^\s<>\"']*",
        re.IGNORECASE,
    )

    URL_ADAPTER: ClassVar[TypeAdapter] = TypeAdapter(HttpUrl)

    message: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Message containing exactly one valid CTA URL.",
        examples=[
            "Grow your business with us https://example.com"
        ],
    )

    media_url: Optional[HttpUrl] = Field(
        default=None,
        description="Publicly accessible HTTPS image URL for Instagram.",
    )

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        """
        Validate message length and ensure exactly one valid CTA URL.
        """

        urls = cls.URL_PATTERN.findall(value)

        if len(urls) != 1:
            raise ValueError(
                "Message must contain exactly one CTA link."
            )

        url = urls[0].rstrip(".,!?;:)")

        try:
            validated_url = cls.URL_ADAPTER.validate_python(url)
            parsed_url = urlsplit(str(validated_url))

        except (ValidationError, ValueError):
            raise ValueError("Invalid URL provided.") from None

        if (
            parsed_url.username is not None
            or parsed_url.password is not None
        ):
            raise ValueError(
                "URLs containing credentials are not allowed."
            )

        return value

    @field_validator("media_url")
    @classmethod
    def validate_media_url(
        cls,
        value: Optional[HttpUrl],
    ) -> Optional[HttpUrl]:
        """
        Validate that media URLs use HTTPS without credentials.
        """

        if value is None:
            return value

        parsed_url = urlsplit(str(value))

        if parsed_url.scheme != "https":
            raise ValueError(
                "Media URL must use HTTPS."
            )

        if (
            parsed_url.username is not None
            or parsed_url.password is not None
        ):
            raise ValueError(
                "Media URLs containing credentials are not allowed."
            )

        return value


class PostingStatus(str, Enum):
    """
    Publishing status for an individual platform.
    """

    SUCCESS = "success"
    FAILED = "failed"


class PlatformResult(BaseModel):
    """
    Individual platform publishing result.
    """

    platform: str = Field(
        ...,
        min_length=1,
        description="Name of the social media platform.",
    )

    status: PostingStatus

    posted_url: Optional[HttpUrl] = None

    public_access: Optional[bool] = None

    date: Optional[Date] = None

    time: Optional[Time] = None

    error: Optional[str] = None


class PostingResponse(BaseModel):
    """
    Standardized response for multi-platform publishing.
    """

    success: bool

    results: List[PlatformResult] = Field(
        default_factory=list
    )