#!/usr/bin/env python3
"""Seed Firestore with initial destinations for the Wanderlust Travel Concierge agent."""

import os
from google.cloud import firestore

# Hardcode the project ID as requested to prevent project number resolution issues
PROJECT_ID = "qwiklabs-gcp-04-01d87701e441"

SAMPLE_DESTINATIONS = [
    {
        "id": "kyoto-japan",
        "name": "Kyoto, Japan",
        "country": "Japan",
        "category": "Cultural & Historical",
        "estimated_budget_usd": 1800,
        "best_season": "Spring (Cherry Blossoms) or Autumn",
        "highlights": [
            "Fushimi Inari Taisha",
            "Arashiyama Bamboo Grove",
            "Kinkaku-ji (Golden Pavilion)",
            "Gion Historic District"
        ],
        "description": "Ancient imperial capital with thousands of classical Buddhist temples, gardens, imperial palaces, and traditional wooden houses.",
        "recommended_days": 4
    },
    {
        "id": "reykjavik-iceland",
        "name": "Reykjavik & South Coast, Iceland",
        "country": "Iceland",
        "category": "Nature & Adventure",
        "estimated_budget_usd": 2600,
        "best_season": "Winter (Northern Lights) or Summer (Midnight Sun)",
        "highlights": [
            "Blue Lagoon geothermal spa",
            "Golden Circle (Thingvellir, Geysir, Gullfoss)",
            "Skogafoss & Seljalandsfoss waterfalls",
            "Reynisfjara Black Sand Beach"
        ],
        "description": "Land of fire and ice featuring dramatic glaciers, active volcanoes, black sand coastlines, and ethereal geothermal hot springs.",
        "recommended_days": 6
    },
    {
        "id": "amalfi-coast-italy",
        "name": "Amalfi Coast, Italy",
        "country": "Italy",
        "category": "Coastal & Scenic",
        "estimated_budget_usd": 2400,
        "best_season": "May to September",
        "highlights": [
            "Positano pastel cliffside village",
            "Path of the Gods scenic hike",
            "Ravello gardens & Villa Rufolo",
            "Capri island boat tour"
        ],
        "description": "Spectacular Mediterranean coastline with sheer cliffs, pastel-colored cliffside fishing villages, lemon groves, and azure waters.",
        "recommended_days": 5
    },
    {
        "id": "banff-canada",
        "name": "Banff National Park, Canada",
        "country": "Canada",
        "category": "Nature & Adventure",
        "estimated_budget_usd": 1900,
        "best_season": "Summer (Hiking/Lakes) or Winter (Skiing)",
        "highlights": [
            "Lake Louise turquoise glacial waters",
            "Moraine Lake & Valley of the Ten Peaks",
            "Icefields Parkway scenic drive",
            "Sulphur Mountain Gondola"
        ],
        "description": "Canada's oldest national park nestled in the Canadian Rockies with emerald glacial lakes, snow-capped peaks, and abundant wildlife.",
        "recommended_days": 5
    },
    {
        "id": "barcelona-spain",
        "name": "Barcelona, Spain",
        "country": "Spain",
        "category": "Cultural & Urban",
        "estimated_budget_usd": 1600,
        "best_season": "April to June or September to October",
        "highlights": [
            "La Sagrada Familia",
            "Park Güell",
            "Gothic Quarter alleys",
            "Barceloneta beach & tapas bars"
        ],
        "description": "Vibrant Catalan city celebrated for its fantastical Gaudí architecture, world-renowned culinary scene, and Mediterranean seaside lifestyle.",
        "recommended_days": 4
    }
]


def seed_destinations():
    print(f"Connecting to Firestore using project ID: {PROJECT_ID}...")
    db = firestore.Client(project=PROJECT_ID)
    collection_ref = db.collection("destinations")

    for dest in SAMPLE_DESTINATIONS:
        doc_id = dest["id"]
        data = {k: v for k, v in dest.items() if k != "id"}
        collection_ref.document(doc_id).set(data)
        print(f"Seeded destination: {dest['name']} ({doc_id})")

    print(f"\nSuccessfully seeded {len(SAMPLE_DESTINATIONS)} destinations into Firestore!")


if __name__ == "__main__":
    seed_destinations()
