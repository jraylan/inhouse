

CREATE OR REPLACE FUNCTION mmr (mu float4, sigma float4) returns float4 as $$
BEGIN
RETURN 20 * (mu - 3  * sigma + 25);
END
$$ LANGUAGE plpgsql;