package integration

import (
	"context"
	"fmt"
	"strings"
)

// market_meta.go — صنعت/طبقه‌بندی و ساختار سهام شرکت‌ها (منبع: TSETMC از طریق
// کالکتور BRS در go-app/py/sync_market_meta.py). برای سقف صنعتی سبد و گزارش
// پرتفوی مصرف می‌شود.

// MarketMetaRow متادیتای بازار یک شرکت.
type MarketMetaRow struct {
	LegacyCompanyID string
	Category        string
	SharesCount     float64
	MarketValueRial float64
	AsOfDate        string
}

// MarketMetaByLegacyCompanyIDs صنعتِ جاری و آخرین snapshot ساختار سهام هر شرکت
// را برمی‌گرداند؛ شرکت‌هایی که متادیتا ندارند در خروجی نیستند.
func (p *PG) MarketMetaByLegacyCompanyIDs(ctx context.Context, ids []string) ([]MarketMetaRow, error) {
	if p == nil || p.db == nil {
		return nil, fmt.Errorf("canonical postgres not configured")
	}
	if len(ids) == 0 {
		return nil, nil
	}
	const q = `
		WITH want AS (SELECT unnest(string_to_array($1, ',')) AS legacy_key),
		cls AS (
			SELECT lem.legacy_key, cc.category
			FROM core.company_classification cc
			JOIN core.legacy_entity_map lem
			  ON lem.entity_type = 'company' AND lem.target_uuid = cc.company_id
			 AND lem.legacy_key ~ '^[0-9a-f]{32}$'
			JOIN want w ON w.legacy_key = lem.legacy_key
			WHERE cc.valid_to IS NULL
		),
		ss AS (
			SELECT DISTINCT ON (lem.legacy_key)
			       lem.legacy_key, x.shares_count, x.market_value_rial, x.as_of_date::text AS as_of
			FROM core.share_structure x
			JOIN core.legacy_entity_map lem
			  ON lem.entity_type = 'company' AND lem.target_uuid = x.company_id
			 AND lem.legacy_key ~ '^[0-9a-f]{32}$'
			JOIN want w ON w.legacy_key = lem.legacy_key
			ORDER BY lem.legacy_key, x.as_of_date DESC
		)
		SELECT COALESCE(cls.legacy_key, ss.legacy_key),
		       COALESCE(cls.category, ''),
		       COALESCE(ss.shares_count, 0),
		       COALESCE(ss.market_value_rial, 0),
		       COALESCE(ss.as_of, '')
		FROM cls
		FULL JOIN ss ON ss.legacy_key = cls.legacy_key`
	rows, err := p.db.QueryContext(ctx, q, strings.Join(ids, ","))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]MarketMetaRow, 0, len(ids))
	for rows.Next() {
		var r MarketMetaRow
		if err := rows.Scan(&r.LegacyCompanyID, &r.Category, &r.SharesCount, &r.MarketValueRial, &r.AsOfDate); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}
