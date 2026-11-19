import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Optional


class PostingRepository:
    """Persistent storage for duplicate prevention and posting history."""

    def __init__(self, database_path: str = "data/posting_history.db"):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=30,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize_database(self) -> None:
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS posting_requests (
                    fingerprint TEXT PRIMARY KEY,
                    message TEXT NOT NULL,
                    media_url TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            connection.execute("""
                CREATE TABLE IF NOT EXISTS platform_results (
                    fingerprint TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    status TEXT NOT NULL,
                    posted_url TEXT,
                    error TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (fingerprint, platform),
                    FOREIGN KEY (fingerprint)
                        REFERENCES posting_requests(fingerprint)
                )
            """)

    @staticmethod
    def create_fingerprint(
        message: str,
        media_url: Optional[str] = None,
    ) -> str:
        payload = {
            "message": message.strip(),
            "media_url": str(media_url).strip() if media_url else None,
        }

        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        )

        return hashlib.sha256(
            serialized.encode("utf-8")
        ).hexdigest()

    def create_request(
        self,
        fingerprint: str,
        message: str,
        media_url: Optional[str],
    ) -> bool:
        connection = self._connect()

        try:
            connection.execute("BEGIN IMMEDIATE")

            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO posting_requests (
                    fingerprint,
                    message,
                    media_url,
                    status
                )
                VALUES (?, ?, ?, 'processing')
                """,
                (fingerprint, message, media_url),
            )

            created = cursor.rowcount == 1
            connection.commit()

            return created

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    def get_request(self, fingerprint: str):
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM posting_requests
                WHERE fingerprint = ?
                """,
                (fingerprint,),
            ).fetchone()

            return dict(row) if row else None

    def claim_platform(
        self,
        fingerprint: str,
        platform: str,
    ) -> bool:
        """
        Atomically claim a platform for publishing.

        New platforms can be claimed once.
        Failed platforms can be claimed again.
        Successful or processing platforms cannot be claimed again.
        """

        connection = self._connect()

        try:
            connection.execute("BEGIN IMMEDIATE")

            cursor = connection.execute(
                """
                INSERT INTO platform_results (
                    fingerprint,
                    platform,
                    status,
                    posted_url,
                    error
                )
                VALUES (?, ?, 'processing', NULL, NULL)
                ON CONFLICT(fingerprint, platform)
                DO UPDATE SET
                    status = 'processing',
                    posted_url = NULL,
                    error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE platform_results.status = 'failed'
                """,
                (fingerprint, platform),
            )

            claimed = cursor.rowcount == 1

            connection.commit()

            return claimed

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    def save_platform_result(
        self,
        fingerprint: str,
        platform: str,
        status: str,
        posted_url: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO platform_results (
                    fingerprint,
                    platform,
                    status,
                    posted_url,
                    error
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(fingerprint, platform)
                DO UPDATE SET
                    status = excluded.status,
                    posted_url = excluded.posted_url,
                    error = excluded.error,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    fingerprint,
                    platform,
                    status,
                    posted_url,
                    error,
                ),
            )

    def get_platform_results(self, fingerprint: str):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM platform_results
                WHERE fingerprint = ?
                """,
                (fingerprint,),
            ).fetchall()

            return {
                row["platform"]: dict(row)
                for row in rows
            }

    def update_request_status(
        self,
        fingerprint: str,
        status: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE posting_requests
                SET status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE fingerprint = ?
                """,
                (status, fingerprint),
            )