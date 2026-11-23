CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE TABLE customers (
    customer_id text PRIMARY KEY,
    idp_issuer text NOT NULL,
    subject text NOT NULL,
    UNIQUE (idp_issuer, subject)
);
CREATE TABLE device_ownership (
    device_id text NOT NULL,
    customer_id text NOT NULL REFERENCES customers,
    model text NOT NULL,
    valid_from timestamptz NOT NULL,
    valid_to timestamptz,
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    EXCLUDE USING gist (device_id WITH =, tstzrange(valid_from, valid_to, '[)') WITH &&)
);
CREATE ROLE crm_reader LOGIN PASSWORD 'demo_crm_reader';
GRANT CONNECT ON DATABASE crm TO crm_reader;
GRANT USAGE ON SCHEMA public TO crm_reader;
GRANT SELECT ON customers, device_ownership TO crm_reader;
