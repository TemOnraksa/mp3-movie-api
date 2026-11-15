# MP3 Movie API

This project is a FastAPI application that stores a movie collection in a SQLite database, lets clients filter it with SQL, cleans it with my MP1 data pipeline, and caches repeated requests. `POST /upload` accepts a CSV with `title`, `release_year`, `rating`, and `genre` columns, checks that the columns are right and that there is at least one row, and replaces the movies in the `movies` table. Because the data lives in `data/movies.db` instead of in memory, the movies are still there after the server restarts. `GET /movies` returns up to `limit` movies plus the total count, and `GET /movies/search` uses a SQL `WHERE` and `ORDER BY` to return chosen columns for movies with at least `min_rating`, highest rated first. `POST /movies/process` reads the movies from SQLite, runs the MP1 `validate_dataframe` and `process_data` functions with the settings in the request body, saves the cleaned movies back, and returns a cleaning report. Responses from `GET /movies` are cached in FakeRedis for 90 seconds per `limit`, and the cache is cleared after every successful upload or processing so clients never get outdated data. The code is split into `src/database.py` (connection and table), `src/storage.py` (SQL queries), `src/cache.py` (caching), `src/models.py` (request and response models), `src/middleware.py` (request IDs and logging), and `data_pipeline/` (the MP1 modules).

## Start the API

```bash
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

Then open http://127.0.0.1:8000/docs.

## Run the tests

```bash
python -m pytest tests -v
```

## Sample processing request

After uploading `fixtures/sample_movies.csv`, send this body to `POST /movies/process`:

```json
{
  "validation": {
    "required_columns": ["title", "release_year", "rating", "genre"],
    "numeric_columns": ["release_year", "rating"]
  },
  "processing": {
    "remove_duplicates": true,
    "missing": {"enabled": true, "axis": "rows"},
    "outliers": {"enabled": true, "columns": ["rating"], "method": "iqr", "threshold": 1.5}
  }
}
```

Expected result:

```json
{
  "validation_rows_removed": 0,
  "cleaning_report": {
    "rows_before": 20,
    "rows_after": 16,
    "rows_removed": 4,
    "columns_before": 4,
    "columns_after": 4,
    "columns_removed": 0
  }
}
```

The 4 removed rows are the duplicate Movie B and Movie D rows and the two outlier ratings, Movie Q (1.0) and Movie R (0.5).
