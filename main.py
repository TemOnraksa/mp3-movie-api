import io
import logging
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile

from data_pipeline import create_cleaning_report, process_data, validate_dataframe
from src import (
    HealthResponse,
    MovieCache,
    MovieDataResponse,
    MovieProcessingReport,
    MovieStorage,
    MovieUploadInfo,
    ProcessConfig,
    log_requests,
    setup_logging,
)
from src.storage import MOVIE_COLUMNS

setup_logging(verbose=True)
logger = logging.getLogger(__name__)

app = FastAPI(title="Movie API", version="1.0.0")
app.middleware("http")(log_requests)

storage = MovieStorage()
cache = MovieCache()


@app.get("/health", response_model=HealthResponse)
def health_check():
    """Return the application status and version."""
    return {"status": "ok", "version": "1.0.0"}


@app.post("/upload", response_model=MovieUploadInfo)
async def upload_movies(file: UploadFile = File(...)):
    """Read a movie CSV and replace the stored collection."""
    # 1. Only accept CSV files, then read them like in MP2
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".csv":
        logger.warning(f"Unsupported file format: {suffix}")
        raise HTTPException(status_code=400, detail=f"Unsupported file format: {suffix}. Please upload a .csv file.")

    contents = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(contents))
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as error:
        logger.warning(f"Could not read CSV file {file.filename}: {error}")
        raise HTTPException(status_code=400, detail="Could not read the CSV file. Make sure it is a valid, non-empty CSV.")

    # 2. Quick checks before saving: the right columns and at least one row
    if sorted(df.columns) != sorted(MOVIE_COLUMNS):
        logger.warning(f"Wrong columns: {list(df.columns)}")
        raise HTTPException(status_code=400, detail=f"The CSV must have exactly these columns: {MOVIE_COLUMNS}")

    if df.empty:
        logger.warning("Uploaded CSV has no data rows")
        raise HTTPException(status_code=400, detail="The CSV has no data rows.")

    df = df[MOVIE_COLUMNS]

    # 3. Replace the stored movies, then clear old cached responses
    storage.save(df)
    cache.invalidate()
    logger.info(f"Uploaded movies: filename={file.filename}, rows={len(df)}")

    return {
        "filename": file.filename,
        "rows": len(df),
        "columns": len(df.columns),
        "column_names": list(df.columns),
    }


@app.get("/movies", response_model=MovieDataResponse)
def get_movies(limit: int = Query(default=100, ge=1)):
    """Return up to limit movies, using the cache when possible."""
    # 1. If this exact request was answered recently, reuse that answer
    cached = cache.get(limit)
    if cached is not None:
        logger.info(f"Cache hit: limit={limit}")
        return cached

    # 2. Otherwise read from SQLite
    data = storage.select_columns(MOVIE_COLUMNS, limit)
    total_rows = storage.count_movies()
    response = {"data": data, "total_rows": total_rows}

    # 3. Save the answer in the cache for next time
    cache.set(limit, response)
    logger.info(f"Retrieved movies: returned_rows={len(data)}")
    return response


@app.get("/movies/search", response_model=list[dict])
def query_movies(
    columns: list[str] = Query(default=["title"]),
    min_rating: float = Query(default=0, ge=0, le=10),
    limit: int = Query(default=100, ge=1)
):
    """Return chosen columns for movies with at least min_rating."""
    try:
        results = storage.query_movies(columns, min_rating, limit)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    logger.info(f"Queried movies: columns={columns}, min_rating={min_rating}, returned_rows={len(results)}")
    return results


@app.post("/movies/process", response_model=MovieProcessingReport)
def process_movies(config: ProcessConfig):
    """Validate and clean the stored movies using MP1 functions."""
    # 1. Get the stored movies
    df = storage.get()
    if df.empty:
        logger.warning("No movies to process")
        raise HTTPException(status_code=400, detail="No movies to process. Upload a CSV first.")

    # 2. Same steps as MP2: settings, numeric column check, validate, clean
    settings = config.model_dump()
    required_columns = settings["validation"]["required_columns"]
    numeric_columns = settings["validation"]["numeric_columns"]

    for col in numeric_columns:
        if col not in df.columns:
            logger.warning(f"Numeric column not found: {col}")
            raise HTTPException(status_code=400, detail=f"Numeric column not found: {col}")

    try:
        validated = validate_dataframe(df, required_columns, numeric_columns)
        validation_rows_removed = len(df) - len(validated)
        logger.info(f"Validated movies: rows_removed={validation_rows_removed}")

        df_before = validated.copy()
        processed = process_data(validated, settings)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    report = create_cleaning_report(df_before, processed)

    # 3. Save the cleaned movies, then clear old cached responses
    storage.save(processed)
    cache.invalidate()
    logger.info(
        f"Processed movies: validation_removed={validation_rows_removed}, "
        f"rows_before={report['rows_before']}, rows_after={report['rows_after']}"
    )

    return {
        "validation_rows_removed": validation_rows_removed,
        "cleaning_report": report,
    }
