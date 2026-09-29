# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import datetime
import json
import os
import re
import urllib.parse
import urllib.request
import uuid
from zoneinfo import ZoneInfo

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google import genai
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.cloud import firestore, storage
from google.genai import types

from .a2ui_utils import a2ui_callback


MODEL = "gemini-3.6-flash"
IMAGE_MODEL = "gemini-3.1-flash-lite-image"
VIDEO_MODEL = "gemini-omni-flash-preview"

# Hardcoded project ID and GCS bucket name as requested
FIRESTORE_PROJECT_ID = "qwiklabs-gcp-04-01d87701e441"
GCS_BUCKET_NAME = "wanderlust-travel-media-qwiklabs-gcp-04-01d87701e441"


def get_firestore_client() -> firestore.Client:
    """Returns a Firestore client initialized with the hardcoded project ID."""
    return firestore.Client(project=FIRESTORE_PROJECT_ID)


def get_weather(location: str) -> str:
    """Simulates weather search for a given city or location.

    Args:
        location: The name of the city or region to get weather information for.

    Returns:
        A string with the current weather conditions, temperature, and forecast.
    """
    loc_lower = location.lower()
    if "sf" in loc_lower or "san francisco" in loc_lower:
        return "San Francisco: 62°F (17°C), Partly Cloudy, Humidity 78%, Wind 12 mph NW. Forecast: Fog clearing by noon."
    elif "tokyo" in loc_lower:
        return "Tokyo: 21°C (70°F), Clear & Pleasant, Humidity 55%, Wind 8 km/h. Forecast: Sunny throughout the day."
    elif "new york" in loc_lower or "nyc" in loc_lower:
        return "New York: 68°F (20°C), Mostly Sunny, Humidity 45%, Wind 10 mph. Forecast: Mild and clear evening."
    elif "london" in loc_lower:
        return "London: 15°C (59°F), Light Rain, Humidity 82%, Wind 15 km/h. Forecast: Scattered showers."
    elif "paris" in loc_lower:
        return "Paris: 18°C (64°F), Mild Breeze, Humidity 60%, Wind 11 km/h. Forecast: Partly cloudy."
    elif "sydney" in loc_lower:
        return "Sydney: 24°C (75°F), Warm and Sunny, Humidity 50%, Wind 14 km/h. Forecast: Great beach weather."
    else:
        return f"{location.title()}: 72°F (22°C), Clear skies, Humidity 50%, Wind 5 mph. Forecast: Fair weather."


def get_current_time(location: str) -> str:
    """Gets the current date and time for a given city or region.

    Args:
        location: The name of the city or location.

    Returns:
        A string with the current time and timezone information.
    """
    loc_lower = location.lower()
    tz_map = {
        "san francisco": "America/Los_Angeles",
        "sf": "America/Los_Angeles",
        "los angeles": "America/Los_Angeles",
        "new york": "America/New_York",
        "nyc": "America/New_York",
        "london": "Europe/London",
        "paris": "Europe/Paris",
        "tokyo": "Asia/Tokyo",
        "sydney": "Australia/Sydney",
        "singapore": "Asia/Singapore",
        "berlin": "Europe/Berlin",
    }

    tz_identifier = None
    for key, tz_name in tz_map.items():
        if key in loc_lower:
            tz_identifier = tz_name
            break

    if not tz_identifier:
        tz_identifier = "UTC"
        tz = ZoneInfo(tz_identifier)
        now = datetime.datetime.now(tz)
        return f"Current time for {location} (approximated in UTC): {now.strftime('%Y-%m-%d %H:%M:%S %Z')}"

    tz = ZoneInfo(tz_identifier)
    now = datetime.datetime.now(tz)
    return f"Current time in {location} ({tz_identifier}): {now.strftime('%Y-%m-%d %H:%M:%S %Z%z')}"



