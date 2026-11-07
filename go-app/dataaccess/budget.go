// Package dataaccess accounts for data delivered to non-administrator accounts.
// All workers and sessions share PostgreSQL budgets; a restart does not reset it.
package dataaccess

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"database/sql"
	"fmt"
	"go-app/config"
	"net/netip"
	"strings"
	"time"
)

var Tehran = time.FixedZone("Asia/Tehran", 12600)

type Cost struct {
	Requests, Records, Bytes int64
	Targets                  []string
}
type Status struct {
	Enabled    bool              `json:"enabled"`
	Unlimited  bool              `json:"unlimited"`
	Limits     config.DataLimits `json:"limits"`
	Used       config.DataLimits `json:"used"`
	Denied     int64             `json:"denied"`
	LastDenial string            `json:"last_denial,omitempty"`
	ResetsAt   time.Time         `json:"resets_at"`
}
type Denied struct {
	Reason string
	Reset  time.Time
}

func (e *Denied) Error() string { return "data access limit: " + e.Reason }

func digest(value string) []byte {
	h := hmac.New(sha256.New, config.JWTSecret())
	h.Write([]byte("data-budget-v1:" + value))
	return h.Sum(nil)
}
func normalize(value string) string {
	value = strings.NewReplacer("ي", "ی", "ك", "ک", "\u200c", " ").Replace(strings.TrimSpace(value))
	return strings.ToLower(strings.Join(strings.Fields(value), ""))
}
func ipIdentity(ip string) string {
	addr, err := netip.ParseAddr(ip)
	if err != nil {
		return "unknown"
	}
	addr = addr.Unmap()
	if addr.Is6() {
		return netip.PrefixFrom(addr, 64).Masked().String()
	}
	return addr.String()
}
func resetAt(now time.Time) time.Time {
	local := now.In(Tehran)
	return time.Date(local.Year(), local.Month(), local.Day()+1, 0, 0, 0, 0, Tehran)
}

