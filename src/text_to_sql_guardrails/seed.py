"""Deterministic demo-shop data generation."""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, insert, text
from sqlalchemy.engine import Engine

from .models import Customer, Order, OrderItem, Product, StaffSalary

CUSTOMER_COUNT = 200
PRODUCT_COUNT = 40
ORDER_COUNT = 1_000


def _demo_rows() -> dict[str, list[dict[str, object]]]:
    rng = random.Random(42)
    base_date = datetime(2024, 1, 1, 9, 0, 0)
    locations = [
        ("Istanbul", "Turkey"),
        ("Berlin", "Germany"),
        ("Paris", "France"),
        ("London", "United Kingdom"),
        ("Madrid", "Spain"),
        ("Rome", "Italy"),
        ("Toronto", "Canada"),
        ("Tokyo", "Japan"),
    ]
    categories = ["Books", "Electronics", "Home", "Outdoors", "Toys", "Clothing"]

    customers: list[dict[str, object]] = []
    for customer_id in range(1, CUSTOMER_COUNT + 1):
        city, country = locations[(customer_id - 1) % len(locations)]
        customers.append(
            {
                "id": customer_id,
                "name": f"Customer {customer_id:03d}",
                "email": f"customer{customer_id:03d}@example.test",
                "phone": f"+90-555-{customer_id:04d}",
                "city": city,
                "country": country,
                "created_at": base_date - timedelta(days=rng.randrange(0, 730)),
            }
        )

    products: list[dict[str, object]] = []
    for product_id in range(1, PRODUCT_COUNT + 1):
        price = Decimal(rng.randrange(500, 50_001)) / Decimal(100)
        products.append(
            {
                "id": product_id,
                "name": f"Product {product_id:02d}",
                "category": categories[(product_id - 1) % len(categories)],
                "price": price.quantize(Decimal("0.01")),
            }
        )

    orders: list[dict[str, object]] = []
    order_items: list[dict[str, object]] = []
    statuses = ["pending", "paid", "shipped", "delivered", "cancelled"]
    item_id = 1
    prices = {int(product["id"]): product["price"] for product in products}
    for order_id in range(1, ORDER_COUNT + 1):
        selected_products = rng.sample(range(1, PRODUCT_COUNT + 1), rng.randint(1, 4))
        total = Decimal("0.00")
        for product_id in selected_products:
            quantity = rng.randint(1, 5)
            unit_price = prices[product_id]
            assert isinstance(unit_price, Decimal)
            total += unit_price * quantity
            order_items.append(
                {
                    "id": item_id,
                    "order_id": order_id,
                    "product_id": product_id,
                    "quantity": quantity,
                    "unit_price": unit_price,
                }
            )
            item_id += 1
        orders.append(
            {
                "id": order_id,
                "customer_id": rng.randint(1, CUSTOMER_COUNT),
                "status": rng.choice(statuses),
                "ordered_at": base_date + timedelta(
                    days=rng.randrange(0, 730), minutes=rng.randrange(0, 1_440)
                ),
                "total": total.quantize(Decimal("0.01")),
            }
        )

    salaries = [
        {
            "id": staff_id,
            "staff_name": f"Staff Member {staff_id:02d}",
            "role": ("Manager", "Engineer", "Support", "Warehouse")[staff_id % 4],
            "salary": Decimal(40_000 + staff_id * 3_750).quantize(Decimal("0.01")),
        }
        for staff_id in range(1, 11)
    ]
    return {
        "customers": customers,
        "products": products,
        "orders": orders,
        "order_items": order_items,
        "staff_salaries": salaries,
    }


def seed_database(engine: Engine) -> None:
    """Replace demo data with the same deterministic dataset on every call."""

    rows = _demo_rows()
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(
                text(
                    "TRUNCATE TABLE order_items, orders, staff_salaries, products, customers "
                    "RESTART IDENTITY CASCADE"
                )
            )
        else:
            for model in (OrderItem, Order, StaffSalary, Product, Customer):
                connection.execute(delete(model))

        connection.execute(insert(Customer), rows["customers"])
        connection.execute(insert(Product), rows["products"])
        connection.execute(insert(Order), rows["orders"])
        connection.execute(insert(OrderItem), rows["order_items"])
        connection.execute(insert(StaffSalary), rows["staff_salaries"])
