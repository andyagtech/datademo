"""
AWS S3 storage adapter.

Maps keys to S3 objects under a bucket/prefix.
DuckDB URIs are s3:// paths — DuckDB reads these natively via its httpfs extension.

Requires:
  - boto3 (included in Lambda runtime)
  - DuckDB httpfs extension (bundled in recent versions)
  - Lambda execution role with s3:GetObject, s3:PutObject, s3:ListBucket
"""

from __future__ import annotations

import fnmatch
import logging
from io import BytesIO

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class S3Storage:
    """StorageAdapter implementation backed by AWS S3."""

    def __init__(self, bucket: str, prefix: str = "") -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.s3 = boto3.client("s3")

    def _full_key(self, key: str) -> str:
        """Build the full S3 key from prefix + relative key."""
        if self.prefix:
            return f"{self.prefix}/{key}"
        return key

    def read_bytes(self, key: str) -> bytes:
        """Read an S3 object's contents as bytes."""
        resp = self.s3.get_object(Bucket=self.bucket, Key=self._full_key(key))
        return resp["Body"].read()

    def write_bytes(self, key: str, data: bytes) -> str:
        """Write bytes to an S3 object. Returns the s3:// URI."""
        full_key = self._full_key(key)
        self.s3.put_object(Bucket=self.bucket, Key=full_key, Body=data)
        return f"s3://{self.bucket}/{full_key}"

    def read_text(self, key: str, encoding: str = "utf-8") -> str:
        """Read an S3 object's contents as a string."""
        return self.read_bytes(key).decode(encoding)

    def write_text(self, key: str, data: str, encoding: str = "utf-8") -> str:
        """Write a string to an S3 object. Returns the s3:// URI."""
        return self.write_bytes(key, data.encode(encoding))

    def list_files(self, prefix: str, pattern: str = "*") -> list[str]:
        """List S3 objects under a prefix matching an optional glob pattern."""
        full_prefix = self._full_key(prefix)
        if not full_prefix.endswith("/"):
            full_prefix += "/"

        results: list[str] = []
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=full_prefix):
            for obj in page.get("Contents", []):
                obj_key = obj["Key"]
                # Get the filename portion
                filename = obj_key.rsplit("/", 1)[-1] if "/" in obj_key else obj_key
                if fnmatch.fnmatch(filename, pattern):
                    # Return key relative to our adapter prefix
                    if self.prefix and obj_key.startswith(self.prefix + "/"):
                        results.append(obj_key[len(self.prefix) + 1 :])
                    else:
                        results.append(obj_key)
        return sorted(results)

    def file_exists(self, key: str) -> bool:
        """Check if an S3 object exists."""
        try:
            self.s3.head_object(Bucket=self.bucket, Key=self._full_key(key))
            return True
        except ClientError:
            return False

    def file_size(self, key: str) -> int:
        """Return S3 object size in bytes."""
        resp = self.s3.head_object(Bucket=self.bucket, Key=self._full_key(key))
        return resp["ContentLength"]

    def get_uri(self, key: str) -> str:
        """Return s3:// URI — DuckDB reads these via httpfs extension."""
        return f"s3://{self.bucket}/{self._full_key(key)}"

    def generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Generate a presigned download URL for a report or export file."""
        return self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._full_key(key)},
            ExpiresIn=expires_in,
        )
