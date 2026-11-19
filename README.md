Automated Multi-Platform Posting System

A FastAPI-based application that enables automated content publishing across multiple social media platforms through a unified API.

Features

* Publish content across multiple platforms through a single API request.
* Facebook integration.
* Instagram integration.
* Bluesky integration.
* Mastodon integration.
* Telegram integration.
* Optional media URL support.
* Message and URL validation.
* Persistent posting history using SQLite.
* Duplicate request detection using content fingerprints.
* Per-platform publishing status tracking.
* Retry support for failed platforms.
* Successful platform results are preserved during retries.
* Concurrent duplicate publishing protection.

Technology Stack

* Python
* FastAPI
* Pydantic
* SQLite
* HTTPX
* Pytest

Project Structure

automated-posting/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── schemas.py
│   ├── platforms/
│   │   ├── facebook.py
│   │   ├── instagram.py
│   │   ├── bluesky.py
│   │   ├── mastodon.py
│   │   └── telegram.py
│   └── services/
│       ├── posting_service.py
│       └── posting_repository.py
├── tests/
├── .env
├── .env.example
├── requirements.txt
└── README.md

Installation

1. Clone the repository

git clone <repository-url>
cd automated-posting

2. Create a virtual environment

python -m venv venv

3. Activate the environment

macOS/Linux:

source venv/bin/activate

4. Install dependencies

pip install -r requirements.txt

5. Configure environment variables

Create your .env file using .env.example as a reference.

Add the required credentials and configuration for the social media platforms you intend to use.

Never commit your real API tokens, passwords, or secrets.

Running the Application

Start the FastAPI server:

uvicorn app.main:app --reload

The API will be available at:

http://127.0.0.1:8000

API Documentation

Interactive API documentation is available at:

http://127.0.0.1:8000/docs

Alternative documentation:

http://127.0.0.1:8000/redoc

API Endpoints

Health Check

GET /

Checks whether the API is running.

Example response:

{
  "success": true,
  "message": "Automated Posting API is running"
}

Publish Content

POST /posting

Publishes a message across configured platforms.

Example request:

{
  "message": "Discover our latest updates https://example.com",
  "media_url": "https://example.com/image.jpg"
}

media_url is optional.

The message must contain exactly one CTA URL.

Supported Platforms

* Facebook
* Instagram
* Bluesky
* Mastodon
* Telegram

Testing

Run the complete test suite:

python -m pytest -q

The current test suite contains 167 passing tests.

Tests cover schemas, platform behavior, posting service logic, repository persistence, duplicate protection, and retry scenarios.

Posting Behavior

The system maintains publishing history to prevent unnecessary duplicate posts.

* Previously successful platforms are skipped on subsequent identical requests.
* Failed platforms can be retried.
* Successful platform results are preserved during retry attempts.
* Different content generates a separate posting request.
* Platform publishing results are tracked individually.

Configuration

Configuration is managed through environment variables and the .env file.

Platform credentials are required for the corresponding integrations.

Disclaimer

Actual publishing depends on valid platform credentials, API permissions, platform availability, rate limits, and platform-specific restrictions.