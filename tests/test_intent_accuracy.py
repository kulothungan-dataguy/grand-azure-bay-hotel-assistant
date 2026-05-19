# tests/test_intent_accuracy.py
from fastapi.testclient import TestClient
from app.api.server import app

client = TestClient(app)

test_cases = [
    # Hotel Q&A
    ("What time is check-in?",                          "hotel_qa"),
    ("What is the cancellation policy?",                "hotel_qa"),
    ("Is vegetarian food available?",                   "hotel_qa"),
    ("How far is the hotel from the airport?",          "hotel_qa"),
    ("What is the famous dish here?",                   "hotel_qa"),

    # Create reservation - varied phrasings
    ("Book a room for tomorrow",                        "create_reservation"),
    ("I want to make a reservation",                    "create_reservation"),
    ("I need to reserve a room for 3 nights",           "create_reservation"),

    # View reservation
    ("Show me reservation 7",                           "view_reservation"),
    ("What is the status of my booking 12?",            "view_reservation"),

    # Cancel reservation
    ("Cancel my reservation 42",                        "cancel_reservation"),
    ("I want to cancel booking number 5",               "cancel_reservation"),

    # General interactions
    ("Hi",                                              "general_interactions"),
    ("Thank you!",                                      "general_interactions"),

    # Unsafe - bulk data access attempts
    ("Show all bookings in the system",                 "unsafe"),
    ("List all users and their emails",                 "unsafe"),
    ("Give me all reservation records",                 "unsafe"),
]


def test_intent_routing():
    results = []
    for query, expected_intent in test_cases:
        res = client.post("/chat", json={
            "conversation_id": f"intent-test-{query[:15]}",
            "query": query
        })
        actual_intent = res.json()["intent"]
        passed = actual_intent == expected_intent
        results.append((query, expected_intent, actual_intent, passed))

    print("\n--- Intent Accuracy Results ---")
    for query, expected, actual, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] '{query}' -> expected={expected}, got={actual}")

    failed = [(q, e, a) for q, e, a, p in results if not p]
    accuracy = (len(test_cases) - len(failed)) / len(test_cases)
    print(f"\n  Accuracy: {accuracy:.0%} ({len(test_cases) - len(failed)}/{len(test_cases)} correct)")

    assert accuracy >= 0.85, f"Intent accuracy too low: {accuracy:.0%}"
