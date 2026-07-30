-- ============================================================================
--  Migration: افزودن ستون‌های درآمد عملیاتی به جدول miandore2
--
--  هدف: محاسبه حاشیه سود عملیاتی (Operating Profit Margin)
--       Operation = OperatingProfitNew / RevenueNew * 100
--
--  این اسکریپت را یک‌بار روی دیتابیس codal اجرا کنید.
--  ستون‌ها NULL باقی می‌مانند تا زمانی که گزارش‌ها مجدداً scrape شوند.
-- ============================================================================

USE [codal]
GO

IF COL_LENGTH('dbo.miandore2', 'RevenueNew') IS NULL
BEGIN
    ALTER TABLE dbo.miandore2
    ADD RevenueNew FLOAT NULL
END
GO

IF COL_LENGTH('dbo.miandore2', 'RevenueLastYear') IS NULL
BEGIN
    ALTER TABLE dbo.miandore2
    ADD RevenueLastYear FLOAT NULL
END
GO
