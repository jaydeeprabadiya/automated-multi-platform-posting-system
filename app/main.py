from fastapi import FastAPI

from app.platforms.facebook import FacebookPlatform
from app.platforms.instagram import InstagramPlatform
from app.platforms.bluesky import BlueskyPlatform
from app.platforms.mastodon import MastodonPlatform
from app.platforms.telegram import TelegramPlatform

from app.schemas import MessageRequest, PostingResponse
from app.services.posting_service import PostingService


app = FastAPI(
    title="Automated Multi-Platform Posting System",
    description="Automatically publish messages across multiple platforms",
    version="1.0.0",
)


# Initialize configured platforms
posting_service = PostingService(
    platforms=[
        FacebookPlatform(),
        InstagramPlatform(),
        BlueskyPlatform(),
        MastodonPlatform(),
        TelegramPlatform(),
    ]
)


@app.get("/")
async def root():
    """
    Health check endpoint.
    """

    return {
        "success": True,
        "message": "Automated Posting API is running",
    }


@app.post(
    "/posting",
    response_model=PostingResponse,
)
async def create_post(
    request: MessageRequest,
) -> PostingResponse:
    """
    Publish content across all configured platforms.
    """

    return await posting_service.publish_to_all(
        message=request.message,
        media_url=(
            str(request.media_url)
            if request.media_url
            else None
        ),
    )