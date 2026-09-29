import pytest
from unittest.mock import AsyncMock

from app.agent import (
    get_weather,
    get_current_time,
    list_destinations,
    get_destination_details,
    save_itinerary,
    convert_currency,
    lookup_location,
    generate_destination_image,
    generate_destination_video,
)

def test_get_weather():
    tokyo = get_weather("Tokyo")
    assert "Tokyo" in tokyo
    assert "Sunny" in tokyo

    sf = get_weather("San Francisco")
    assert "San Francisco" in sf

def test_get_current_time():
    sf_time = get_current_time("San Francisco")
    assert "America/Los_Angeles" in sf_time

    tokyo_time = get_current_time("Tokyo")
    assert "Asia/Tokyo" in tokyo_time

def test_firestore_list_destinations():
    destinations = list_destinations()
    assert len(destinations) >= 5
    names = [d["name"] for d in destinations]
    assert any("Kyoto" in name for name in names)

def test_firestore_get_destination_details():
    kyoto = get_destination_details("kyoto-japan")
    assert "name" in kyoto
    assert "Kyoto" in kyoto["name"]
    assert "highlights" in kyoto

def test_firestore_save_itinerary():
    res = save_itinerary(
        destination="Kyoto, Japan",
        duration_days=3,
        planned_activities=["Visit Fushimi Inari", "Tea ceremony in Gion"],
        estimated_cost_usd=1200.0,
        notes="Solo travel test"
    )
    assert "saved successfully" in res

def test_convert_currency():
    res = convert_currency(100.0, "USD", "EUR")
    assert "converted_amount" in res
    assert res["from_currency"] == "USD"
    assert res["to_currency"] == "EUR"
    assert res["converted_amount"] > 0

def test_lookup_location():
    res = lookup_location("Colosseum Rome")
    assert "latitude" in res
    assert "longitude" in res
    assert "osm_map_url" in res
    assert abs(res["latitude"] - 41.89) < 0.1

@pytest.mark.asyncio
async def test_generate_destination_image():
    mock_context = AsyncMock()
    mock_context.save_artifact = AsyncMock()
    res = await generate_destination_image("Scenic Kyoto temple in autumn", tool_context=mock_context)
    assert res.get("status") == "success"
    assert "public_image_url" in res
    assert "wanderlust-travel-media-qwiklabs-gcp-04-01d87701e441" in res["public_image_url"]
    assert mock_context.save_artifact.called


@pytest.mark.asyncio
async def test_generate_destination_video():
    mock_context = AsyncMock()
    mock_context.save_artifact = AsyncMock()
    res = await generate_destination_video(
        "A 3-second drone video flying over a tropical beach at sunset",
        tool_context=mock_context,
    )
    assert res.get("status") == "success", f"Video generation failed: {res}"
    assert "public_video_url" in res
    assert "wanderlust-travel-media-qwiklabs-gcp-04-01d87701e441" in res["public_video_url"]
    assert res["public_video_url"].endswith(".mp4")
    assert mock_context.save_artifact.called





