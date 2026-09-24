# 05 — Indexes


### dbo.CodalReports :: PK__CodalRep__3214EC0745ABAB41
| property | value |
| --- | --- |
| type | CLUSTERED |
| unique | YES |
| primary_key | YES |
| unique_constraint | NO |
| key_columns | Id |
| included_columns | (none) |
| filtered | NO |

### dbo.CodalReports :: UX_CodalReports_ReportId
| property | value |
| --- | --- |
| type | NONCLUSTERED |
| unique | YES |
| primary_key | NO |
| unique_constraint | NO |
| key_columns | CodalReportId |
| included_columns | (none) |
| filtered | NO |

### dbo.CodalReports :: IX_CodalReports_LetterType_Status
| property | value |
| --- | --- |
| type | NONCLUSTERED |
| unique | NO |
| primary_key | NO |
| unique_constraint | NO |
| key_columns | LetterType, Status |
| included_columns | (none) |
| filtered | NO |

### dbo.CodalSyncState :: PK__CodalSyn__ED488CD1B7444E93
| property | value |
| --- | --- |
| type | CLUSTERED |
| unique | YES |
| primary_key | YES |
| unique_constraint | NO |
| key_columns | LetterType |
| included_columns | (none) |
| filtered | NO |

### dbo.FamilyAccounts :: PK__FamilyAc__AA2FFB856B792986
| property | value |
| --- | --- |
| type | CLUSTERED |
| unique | YES |
| primary_key | YES |
| unique_constraint | NO |
| key_columns | PersonID |
| included_columns | (none) |
| filtered | NO |

### dbo.FamilyAssets :: PK__FamilyAs__43492372E36C84C3
| property | value |
| --- | --- |
| type | CLUSTERED |
| unique | YES |
| primary_key | YES |
| unique_constraint | NO |
| key_columns | AssetID |
| included_columns | (none) |
| filtered | NO |

### dbo.FamilyCashFlows :: PK__FamilyCa__3214EC27C9167FF6
| property | value |
| --- | --- |
| type | CLUSTERED |
| unique | YES |
| primary_key | YES |
| unique_constraint | NO |
| key_columns | ID |
| included_columns | (none) |
| filtered | NO |

### dbo.FamilyHistory :: PK__FamilyHi__40DF45E3EBB25058
| property | value |
| --- | --- |
| type | CLUSTERED |
| unique | YES |
| primary_key | YES |
| unique_constraint | NO |
| key_columns | DateKey |
| included_columns | (none) |
| filtered | NO |

### dbo.FamilyHoldings :: PK_FamilyHoldings
| property | value |
| --- | --- |
| type | CLUSTERED |
| unique | YES |
| primary_key | YES |
| unique_constraint | NO |
| key_columns | PersonID, AssetID |
| included_columns | (none) |
| filtered | NO |

### dbo.FamilyPeople :: PK__FamilyPe__AA2FFB85A938357F
| property | value |
| --- | --- |
| type | CLUSTERED |
| unique | YES |
| primary_key | YES |
| unique_constraint | NO |
| key_columns | PersonID |
| included_columns | (none) |
| filtered | NO |

### dbo.FamilyPrices :: PK_FamilyPrices
| property | value |
| --- | --- |
| type | CLUSTERED |
| unique | YES |
| primary_key | YES |
| unique_constraint | NO |
| key_columns | DateKey, AssetID |
| included_columns | (none) |
| filtered | NO |

### dbo.FullPE :: PK_FullPE
| property | value |
| --- | --- |
| type | CLUSTERED |
| unique | YES |
| primary_key | YES |
| unique_constraint | NO |
| key_columns | CompanyName |
| included_columns | (none) |
| filtered | NO |

### dbo.mahane :: PK_mahane
| property | value |
| --- | --- |
| type | CLUSTERED |
| unique | YES |
| primary_key | YES |
| unique_constraint | NO |
| key_columns | CompanyID, ReportDate |
| included_columns | (none) |
| filtered | NO |

