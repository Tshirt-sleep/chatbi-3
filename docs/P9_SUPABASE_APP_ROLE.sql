-- Run once in the dedicated ChatBI Mock Supabase project as the project owner.
-- Do not add a password here. Set the role password through `psql`'s `\password`
-- prompt so the plaintext is not part of SQL editor history or this repository.

CREATE ROLE chatbi_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;

GRANT CONNECT ON DATABASE postgres TO chatbi_app;
GRANT USAGE ON SCHEMA public TO chatbi_app;

GRANT SELECT ON TABLE
    dataset_manifests,
    categories,
    channels,
    customers,
    products,
    orders,
    order_items,
    refunds,
    saas_accounts,
    saas_plans,
    saas_acquisition_channels,
    saas_subscriptions
TO chatbi_app;

GRANT SELECT, INSERT, UPDATE ON TABLE turn_feedback TO chatbi_app;

-- The app connects as chatbi_app. These two dimensions are joined by the
-- category-sales and channel-sales query templates, so their read scope must
-- match the existing ecommerce Mock policies on products/order_items/refunds.
CREATE POLICY chatbi_app_read_categories
    ON public.categories
    FOR SELECT TO chatbi_app
    USING (dataset_id IN ('ecommerce_mock_v1', 'ecommerce_empty_day_fixture_v1'));

CREATE POLICY chatbi_app_read_channels
    ON public.channels
    FOR SELECT TO chatbi_app
    USING (dataset_id IN ('ecommerce_mock_v1', 'ecommerce_empty_day_fixture_v1'));

-- This application does not use Supabase Data API or client-side database access.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE ALL ON SEQUENCES FROM anon, authenticated;
