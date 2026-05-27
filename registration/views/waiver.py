"""Waiver PDF generation and S3 upload helpers."""

import logging
from io import BytesIO

from django.conf import settings
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def generate_waiver_pdf(context: dict) -> bytes:
    """
    Render the waiver HTML template with the given context and convert it to
    a PDF using Gotenberg.

    ``context`` must contain:
        name, address, city, state, zipcode, date, signature_data
        ec_name, ec_relationship, ec_phone  (may be empty strings)

    Returns the raw PDF bytes.
    Raises if Gotenberg is not configured or the render fails.
    """
    from gotenberg_client import GotenbergClient
    from gotenberg_client.options import PageOrientation, PageSize

    html = render_to_string("registration/waiver.html", context)

    gotenberg_host = getattr(settings, "GOTENBERG_HOST", None)
    if not gotenberg_host:
        raise RuntimeError("GOTENBERG_HOST is not configured")

    with GotenbergClient(gotenberg_host) as client:
        with client.chromium.html_to_pdf() as route:
            response = (
                route.size(PageSize("8.5in", "11in"))
                .orient(PageOrientation(PageOrientation.Portrait))
                .string_resource(html, "index.html")
                .run()
            )
            return response.content


def upload_waiver_to_s3(pdf_bytes: bytes, order_reference: str) -> str:
    """
    Upload ``pdf_bytes`` to the configured S3 bucket under a key derived from
    ``order_reference``.

    Returns the public-readable HTTPS URL (or a private S3 URI if the bucket
    is not public – callers treat it as an opaque URL for display/linking).

    Raises on any boto3 / configuration error.
    """
    import boto3

    bucket = getattr(settings, "WAIVER_S3_BUCKET", None)
    if not bucket:
        raise RuntimeError("WAIVER_S3_BUCKET is not configured")

    region = getattr(settings, "WAIVER_S3_REGION", "us-east-1")
    prefix = getattr(settings, "WAIVER_S3_PREFIX", "waivers/")

    key = f"{prefix}{order_reference}.pdf"

    s3 = boto3.client("s3", region_name=region)
    s3.upload_fileobj(
        BytesIO(pdf_bytes),
        bucket,
        key,
        ExtraArgs={"ContentType": "application/pdf"},
    )

    url = f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
    logger.info("Uploaded waiver PDF to %s", url)
    return url
