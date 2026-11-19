GRANT USAGE ON SCHEMA public TO :"app_user";

GRANT SELECT, INSERT, UPDATE
    ON TABLE publishers, games, customers, orders, order_items
    TO :"app_user";
