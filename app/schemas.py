from pydantic import BaseModel, Field


class ProductCreate(BaseModel):
    name: str = Field(..., min_length=2)
    price: float = Field(..., gt=0)
    stock: int = Field(..., ge=0)


class ProductRead(ProductCreate):
    id: int


class OrderCreate(BaseModel):
    product_id: int = Field(..., gt=0)
    quantity: int = Field(..., gt=0)


class OrderRead(BaseModel):
    id: int
    product_id: int
    quantity: int
    total: float
