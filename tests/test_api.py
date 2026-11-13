def test_upload_movies(uploaded_movies):
    assert uploaded_movies["rows"] == 20
    assert uploaded_movies["columns"] == 4
    assert uploaded_movies["column_names"] == ["title", "release_year", "rating", "genre"]


def test_get_movies_with_limit(client, uploaded_movies):
    response = client.get("/movies?limit=2")

    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 2
    assert body["total_rows"] == 20


def test_search_by_rating(client, uploaded_movies):
    response = client.get("/movies/search?min_rating=8.5&limit=2")

    assert response.status_code == 200
    assert response.json() == [
        {"id": 4, "title": "Movie C"},
        {"id": 2, "title": "Movie B"},
    ]


def test_process_movies(client, uploaded_movies, processing_body):
    response = client.post("/movies/process", json=processing_body)

    assert response.status_code == 200
    report = response.json()["cleaning_report"]
    assert report["rows_before"] == 20
    assert report["rows_after"] == 16
