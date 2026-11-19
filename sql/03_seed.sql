TRUNCATE order_items, orders, games, customers, publishers RESTART IDENTITY;

INSERT INTO publishers (name, country) VALUES
    ('Kosmos',              'Германия'),
    ('Days of Wonder',      'США'),
    ('Z-Man Games',         'США'),
    ('Czech Games Edition', 'Чехия'),
    ('Мир Хобби',           'Россия');

INSERT INTO games (publisher_id, title, genre, min_players, max_players, play_minutes, price, stock)
SELECT p.id, v.title, v.genre, v.min_p, v.max_p, v.minutes, v.price, v.stock
FROM (VALUES
    (1, 'Kosmos',              'Catan',             'стратегия', 3, 4,  90, 4490.00, 15),
    (2, 'Days of Wonder',      'Ticket to Ride',    'семейная',  2, 5,  60, 3990.00, 20),
    (3, 'Days of Wonder',      'Small World',       'стратегия', 2, 5,  80, 4290.00, 10),
    (4, 'Z-Man Games',         'Pandemic',          'кооператив', 2, 4, 45, 3790.00, 12),
    (5, 'Czech Games Edition', 'Codenames',         'вечеринка', 2, 8,  15, 1990.00, 40),
    (6, 'Czech Games Edition', 'Through the Ages',  'стратегия', 2, 4, 120, 5990.00, 6),
    (7, 'Мир Хобби',           'Каркассон',         'семейная',  2, 5,  45, 1990.00, 35),
    (8, 'Мир Хобби',           'Манчкин',           'карточная', 3, 6,  60, 1290.00, 50)
) AS v (ord, publisher, title, genre, min_p, max_p, minutes, price, stock)
JOIN publishers p ON p.name = v.publisher
ORDER BY v.ord;

INSERT INTO customers (full_name, email, city) VALUES
    ('Иванов Иван',     'ivanov@example.com',     'Москва'),
    ('Петрова Анна',    'petrova@example.com',    'Санкт-Петербург'),
    ('Сидоров Пётр',    'sidorov@example.com',    'Казань'),
    ('Кузнецова Мария', 'kuznetsova@example.com', NULL);

DO $$
DECLARE
    v_order integer;
BEGIN
    INSERT INTO orders (customer_id, status)
    VALUES ((SELECT id FROM customers WHERE email = 'ivanov@example.com'), 'paid')
    RETURNING id INTO v_order;
    INSERT INTO order_items (order_id, game_id, quantity, unit_price)
    SELECT v_order, g.id, v.qty, g.price
    FROM (VALUES ('Catan', 1), ('Codenames', 2)) AS v (title, qty)
    JOIN games g ON g.title = v.title;

    INSERT INTO orders (customer_id, status)
    VALUES ((SELECT id FROM customers WHERE email = 'petrova@example.com'), 'shipped')
    RETURNING id INTO v_order;
    INSERT INTO order_items (order_id, game_id, quantity, unit_price)
    SELECT v_order, g.id, v.qty, g.price
    FROM (VALUES ('Pandemic', 1), ('Каркассон', 1)) AS v (title, qty)
    JOIN games g ON g.title = v.title;

    INSERT INTO orders (customer_id, status)
    VALUES ((SELECT id FROM customers WHERE email = 'sidorov@example.com'), 'new')
    RETURNING id INTO v_order;
    INSERT INTO order_items (order_id, game_id, quantity, unit_price)
    SELECT v_order, g.id, v.qty, g.price
    FROM (VALUES ('Through the Ages', 1)) AS v (title, qty)
    JOIN games g ON g.title = v.title;
END $$;