// Reserve commits either the full cost or a denial counter. Row locks serialize
// concurrent requests, including requests from different API processes.
func Reserve(ctx context.Context, db *sql.DB, username, ip string, cost Cost) (Status, error) {
	var status Status
	defaults, err := config.DefaultDataLimits()
	if err != nil {
		return status, err
	}
	if cost.Requests < 0 || cost.Records < 0 || cost.Bytes < 0 || len(cost.Targets) > 50 {
		return status, fmt.Errorf("invalid data cost")
	}
	now := time.Now()
	day := now.In(Tehran).Format("2006-01-02")
	status.ResetsAt = resetAt(now)
	status.Limits = defaults
	status.Enabled = true
	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		return status, err
	}
	defer tx.Rollback()
	var userID string
	var admin bool
	err = tx.QueryRowContext(ctx, `SELECT id::text,is_admin FROM auth.users WHERE username=$1 AND is_active=true`, username).Scan(&userID, &admin)
	if err != nil {
		return status, err
	}
	if admin {
		status.Unlimited = true
		return status, nil
	}
	err = tx.QueryRowContext(ctx, `SELECT enabled,requests_limit,records_limit,bytes_limit,symbols_limit FROM auth.data_policies WHERE user_id=$1`, userID).Scan(&status.Enabled, &status.Limits.Requests, &status.Limits.Records, &status.Limits.Bytes, &status.Limits.Symbols)
	if err != nil && err != sql.ErrNoRows {
		return status, err
	}
	ipHash := digest("ip:" + ipIdentity(ip))
	if _, err = tx.ExecContext(ctx, `INSERT INTO auth.data_ip_usage(day,ip_hash) VALUES($1,$2) ON CONFLICT DO NOTHING`, day, ipHash); err != nil {
		return status, err
	}
	var ipRequests, ipRecords, ipBytes int64
	if err = tx.QueryRowContext(ctx, `SELECT requests,records,bytes FROM auth.data_ip_usage WHERE day=$1 AND ip_hash=$2 FOR UPDATE`, day, ipHash).Scan(&ipRequests, &ipRecords, &ipBytes); err != nil {
		return status, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO auth.data_usage(user_id,day) VALUES($1,$2) ON CONFLICT DO NOTHING`, userID, day); err != nil {
		return status, err
	}
	if err = tx.QueryRowContext(ctx, `SELECT requests,records,bytes,symbols,denied,last_denial FROM auth.data_usage WHERE user_id=$1 AND day=$2 FOR UPDATE`, userID, day).Scan(&status.Used.Requests, &status.Used.Records, &status.Used.Bytes, &status.Used.Symbols, &status.Denied, &status.LastDenial); err != nil {
		return status, err
	}
	hashes := map[string][]byte{}
	for _, target := range cost.Targets {
		target = normalize(target)
		if target == "" || len(target) > 300 {
			return status, fmt.Errorf("invalid data target")
		}
		hash := digest("symbol:" + target)
		var exists bool
		if err = tx.QueryRowContext(ctx, `SELECT EXISTS(SELECT 1 FROM auth.data_targets WHERE user_id=$1 AND day=$2 AND target_hash=$3)`, userID, day, hash).Scan(&exists); err != nil {
			return status, err
		}
		if !exists {
			hashes[string(hash)] = hash
		}
	}
	reason := ""
	switch {
	case !status.Enabled:
		reason = "disabled"
	case status.Used.Requests+cost.Requests > status.Limits.Requests:
		reason = "daily_requests"
	case status.Used.Records+cost.Records > status.Limits.Records:
		reason = "daily_records"
	case status.Used.Bytes+cost.Bytes > status.Limits.Bytes:
		reason = "daily_bytes"
	case status.Used.Symbols+int64(len(hashes)) > status.Limits.Symbols:
		reason = "daily_symbols"
	case ipRequests+cost.Requests > defaults.Requests*10 || ipRecords+cost.Records > defaults.Records*10 || ipBytes+cost.Bytes > defaults.Bytes*10:
		reason = "shared_network_budget"
	}
	if reason != "" {
		if _, err = tx.ExecContext(ctx, `UPDATE auth.data_usage SET denied=denied+1,last_denial=$3,updated_at=now() WHERE user_id=$1 AND day=$2`, userID, day, reason); err != nil {
			return status, err
		}
		if err = tx.Commit(); err != nil {
			return status, err
		}
		status.Denied++
		status.LastDenial = reason
		return status, &Denied{reason, status.ResetsAt}
	}
	for _, hash := range hashes {
		if _, err = tx.ExecContext(ctx, `INSERT INTO auth.data_targets(user_id,day,target_hash) VALUES($1,$2,$3)`, userID, day, hash); err != nil {
			return status, err
		}
	}
	if _, err = tx.ExecContext(ctx, `UPDATE auth.data_ip_usage SET requests=requests+$3,records=records+$4,bytes=bytes+$5 WHERE day=$1 AND ip_hash=$2`, day, ipHash, cost.Requests, cost.Records, cost.Bytes); err != nil {
		return status, err
	}
	if _, err = tx.ExecContext(ctx, `UPDATE auth.data_usage SET requests=requests+$3,records=records+$4,bytes=bytes+$5,symbols=symbols+$6,updated_at=now() WHERE user_id=$1 AND day=$2`, userID, day, cost.Requests, cost.Records, cost.Bytes, len(hashes)); err != nil {
		return status, err
	}
	if err = tx.Commit(); err != nil {
		return status, err
	}
	status.Used.Requests += cost.Requests
	status.Used.Records += cost.Records
	status.Used.Bytes += cost.Bytes
	status.Used.Symbols += int64(len(hashes))
	return status, nil
}

// ReadStatus never spends a budget, so a limited user can still see when access
// returns, manage their own portfolio and sign out.
func ReadStatus(ctx context.Context, db *sql.DB, username string) (Status, error) {
	limits, err := config.DefaultDataLimits()
	status := Status{Enabled: true, Limits: limits, ResetsAt: resetAt(time.Now())}
	if err != nil {
		return status, err
	}
	var userID string
	if err = db.QueryRowContext(ctx, `SELECT id::text,is_admin FROM auth.users WHERE username=$1 AND is_active=true`, username).Scan(&userID, &status.Unlimited); err != nil {
		return status, err
	}
	err = db.QueryRowContext(ctx, `SELECT enabled,requests_limit,records_limit,bytes_limit,symbols_limit FROM auth.data_policies WHERE user_id=$1`, userID).Scan(&status.Enabled, &status.Limits.Requests, &status.Limits.Records, &status.Limits.Bytes, &status.Limits.Symbols)
	if err != nil && err != sql.ErrNoRows {
		return status, err
	}
	err = db.QueryRowContext(ctx, `SELECT requests,records,bytes,symbols,denied,last_denial FROM auth.data_usage WHERE user_id=$1 AND day=$2`, userID, time.Now().In(Tehran).Format("2006-01-02")).Scan(&status.Used.Requests, &status.Used.Records, &status.Used.Bytes, &status.Used.Symbols, &status.Denied, &status.LastDenial)
	if err == sql.ErrNoRows {
		err = nil
	}
	return status, err
}
