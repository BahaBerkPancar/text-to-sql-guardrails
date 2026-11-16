"""Create the demo shop schema.

Revision ID: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False, unique=True),
        sa.Column("phone", sa.String(length=40), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
    )
    op.create_table(
        "staff_salaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("staff_name", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=100), nullable=False),
        sa.Column("salary", sa.Numeric(12, 2), nullable=False),
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("ordered_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
    )
    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("staff_salaries")
    op.drop_table("products")
    op.drop_table("customers")
