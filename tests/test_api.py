from pathlib import Path

import pandas as pd
import pytest

from src import MovieStorage
import main


def test_movies_persist(client, test_storage, uploaded_movies):
    # A brand-new storage object pointing at the same database file
    other_storage = MovieStorage(test_storage.db_path)

    df = other_storage.get()
    assert other_storage.count_movies() == 20
    assert len(df) == 20
    assert list(df.columns) == ["title", "release_year", "rating", "genre"]

    # Titles come back in the same order as the CSV
    original = pd.read_csv(Path("fixtures") / "sample_movies.csv")
    assert list(df["title"]) == list(original["title"])

    # IDs from SQL and from the API are both 1 to 20, in row order
    db_ids = [row["id"] for row in other_storage.select_columns(["title"], limit=100)]
    response = client.get("/movies?limit=100")
    api_ids = [row["id"] for row in response.json()["data"]]

    assert db_ids == list(range(1, 21))
    assert api_ids == list(range(1, 21))


def test_cache_and_processing(client, uploaded_movies, processing_body):
    # 1. First requests fill the cache
    first_100 = client.get("/movies?limit=100")
    first_1 = client.get("/movies?limit=1")
    assert first_100.status_code == 200
    assert first_1.status_code == 200
    assert main.cache.get(100) == first_100.json()
    assert main.cache.get(1) == first_1.json()

    # 2. Repeating gives the same response
    again_100 = client.get("/movies?limit=100")
    assert again_100.json() == first_100.json()

    # 3. Processing changes the data and clears the cache
    response = client.post("/movies/process", json=processing_body)
    assert response.status_code == 200
    body = response.json()
    assert body["validation_rows_removed"] == 0
    assert body["cleaning_report"]["rows_before"] == 20
    assert body["cleaning_report"]["rows_after"] == 16
    assert main.cache.get(100) is None
    assert main.cache.get(1) is None

    # 4. New retrieval shows the 16 cleaned movies and is cached again
    response = client.get("/movies?limit=100")
    body = response.json()
    assert body["total_rows"] == 16

    titles = [row["title"] for row in body["data"]]
    expected_titles = [f"Movie {letter}" for letter in "ABCDEFGHIJKLMNOP"]
    assert titles == expected_titles

    ids = [row["id"] for row in body["data"]]
    assert ids == list(range(1, 17))

    assert main.cache.get(100) == body


def test_cache_hit_skips_database(client, uploaded_movies, monkeypatch):
    # 1. Fill the cache
    first = client.get("/movies?limit=100")
    assert first.status_code == 200

    # 2. Make the database methods fail the test if they are called
    def fail_if_called(*args, **kwargs):
        pytest.fail("The database was used even though the response was cached")

    monkeypatch.setattr(main.storage, "select_columns", fail_if_called)
    monkeypatch.setattr(main.storage, "count_movies", fail_if_called)

    # 3. Same request again comes from the cache
    second = client.get("/movies?limit=100")
    assert second.status_code == 200
    assert second.json() == first.json()