def list_destinations(category: str = "", max_budget_usd: float = 0.0) -> list[dict]:
    """Lists travel destinations from the Firestore catalog with optional filtering.

    Args:
        category: Optional category filter (e.g. 'Nature & Adventure', 'Cultural & Historical', 'Coastal & Scenic', 'Cultural & Urban').
        max_budget_usd: Optional upper budget limit in USD. If greater than 0, only destinations within budget are returned.

    Returns:
        A list of destination dictionaries.
    """
    db = get_firestore_client()
    docs = db.collection("destinations").stream()
    results = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        if category:
            cat_match = category.lower() in data.get("category", "").lower()
            name_match = category.lower() in data.get("name", "").lower()
            if not (cat_match or name_match):
                continue
        if max_budget_usd > 0 and data.get("estimated_budget_usd", 0) > max_budget_usd:
            continue
        results.append(data)
    return results


def get_destination_details(destination_id_or_name: str) -> dict:
    """Retrieves detailed information about a specific travel destination from Firestore.

    Args:
        destination_id_or_name: The destination ID (e.g., 'kyoto-japan') or name (e.g., 'Kyoto').

    Returns:
        A dictionary with destination highlights, season, budget, and description.
    """
    db = get_firestore_client()
    target = destination_id_or_name.strip().lower()

    # Direct document ID lookup
    doc_ref = db.collection("destinations").document(target)
    doc = doc_ref.get()
    if doc.exists:
        res = doc.to_dict()
        res["id"] = doc.id
        return res

    # Fallback search by name or country
    for d in db.collection("destinations").stream():
        data = d.to_dict()
        if target in d.id.lower() or target in data.get("name", "").lower() or target in data.get("country", "").lower():
            data["id"] = d.id
            return data

    return {"error": f"Destination '{destination_id_or_name}' not found in catalog."}


def add_destination(
    name: str,
    country: str,
    category: str,
    estimated_budget_usd: float,
    best_season: str,
    highlights: list[str],
    description: str,
    recommended_days: int = 4,
) -> str:
    """Adds a new destination to the Firestore catalog.

    Args:
        name: Full name of the destination (e.g. 'Santorini, Greece').
        country: Country name.
        category: Category (e.g. 'Coastal & Scenic', 'Cultural & Historical', 'Nature & Adventure').
        estimated_budget_usd: Estimated budget in USD.
        best_season: Best time of the year to visit.
        highlights: Key landmarks and must-see attractions.
        description: Overview of what makes the destination appealing.
        recommended_days: Recommended trip length in days.

    Returns:
        Confirmation string with the created destination ID.
    """
    db = get_firestore_client()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", f"{name}-{country}".lower()).strip("-")
    doc_data = {
        "name": name,
        "country": country,
        "category": category,
        "estimated_budget_usd": float(estimated_budget_usd),
        "best_season": best_season,
        "highlights": highlights,
        "description": description,
        "recommended_days": int(recommended_days),
    }
    db.collection("destinations").document(slug).set(doc_data)
    return f"Destination '{name}' successfully saved with ID '{slug}'."


