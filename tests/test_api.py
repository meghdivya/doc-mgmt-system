import os
import sqlite3
from pathlib import Path

os.environ["OUTMARKET_DB_PATH"] = "data/test_outmarket.db"

import pytest
from fastapi.testclient import TestClient

from app.database import ensure_db
from app.main import app


@pytest.fixture
def client():
    db_path = Path("data/test_outmarket.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    ensure_db()

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("DELETE FROM orders")
        conn.execute("DELETE FROM products")
        conn.execute("DELETE FROM sqlite_sequence WHERE name='orders'")
        conn.execute("DELETE FROM sqlite_sequence WHERE name='products'")
        conn.commit()

    with TestClient(app) as test_client:
        yield test_client


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_product_flow(client):
    product = {"name": "Coffee Beans", "price": 12.5, "stock": 10}
    create = client.post("/products", json=product)

    assert create.status_code == 201
    assert create.json()["name"] == product["name"]
    assert create.json()["stock"] == product["stock"]

    products = client.get("/products")
    assert products.status_code == 200
    assert len(products.json()) == 1
    assert products.json()[0]["price"] == product["price"]


def test_order_and_dashboard(client):
    client.post("/products", json={"name": "Tea", "price": 8, "stock": 5})
    client.post("/products", json={"name": "Chips", "price": 3.5, "stock": 12})

    order = client.post("/orders", json={"product_id": 1, "quantity": 2})
    assert order.status_code == 201
    assert order.json()["total"] == 16.0

    product_after_order = client.get("/products").json()[0]
    assert product_after_order["stock"] == 3

    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["orders"] == 1
    assert dashboard.json()["products"] == 2
    assert dashboard.json()["revenue"] == 16.0