### dbo.mahane :: IX_mahane_Company_ReportDate
| property | value |
| --- | --- |
| type | NONCLUSTERED |
| unique | NO |
| primary_key | NO |
| unique_constraint | NO |
| key_columns | CompanyID, ReportDate |
| included_columns | CompanyName, Value1, Value2, Value3, LastModificationDate |
| filtered | NO |

### dbo.MarketPriceHistory :: PK_MarketPriceHistory_Instrument_Date
| property | value |
| --- | --- |
| type | CLUSTERED |
| unique | YES |
| primary_key | YES |
| unique_constraint | NO |
| key_columns | InstrumentCode, GregorianDate |
| included_columns | (none) |
| filtered | NO |

### dbo.MarketPriceHistory :: IX_MarketPriceHistory_Company_Date
| property | value |
| --- | --- |
| type | NONCLUSTERED |
| unique | NO |
| primary_key | NO |
| unique_constraint | NO |
| key_columns | CompanyID, GregorianDate |
| included_columns | CompanyName, Symbol, ClosingPrice, LastPrice, HighPrice, LowPrice, TradeValue, Volume, TradeCount, ClosingChangePercent, CollectedAt |
| filtered | NO |

### dbo.miandore :: PK__miandore__A5B12462B09FEA0E
| property | value |
| --- | --- |
| type | CLUSTERED |
| unique | YES |
| primary_key | YES |
| unique_constraint | NO |
| key_columns | CompanyID, ReportDate |
| included_columns | (none) |
| filtered | NO |

### dbo.miandore2 :: PK__miandore__A5B12462AA778394
| property | value |
| --- | --- |
| type | CLUSTERED |
| unique | YES |
| primary_key | YES |
| unique_constraint | NO |
| key_columns | CompanyID, ReportDate |
| included_columns | (none) |
| filtered | NO |

### dbo.miandore2 :: IX_miandore2_Company_ReportDate
| property | value |
| --- | --- |
| type | NONCLUSTERED |
| unique | NO |
| primary_key | NO |
| unique_constraint | NO |
| key_columns | CompanyID, ReportDate |
| included_columns | CompanyName, Num1_Value1, Num2_Value1, Num4_Value1, Product1, OperatingProfitNew, OperatingProfitLastYear |
| filtered | NO |

### dbo.statements :: PK__statemen__3214EC2748CBBC10
| property | value |
| --- | --- |
| type | CLUSTERED |
| unique | YES |
| primary_key | YES |
| unique_constraint | NO |
| key_columns | ID |
| included_columns | (none) |
| filtered | NO |

### dbo.statements :: UQ_statements_row
| property | value |
| --- | --- |
| type | NONCLUSTERED |
| unique | YES |
| primary_key | NO |
| unique_constraint | YES |
| key_columns | CompanyID, ReportDate, StatementType, MetricCode, PeriodOrder |
| included_columns | (none) |
| filtered | NO |

### dbo.StockData :: PK_Stock
| property | value |
| --- | --- |
| type | CLUSTERED |
| unique | YES |
| primary_key | YES |
| unique_constraint | NO |
| key_columns | Ticker, TradeDate |
| included_columns | (none) |
| filtered | NO |

### dbo.StockPrices :: PK_CompanyName_Date
| property | value |
| --- | --- |
| type | CLUSTERED |
| unique | YES |
| primary_key | YES |
| unique_constraint | NO |
| key_columns | CompanyName, date |
| included_columns | (none) |
| filtered | NO |

### dbo.TrackedTickers :: PK__TrackedT__B7CC3F002A5D039A
| property | value |
| --- | --- |
| type | CLUSTERED |
| unique | YES |
| primary_key | YES |
| unique_constraint | NO |
| key_columns | Symbol |
| included_columns | (none) |
| filtered | NO |