def save_itinerary(
    destination: str,
    duration_days: int,
    planned_activities: list[str],
    estimated_cost_usd: float,
    notes: str = "",
) -> str:
    """Saves a personalized travel itinerary to the Firestore backend.

    Args:
        destination: Destination name or city.
        duration_days: Number of days for the trip.
        planned_activities: List of scheduled activities or day-by-day plan.
        estimated_cost_usd: Estimated total trip cost in USD.
        notes: Any special preferences, accommodations, or notes.

    Returns:
        Confirmation message with the saved itinerary ID.
    """
    db = get_firestore_client()
    itinerary_id = f"itin-{uuid.uuid4().hex[:8]}"
    doc_data = {
        "destination": destination,
        "duration_days": int(duration_days),
        "planned_activities": planned_activities,
        "estimated_cost_usd": float(estimated_cost_usd),
        "notes": notes,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    db.collection("saved_itineraries").document(itinerary_id).set(doc_data)
    return f"Itinerary for {destination} saved successfully with ID '{itinerary_id}'."



def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict:
    """Converts an amount from one currency to another using live exchange rates.

    Args:
        amount: The numerical amount of money to convert.
        from_currency: 3-letter currency code to convert from (e.g. 'USD', 'EUR', 'JPY', 'GBP', 'CAD').
        to_currency: 3-letter currency code to convert to (e.g. 'JPY', 'EUR', 'USD', 'GBP').

    Returns:
        A dictionary containing the conversion result, rate, and currencies.
    """
    from_code = from_currency.strip().upper()
    to_code = to_currency.strip().upper()

    try:
        url = f"https://open.er-api.com/v6/latest/{from_code}"
        req = urllib.request.Request(url, headers={"User-Agent": "WanderlustAgent"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))

        if data.get("result") != "success":
            return {"error": f"Failed to fetch exchange rates for {from_code}."}

        rates = data.get("rates", {})
        if to_code not in rates:
            return {"error": f"Currency code '{to_code}' is not supported."}

        rate = float(rates[to_code])
        converted_amount = round(amount * rate, 2)
        return {
            "amount": amount,
            "from_currency": from_code,
            "to_currency": to_code,
            "rate": rate,
            "converted_amount": converted_amount,
        }
    except Exception as e:
        return {"error": f"Currency conversion error: {str(e)}"}


def lookup_location(query: str) -> dict:
    """Looks up geographic coordinates, full address, and an OpenStreetMap URL for any landmark, city, or destination worldwide.

    Args:
        query: The landmark, attraction, or city name to look up (e.g. 'Colosseum Rome', 'Eiffel Tower', 'Fushimi Inari Kyoto').

    Returns:
        A dictionary with the location's name, full address, latitude, longitude, category type, and OpenStreetMap map link.
    """
    try:
        clean_query = query.strip()
        params = urllib.parse.urlencode({"q": clean_query, "format": "json", "limit": 1})
        api_key = os.getenv("NOMINATIM_API_KEY", "")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 WanderlustTravelAgent/1.0"
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        url = f"https://nominatim.openstreetmap.org/search?{params}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if not data:
            return {"error": f"No geographic data found for '{query}'."}

        item = data[0]
        lat = float(item.get("lat"))
        lon = float(item.get("lon"))
        return {
            "name": item.get("name") or clean_query,
            "display_name": item.get("display_name"),
            "latitude": lat,
            "longitude": lon,
            "type": item.get("type"),
            "osm_map_url": f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}",
        }
    except Exception as e:
        return {"error": f"Geocoding lookup error: {str(e)}"}



