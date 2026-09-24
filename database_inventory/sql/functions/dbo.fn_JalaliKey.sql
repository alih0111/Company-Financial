CREATE   FUNCTION dbo.fn_JalaliKey
(
    @date NVARCHAR(30)
)
RETURNS INT
AS
BEGIN
    DECLARE @d NVARCHAR(30);
    DECLARE @p1 INT;
    DECLARE @p2 INT;
    DECLARE @y INT;
    DECLARE @m INT;
    DECLARE @day INT;

    SET @d = LTRIM(RTRIM(REPLACE(REPLACE(@date, N'-', N'/'), N' ', N'')));
    SET @p1 = CHARINDEX(N'/', @d);
    SET @p2 = CASE WHEN @p1 > 0 THEN CHARINDEX(N'/', @d, @p1 + 1) ELSE 0 END;

    IF @d IS NULL OR @p1 = 0 OR @p2 = 0
        RETURN NULL;

    SET @y = TRY_CONVERT(INT, SUBSTRING(@d, 1, @p1 - 1));
    SET @m = TRY_CONVERT(INT, SUBSTRING(@d, @p1 + 1, @p2 - @p1 - 1));
    SET @day = TRY_CONVERT(INT, SUBSTRING(@d, @p2 + 1, 2));

    IF @y IS NULL OR @m IS NULL OR @day IS NULL
        RETURN NULL;

    IF @m < 1 OR @m > 12 OR @day < 1 OR @day > 31
        RETURN NULL;

    RETURN (@y * 10000) + (@m * 100) + @day;
END;
