from travel_sources import content_hash, packing_recommendations, risk_level


def test_content_hash_is_stable_and_changes_with_text():
    assert content_hash("Paris", "text") == content_hash("Paris", "text")
    assert content_hash("Paris", "text") != content_hash("Paris", "new text")


def test_weather_risk_levels():
    assert risk_level(5, 0) == "low"
    assert risk_level(45, 61) == "moderate"
    assert risk_level(80, 95) == "high"


def test_packing_rules_are_explainable():
    items = packing_recommendations(
        {
            "precipitation_probability_max": 50,
            "temperature_min": 12,
            "temperature_max": 32,
            "wind_speed_max": 45,
        }
    )
    assert {item["item"] for item in items} == {
        "Umbrella or rain shell",
        "Warm layer or jacket",
        "Sunscreen and water bottle",
        "Wind-resistant outer layer",
    }
