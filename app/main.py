from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status

from app.database import ensure_db, get_db_connection
from app.schemas import OrderCreate, OrderRead, ProductCreate, ProductRead


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_db()
    yield


app = FastAPI(title="Outmarket", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "outmarket"}


@app.get("/products", response_model=list[ProductRead])
def list_products() -> list[dict]:
    with get_db_connection() as conn:
        rows = conn.execute("SELECT * FROM products ORDER BY id").fetchall()
        return [dict(row) for row in rows]


@app.post("/products", status_code=status.HTTP_201_CREATED, response_model=ProductRead)
def create_product(product: ProductCreate) -> dict:
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO products (name, price, stock) VALUES (?, ?, ?)",
            (product.name, product.price, product.stock),
        )
        product_id = cursor.lastrowid
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        return dict(row)


@app.post("/orders", status_code=status.HTTP_201_CREATED, response_model=OrderRead)
def create_order(order: OrderCreate) -> dict:
    with get_db_connection() as conn:
        product = conn.execute(
            "SELECT * FROM products WHERE id = ?",
            (order.product_id,),
        ).fetchone()

        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")

        if product["stock"] < order.quantity:
            raise HTTPException(status_code=400, detail="Not enough stock")

        total = round(float(product["price"]) * order.quantity, 2)
        new_stock = product["stock"] - order.quantity

        conn.execute(
            "UPDATE products SET stock = ? WHERE id = ?",
            (new_stock, order.product_id),
        )
        cursor = conn.execute(
            "INSERT INTO orders (product_id, quantity, total) VALUES (?, ?, ?)",
            (order.product_id, order.quantity, total),
        )
        order_row = conn.execute(
            "SELECT * FROM orders WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return dict(order_row)


@app.get("/dashboard")
def dashboard() -> dict:
    with get_db_connection() as conn:
        product_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        order_count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        revenue = conn.execute("SELECT COALESCE(SUM(total), 0) FROM orders").fetchone()[0]
        low_stock = conn.execute(
            "SELECT COUNT(*) FROM products WHERE stock <= 5"
        ).fetchone()[0]

        return {
            "products": product_count,
            "orders": order_count,
            "revenue": round(float(revenue), 2),
            "low_stock": low_stock,
        }
