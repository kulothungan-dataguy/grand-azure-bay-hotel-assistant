import os


def test_google_api_key_exists():

    assert os.getenv("GOOGLE_API_KEY") is not None