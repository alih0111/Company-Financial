-- 115_market_meta.sql — Industry classification + share structure of companies (source: TSETMC via BRS)
--
-- data source: Api.BrsApi.ir/Tsetmc/AllSymbols.php (cs/cs_id = TSETMC industry category,
-- z = shares outstanding, mv = market value rial), matched to canonical
-- core.securities.tsetmc_ins_code.
--
-- core.company_classification: current industry/board category of the company with PIT validity —
-- each category change = closing the previous row (valid_to) and inserting a new row.
-- core.share_structure: daily snapshot of shares count / market value / EPS (append-only,
-- for capacity calculation and cap-based weighting).

CREATE TABLE IF NOT EXISTS core.company_classification (
    id              bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id      uuid        NOT NULL REFERENCES core.companies(id) ON DELETE CASCADE,
    security_id     uuid        REFERENCES core.securities(id) ON DELETE SET NULL,
    tsetmc_ins_code text,
    category        text        NOT NULL,
    category_id     integer,
    source          text        NOT NULL DEFAULT 'brs_all_symbols',
    valid_from      date        NOT NULL DEFAULT current_date,
    valid_to        date,
    collected_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_company_classification_current
    ON core.company_classification (company_id, valid_from)
    WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS ix_company_classification_company
    ON core.company_classification (company_id, valid_from DESC);

CREATE TABLE IF NOT EXISTS core.share_structure (
    id                bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    security_id       uuid        NOT NULL REFERENCES core.securities(id) ON DELETE CASCADE,
    company_id        uuid,
    shares_count      numeric(24,0),
    market_value_rial numeric(30,4),
    eps_rial          numeric(24,4),
    as_of_date        date        NOT NULL,
    source            text        NOT NULL DEFAULT 'brs_all_symbols',
    collected_at      timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_share_structure_security_date
    ON core.share_structure (security_id, as_of_date);
CREATE INDEX IF NOT EXISTS ix_share_structure_security
    ON core.share_structure (security_id, as_of_date DESC);
