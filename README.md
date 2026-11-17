# Outmarket

Outmarket is a minimal local marketplace MVP built for fast demo and iteration. It focuses on the essentials: product listing, stock updates, order creation, and a small sales summary.

## Purpose

This project is intentionally lean and local-first so it can be explained easily, tested often, and shipped quickly without extra complexity.

## Local run

1. Create a virtual environment.
2. Install dependencies:
   `pip install -r requirements.txt`
3. Start the API:
   `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
4. Open the API docs at http://localhost:8000/docs

## MVP scope

- Create and list products
- Sell stock through orders
- View local dashboard totals

## Project structure

- app/: API code
- docs/: planning and progress notes
- tests/: end-to-end feature tests
- data/: local SQLite data files
