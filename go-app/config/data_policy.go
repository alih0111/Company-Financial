package config

import (
	"fmt"
	"os"
	"strconv"
)

type DataLimits struct {
	Requests int64 `json:"requests"`
	Records  int64 `json:"records"`
	Bytes    int64 `json:"bytes"`
	Symbols  int64 `json:"symbols"`
}

func (l DataLimits) Valid() bool {
	return l.Requests >= 10 && l.Requests <= 10000 && l.Records >= 100 && l.Records <= 200000 && l.Bytes >= 65536 && l.Bytes <= 256<<20 && l.Symbols >= 1 && l.Symbols <= 1000
}

func DefaultDataLimits() (DataLimits, error) {
	values := []int64{300, 12000, 8 << 20, 40}
	for i, key := range []string{"CDF_DATA_DAILY_REQUESTS", "CDF_DATA_DAILY_RECORDS", "CDF_DATA_DAILY_BYTES", "CDF_DATA_DAILY_SYMBOLS"} {
		if raw := os.Getenv(key); raw != "" {
			n, err := strconv.ParseInt(raw, 10, 64)
			if err != nil {
				return DataLimits{}, fmt.Errorf("invalid %s", key)
			}
			values[i] = n
		}
	}
	limits := DataLimits{values[0], values[1], values[2], values[3]}
	if !limits.Valid() {
		return limits, fmt.Errorf("data limits outside supported bounds")
	}
	return limits, nil
}
