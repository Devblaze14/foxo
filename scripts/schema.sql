-- Postgres schema for the Inventory & Stock-Movement Service.
--
-- You do NOT have to run this by hand: the app auto-creates these tables on
-- startup (Base.metadata.create_all). This file is provided so you can create
-- the schema directly in the Supabase SQL Editor (Dashboard -> SQL Editor ->
-- New query -> paste -> Run) if you prefer to set the database up first.
--
-- Generated from app/models.py, so it matches the ORM exactly.

CREATE TYPE movement_type_enum AS ENUM ('RESTOCK', 'SALE', 'ADJUSTMENT');

CREATE TABLE products (
    id SERIAL NOT NULL,
    sku VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    quantity_on_hand INTEGER NOT NULL,
    low_stock_threshold INTEGER,
    is_active BOOLEAN NOT NULL,
    version INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_product_qty_non_negative CHECK (quantity_on_hand >= 0)
);

CREATE UNIQUE INDEX ix_products_sku ON products (sku);

CREATE TABLE stock_movements (
    id SERIAL NOT NULL,
    product_id INTEGER NOT NULL,
    movement_type movement_type_enum NOT NULL,
    quantity_delta INTEGER NOT NULL,
    reason VARCHAR(500),
    resulting_quantity INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_movement_delta_nonzero CHECK (quantity_delta <> 0),
    CONSTRAINT ck_movement_resulting_non_negative CHECK (resulting_quantity >= 0),
    FOREIGN KEY (product_id) REFERENCES products (id)
);

CREATE INDEX ix_stock_movements_created_at ON stock_movements (created_at);
CREATE INDEX ix_stock_movements_product_id ON stock_movements (product_id);
