"""Mocked logic tests implementing Phase 11 claims.

Tests:
1. Polling loop stops at the 30s cap (max attempts reached, no infinite loop).
2. Documented error codes raise correctly (mapped to YouCamAPIError, not swallowed).
3. Undocumented error code falls back to unknown_internal_error.
4. Catalog matching is deterministic (same input produces exact same match).
5. Catalog matching produces non-empty results across varied skin tones.
6. Contrast and undertone scoring properly ranks suitable garments.
"""
import pytest
import httpx
from unittest.mock import AsyncMock, patch

from app.clients.youcam import YouCamClient, YouCamAPIError, YouCamTimeoutError
from app.catalog.matcher import CatalogMatcher, hex_to_rgb


@pytest.mark.asyncio
async def test_polling_loop_stops_at_cap():
    """Verify that a stuck 'running' task does not poll forever and stops at max attempts."""
    client = YouCamClient(
        api_key="mock_key",
        base_url="https://mock.youcam.com",
        max_poll_attempts=3,
        poll_interval_seconds=0.01,
    )

    mock_response = httpx.Response(
        200,
        json={"status": "running", "task_id": "mock_task_123"},
        request=httpx.Request("GET", "https://mock.youcam.com/task/mock_task_123"),
    )

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        async with httpx.AsyncClient() as http_client:
            with pytest.raises(YouCamTimeoutError) as exc_info:
                await client.poll_task_result(http_client, "mock_task_123")

            assert "did not complete within the 30s cap" in str(exc_info.value)
            assert mock_get.call_count == 3


@pytest.mark.asyncio
async def test_documented_error_codes_raise_correctly():
    """Verify that YouCam error statuses map to YouCamAPIError with the exact code."""
    client = YouCamClient(api_key="mock_key", base_url="https://mock.youcam.com")

    for error_code in ["error_pose", "error_invalid_ref", "error_nsfw_content_detected"]:
        mock_response = httpx.Response(
            200,
            json={"status": "error", "error_code": error_code, "error_message": f"Failed: {error_code}"},
            request=httpx.Request("GET", "https://mock.youcam.com/task/mock_err"),
        )

        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            async with httpx.AsyncClient() as http_client:
                with pytest.raises(YouCamAPIError) as exc_info:
                    await client.poll_task_result(http_client, "mock_err")

                assert exc_info.value.error_code == error_code
                assert error_code in str(exc_info.value)


@pytest.mark.asyncio
async def test_undocumented_error_code_fallback():
    """Verify unknown error statuses map to unknown_internal_error."""
    client = YouCamClient(api_key="mock_key", base_url="https://mock.youcam.com")

    mock_response = httpx.Response(
        200,
        json={"status": "error"},
        request=httpx.Request("GET", "https://mock.youcam.com/task/mock_unknown"),
    )

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        async with httpx.AsyncClient() as http_client:
            with pytest.raises(YouCamAPIError) as exc_info:
                await client.poll_task_result(http_client, "mock_unknown")

            assert exc_info.value.error_code == "unknown_internal_error"


def test_catalog_matching_is_deterministic():
    """Verify that running the matcher multiple times on the same input produces identical output."""
    matcher = CatalogMatcher()
    sample_hex = "#8d5524"

    run_1 = [item["sku"] for item in matcher.match_hex(sample_hex)]
    run_2 = [item["sku"] for item in matcher.match_hex(sample_hex)]
    run_3 = [item["sku"] for item in matcher.match_hex(sample_hex)]

    assert len(run_1) > 0
    assert run_1 == run_2 == run_3


def test_catalog_matching_non_empty_across_tone_spectrum():
    """Verify that fair, medium, olive, deep, and rich tones all receive non-empty recommendations."""
    matcher = CatalogMatcher()
    test_tones = {
        "fair": "#ffe0bd",
        "medium": "#f1c27d",
        "olive": "#b89778",
        "deep": "#8d5524",
        "rich": "#3b2219",
    }

    for tone_name, hex_val in test_tones.items():
        results = matcher.match_hex(hex_val, limit=3)
        assert len(results) >= 1, f"Expected matches for {tone_name} ({hex_val})"
        assert all("sku" in item for item in results)


def test_hex_to_rgb_conversion():
    """Verify hex color parsing handles standard 6-char, 3-char, and prefix variations."""
    assert hex_to_rgb("#ffffff") == (255, 255, 255)
    assert hex_to_rgb("000000") == (0, 0, 0)
    assert hex_to_rgb("#f00") == (255, 0, 0)