async def generate_destination_image(
    prompt: str, tool_context: ToolContext = None
) -> dict:
    """Generates a scenic destination visual, landmark concept art, or travel postcard using the gemini-3.1-flash-lite-image model in the global region.

    Saves the image as an artifact in the session (Playground Artifacts panel) and uploads the image bytes directly to public Cloud Storage.

    Args:
        prompt: Detailed visual prompt describing the destination, landmark, or postcard (e.g. 'Scenic sunset over Santorini caldera with whitewashed villas and blue domes').
        tool_context: ADK ToolContext used to save the artifact in the session.

    Returns:
        A dictionary containing the public image URL, filename, and status.
    """
    try:
        genai_client = genai.Client(
            vertexai=True,
            project=FIRESTORE_PROJECT_ID,
            location="global",
        )
        response = genai_client.models.generate_content(
            model=IMAGE_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            ),
        )

        image_bytes = None
        mime_type = "image/jpeg"
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                image_bytes = part.inline_data.data
                mime_type = part.inline_data.mime_type or "image/jpeg"
                break

        if not image_bytes:
            return {"error": "No image data was generated by the model."}

        ext = "png" if "png" in mime_type.lower() else "jpg"
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", prompt[:30].strip().lower()).strip("_")
        filename = f"destination_{slug}_{timestamp}_{uuid.uuid4().hex[:6]}.{ext}"

        # 1. Save artifact so it shows up in Playground's Artifacts panel
        if tool_context is not None:
            artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            await tool_context.save_artifact(filename, artifact_part)

        # 2. Upload image bytes directly to public Cloud Storage (without writing to a local file)
        storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(image_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{filename}"
        return {
            "status": "success",
            "public_image_url": public_url,
            "filename": filename,
            "mime_type": mime_type,
        }
    except Exception as e:
        return {"error": f"Image generation error: {str(e)}"}


async def generate_destination_video(
    prompt: str, tool_context: ToolContext = None
) -> dict:
    """Generates a short scenic travel video or cinematic preview for a destination, landmark, or activity using Google's Omni model (gemini-omni-flash-preview) in the global region.

    Saves the video as an artifact in the session (Playground Artifacts panel) and uploads the video bytes directly to public Cloud Storage.

    Args:
        prompt: Detailed visual prompt describing the scene, destination, or motion (e.g. 'A 3-second drone video flying over a tropical beach at sunset with gentle ocean waves').
        tool_context: ADK ToolContext used to save the artifact in the session.

    Returns:
        A dictionary containing the public video URL, filename, and status.
    """
    try:
        genai_client = genai.Client(
            vertexai=True,
            project=FIRESTORE_PROJECT_ID,
            location="global",
        )
        interaction = genai_client.interactions.create(
            model=VIDEO_MODEL,
            input=prompt,
            response_format=[
                {
                    "type": "video",
                    "delivery": "inline",
                    "duration": "3s",
                }
            ],
            generation_config={
                "video_config": {
                    "task": "text_to_video",
                }
            },
        )

        video_bytes = None
        mime_type = "video/mp4"

        for step in getattr(interaction, "steps", []) or []:
            if getattr(step, "type", None) == "model_output":
                for content in getattr(step, "content", []) or []:
                    if getattr(content, "type", None) == "video" or getattr(
                        content, "mime_type", ""
                    ).startswith("video/"):
                        if getattr(content, "data", None):
                            video_bytes = base64.b64decode(content.data)
                            mime_type = getattr(content, "mime_type", "video/mp4")
                            break
                        elif (
                            hasattr(content, "inline_data")
                            and content.inline_data
                            and getattr(content.inline_data, "data", None)
                        ):
                            video_bytes = content.inline_data.data
                            mime_type = (
                                getattr(content.inline_data, "mime_type", None)
                                or "video/mp4"
                            )
                            break
                if video_bytes:
                    break

        if not video_bytes:
            return {"error": "No video data was returned by the Omni model."}

        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", prompt[:30].strip().lower()).strip("_")
        filename = f"destination_video_{slug}_{timestamp}_{uuid.uuid4().hex[:6]}.mp4"

        # 1. Save artifact so it shows up in Playground's Artifacts panel
        if tool_context is not None:
            artifact_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
            await tool_context.save_artifact(filename, artifact_part)

        # 2. Upload video bytes directly to public Cloud Storage (without writing to a local file)
        storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(video_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{filename}"
        return {
            "status": "success",
            "public_video_url": public_url,
            "filename": filename,
            "mime_type": mime_type,
        }
    except Exception as e:
        return {"error": f"Video generation error: {str(e)}"}


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are Wanderlust, an intelligent Travel & Exploration Concierge. "
        "You assist travelers with discovering destinations, checking weather and local time, "
        "exploring detailed itineraries, converting currencies with live market rates, "
        "looking up geographic locations/landmarks via OpenStreetMap, generating scenic destination visuals/postcards, "
        "creating short cinematic travel preview videos using Google's Omni model, "
        "and saving personalized travel plans. "
        "When users ask about places to visit or need recommendations, use `list_destinations` or `get_destination_details` to search the Firestore catalog. "
        "When users ask about where an attraction, city, or landmark is located, use `lookup_location` to provide real coordinates and map links. "
        "When users ask to convert currency or calculate budgets in foreign currencies, use `convert_currency`. "
        "When users ask to visualize a destination, generate a concept image, or create a travel postcard, use `generate_destination_image`. "
        "When users ask for a video, scenic clip, or motion preview of a destination or attraction, use `generate_destination_video`. "
        "When users want to record a new destination or save a customized trip itinerary, use `add_destination` or `save_itinerary` to persist it in Firestore."
    ),
    workflow_description="Analyze the request and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        '{"Image": {"url": {"literalString": "https://..."}}}. Never point an '
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=instruction,
    tools=[
        list_destinations,
        get_destination_details,
        add_destination,
        save_itinerary,
        convert_currency,
        lookup_location,
        generate_destination_image,
        generate_destination_video,
        get_weather,
        get_current_time,
    ],
    after_model_callback=a2ui_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)





