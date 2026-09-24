# 11 — Dependency Graph

`referencing -> referenced` (from sys.sql_expression_dependencies).

| referencing object | referencing type | -> referenced | referenced type |
| --- | --- | --- | --- |
| vw_AIStockMetrics | VIEW | dbo.fn_JalaliKey | OBJECT_OR_COLUMN |
| vw_AIStockMetrics | VIEW | dbo.mahane | OBJECT_OR_COLUMN |
| vw_AIStockMetrics | VIEW | dbo.MarketPriceHistory | OBJECT_OR_COLUMN |
| vw_AIStockMetrics | VIEW | dbo.miandore2 | OBJECT_OR_COLUMN |
| vw_AIStockMetrics2 | VIEW | dbo.fn_JalaliKey | OBJECT_OR_COLUMN |
| vw_AIStockMetrics2 | VIEW | dbo.mahane | OBJECT_OR_COLUMN |
| vw_AIStockMetrics2 | VIEW | dbo.MarketPriceHistory | OBJECT_OR_COLUMN |
| vw_AIStockMetrics2 | VIEW | dbo.miandore2 | OBJECT_OR_COLUMN |
| vw_AIStockMetrics3 | VIEW | dbo.fn_JalaliKey | OBJECT_OR_COLUMN |
| vw_AIStockMetrics3 | VIEW | dbo.mahane | OBJECT_OR_COLUMN |
| vw_AIStockMetrics3 | VIEW | dbo.MarketPriceHistory | OBJECT_OR_COLUMN |
| vw_AIStockMetrics3 | VIEW | dbo.miandore2 | OBJECT_OR_COLUMN |

## Text graph

- vw_AIStockMetrics (VIEW)  ->  dbo.fn_JalaliKey (OBJECT_OR_COLUMN)
- vw_AIStockMetrics (VIEW)  ->  dbo.mahane (OBJECT_OR_COLUMN)
- vw_AIStockMetrics (VIEW)  ->  dbo.MarketPriceHistory (OBJECT_OR_COLUMN)
- vw_AIStockMetrics (VIEW)  ->  dbo.miandore2 (OBJECT_OR_COLUMN)
- vw_AIStockMetrics2 (VIEW)  ->  dbo.fn_JalaliKey (OBJECT_OR_COLUMN)
- vw_AIStockMetrics2 (VIEW)  ->  dbo.mahane (OBJECT_OR_COLUMN)
- vw_AIStockMetrics2 (VIEW)  ->  dbo.MarketPriceHistory (OBJECT_OR_COLUMN)
- vw_AIStockMetrics2 (VIEW)  ->  dbo.miandore2 (OBJECT_OR_COLUMN)
- vw_AIStockMetrics3 (VIEW)  ->  dbo.fn_JalaliKey (OBJECT_OR_COLUMN)
- vw_AIStockMetrics3 (VIEW)  ->  dbo.mahane (OBJECT_OR_COLUMN)
- vw_AIStockMetrics3 (VIEW)  ->  dbo.MarketPriceHistory (OBJECT_OR_COLUMN)
- vw_AIStockMetrics3 (VIEW)  ->  dbo.miandore2 (OBJECT_OR_COLUMN)
