from abc import ABC, abstractmethod
from typing import Any, Dict


class BasePlatform(ABC):
    """
    Abstract base class for all social media platform integrations.
    """

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the platform name."""
        raise NotImplementedError

    @abstractmethod
    async def publish(self, message: str) -> Dict[str, Any]:
        """
        Publish a text-based message to the target platform.

        Args:
            message: Content to publish.

        Returns:
            Dictionary containing the publishing result.
        """
        raise NotImplementedError


class MediaPlatform(BasePlatform):
    """
    Abstract interface for platforms supporting media publishing.
    """

    @abstractmethod
    async def publish_media(
        self,
        message: str,
        media_url: str,
    ) -> Dict[str, Any]:
        """
        Publish media with a message to the target platform.

        Args:
            message: Caption or accompanying text.
            media_url: Publicly accessible media URL.

        Returns:
            Dictionary containing the publishing result.
        """
        raise NotImplementedError