CREATE TABLE publishers (
    id      integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name    text NOT NULL UNIQUE,
    country text
);

CREATE TABLE games (
    id           integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    publisher_id integer NOT NULL REFERENCES publishers (id),
    title        text NOT NULL,
    genre        text NOT NULL,
    min_players  integer NOT NULL CHECK (min_players > 0),
    max_players  integer NOT NULL,
    play_minutes integer NOT NULL CHECK (play_minutes > 0),
    price        numeric(10, 2) NOT NULL CHECK (price >= 0),
    stock        integer NOT NULL DEFAULT 0 CHECK (stock >= 0),
    UNIQUE (publisher_id, title),
    CHECK (max_players >= min_players)
);

CREATE TABLE customers (
    id        integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    full_name text NOT NULL,
    email     text NOT NULL UNIQUE,
    city      text
);

CREATE TABLE orders (
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id integer NOT NULL REFERENCES customers (id),
    status      text NOT NULL DEFAULT 'new'
                CHECK (status IN ('new', 'paid', 'shipped', 'cancelled')),
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE order_items (
    id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id   integer NOT NULL REFERENCES orders (id),
    game_id    integer NOT NULL REFERENCES games (id),
    quantity   integer NOT NULL CHECK (quantity > 0),
    unit_price numeric(10, 2) NOT NULL CHECK (unit_price >= 0),
    UNIQUE (order_id, game_id)
);

CREATE INDEX idx_games_publisher ON games (publisher_id);
CREATE INDEX idx_orders_customer ON orders (customer_id);
CREATE INDEX idx_order_items_game ON order_items (game_id);
