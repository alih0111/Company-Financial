-- ============================================================================
--  ستون‌های صورت وضعیت مالی (ترازنامه) و صورت جریان‌های نقدی برای miandore2
--  این مقادیر از همان صفحه‌ی گزارش CODAL (همان که سود و زیان از آن خوانده
--  می‌شود) با انتخاب «صورت وضعیت مالی» و «صورت جریان‌های نقدی» استخراج
--  می‌شوند و در ردیف همان گزارش ذخیره می‌شوند.
--
--  ستون‌های ...LY مقدار پایان دوره/سال قبل هستند (ستون دوم ترازنامه).
--  جریان نقدی عملیاتی همانند سود، از ابتدای سال مالی «تجمعی» است.
-- ============================================================================
USE [codal]
GO

IF COL_LENGTH('dbo.miandore2', 'TotalAssets') IS NULL
    ALTER TABLE dbo.miandore2 ADD TotalAssets FLOAT NULL;
GO
IF COL_LENGTH('dbo.miandore2', 'TotalAssetsLY') IS NULL
    ALTER TABLE dbo.miandore2 ADD TotalAssetsLY FLOAT NULL;
GO
IF COL_LENGTH('dbo.miandore2', 'CurrentAssets') IS NULL
    ALTER TABLE dbo.miandore2 ADD CurrentAssets FLOAT NULL;
GO
IF COL_LENGTH('dbo.miandore2', 'CurrentAssetsLY') IS NULL
    ALTER TABLE dbo.miandore2 ADD CurrentAssetsLY FLOAT NULL;
GO
IF COL_LENGTH('dbo.miandore2', 'TotalLiabilities') IS NULL
    ALTER TABLE dbo.miandore2 ADD TotalLiabilities FLOAT NULL;
GO
IF COL_LENGTH('dbo.miandore2', 'TotalLiabilitiesLY') IS NULL
    ALTER TABLE dbo.miandore2 ADD TotalLiabilitiesLY FLOAT NULL;
GO
IF COL_LENGTH('dbo.miandore2', 'CurrentLiabilities') IS NULL
    ALTER TABLE dbo.miandore2 ADD CurrentLiabilities FLOAT NULL;
GO
IF COL_LENGTH('dbo.miandore2', 'CurrentLiabilitiesLY') IS NULL
    ALTER TABLE dbo.miandore2 ADD CurrentLiabilitiesLY FLOAT NULL;
GO
IF COL_LENGTH('dbo.miandore2', 'TotalEquity') IS NULL
    ALTER TABLE dbo.miandore2 ADD TotalEquity FLOAT NULL;
GO
IF COL_LENGTH('dbo.miandore2', 'TotalEquityLY') IS NULL
    ALTER TABLE dbo.miandore2 ADD TotalEquityLY FLOAT NULL;
GO
IF COL_LENGTH('dbo.miandore2', 'OperatingCashFlow') IS NULL
    ALTER TABLE dbo.miandore2 ADD OperatingCashFlow FLOAT NULL;
GO
IF COL_LENGTH('dbo.miandore2', 'OperatingCashFlowLY') IS NULL
    ALTER TABLE dbo.miandore2 ADD OperatingCashFlowLY FLOAT NULL;
GO

-- ============================================================================
--  مقادیر واقعی ردیف‌های جدول (واحد هماهنگ با خود جدول — معمولاً میلیون ریال)
--  سه ستون دوره در گزارش CODAL: دوره جاری / دوره مشابه سال قبل / س سال قبل
--  → TTM دقیق از «یک» گزارش: col1 + col3 - col2
-- ============================================================================
IF COL_LENGTH('dbo.miandore2', 'NetProfitAmount') IS NULL
    ALTER TABLE dbo.miandore2 ADD NetProfitAmount FLOAT NULL;
GO
IF COL_LENGTH('dbo.miandore2', 'NetProfitAmountLY') IS NULL
    ALTER TABLE dbo.miandore2 ADD NetProfitAmountLY FLOAT NULL;
GO
IF COL_LENGTH('dbo.miandore2', 'NetProfitAmountFYPrev') IS NULL
    ALTER TABLE dbo.miandore2 ADD NetProfitAmountFYPrev FLOAT NULL;
GO
IF COL_LENGTH('dbo.miandore2', 'OperatingProfitFYPrev') IS NULL
    ALTER TABLE dbo.miandore2 ADD OperatingProfitFYPrev FLOAT NULL;
GO
IF COL_LENGTH('dbo.miandore2', 'RevenueFYPrev') IS NULL
    ALTER TABLE dbo.miandore2 ADD RevenueFYPrev FLOAT NULL;
GO
IF COL_LENGTH('dbo.miandore2', 'OperatingCashFlowFYPrev') IS NULL
    ALTER TABLE dbo.miandore2 ADD OperatingCashFlowFYPrev FLOAT NULL;
GO
