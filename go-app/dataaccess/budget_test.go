package dataaccess

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"go-app/config"
	"net/url"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func isolatedBudgetDB(t *testing.T) *sql.DB {
	t.Helper()
	dsn := os.Getenv("RFA_DEPLOY_TEST_DSN")
	if dsn == "" {
		t.Skip("requires isolated PostgreSQL")
	}
	u, err := url.Parse(dsn)
	if err != nil || !strings.HasPrefix(u.Path, "/company_financial_test_") || (u.Hostname() != "127.0.0.1" && u.Hostname() != "localhost") {
		t.Fatal("unsafe test database")
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { db.Close() })
	return db
}
func budgetUser(t *testing.T, db *sql.DB, limits config.DataLimits) string {
	t.Helper()
	name := fmt.Sprintf("budget_%d", time.Now().UnixNano())
	var id string
	if err := db.QueryRow(`INSERT INTO auth.users(username,email,password_hash) VALUES($1,$2,'not-a-login-hash') RETURNING id::text`, name, name+"@example.com").Scan(&id); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { db.Exec(`DELETE FROM auth.users WHERE id=$1`, id) })
	if _, err := db.Exec(`INSERT INTO auth.data_policies(user_id,requests_limit,records_limit,bytes_limit,symbols_limit) VALUES($1,$2,$3,$4,$5)`, id, limits.Requests, limits.Records, limits.Bytes, limits.Symbols); err != nil {
		t.Fatal(err)
	}
	return name
}

func TestDurableBudgetSerializesConcurrentReaders(t *testing.T) {
	db := isolatedBudgetDB(t)
	user := budgetUser(t, db, config.DataLimits{Requests: 10, Records: 100, Bytes: 65536, Symbols: 40})
	var successes, denials atomic.Int64
	var workers sync.WaitGroup
	for i := 0; i < 24; i++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			_, err := Reserve(context.Background(), db, user, "192.0.2.17", Cost{Requests: 1})
			var denied *Denied
			if err == nil {
				successes.Add(1)
			} else if errors.As(err, &denied) && denied.Reason == "daily_requests" {
				denials.Add(1)
			} else {
				t.Errorf("reserve: %v", err)
			}
		}()
	}
	workers.Wait()
	if successes.Load() != 10 || denials.Load() != 14 {
		t.Fatalf("overspent concurrent budget: %d successes, %d denials", successes.Load(), denials.Load())
	}
	// A new connection, a different IP and deletion of all browser sessions cannot
	// replenish the account's durable budget.
	other := isolatedBudgetDB(t)
	other.Exec(`DELETE FROM auth.sessions WHERE user_id=(SELECT id FROM auth.users WHERE username=$1)`, user)
	_, err := Reserve(context.Background(), other, user, "192.0.2.18", Cost{Requests: 1})
	var denied *Denied
	if !errors.As(err, &denied) {
		t.Fatal("changing IP/connections reset the daily allowance")
	}
	status, err := ReadStatus(context.Background(), other, user)
	if err != nil || status.Used.Requests != 10 || status.Denied != 15 {
		t.Fatalf("durable status: %+v %v", status, err)
	}
}

func TestSymbolAndDeliveryBudgetsAreAtomic(t *testing.T) {
	db := isolatedBudgetDB(t)
	user := budgetUser(t, db, config.DataLimits{Requests: 100, Records: 100, Bytes: 65536, Symbols: 1})
	for _, target := range []string{"کيان", "کیان"} {
		if _, err := Reserve(context.Background(), db, user, "192.0.2.19", Cost{Requests: 1, Targets: []string{target, target}}); err != nil {
			t.Fatal(err)
		}
	}
	_, err := Reserve(context.Background(), db, user, "192.0.2.19", Cost{Requests: 1, Targets: []string{"فولاد"}})
	var denied *Denied
	if !errors.As(err, &denied) || denied.Reason != "daily_symbols" {
		t.Fatal("distinct company budget bypassed")
	}
	status, _ := ReadStatus(context.Background(), db, user)
	if status.Used.Symbols != 1 || status.Used.Requests != 2 {
		t.Fatal("denied reservation partially committed")
	}
	_, err = Reserve(context.Background(), db, user, "192.0.2.19", Cost{Records: 101, Bytes: 1000})
	if !errors.As(err, &denied) || denied.Reason != "daily_records" {
		t.Fatal("row budget bypassed")
	}
	status, _ = ReadStatus(context.Background(), db, user)
	if status.Used.Records != 0 || status.Used.Bytes != 0 {
		t.Fatal("response delivered without atomic budget")
	}
	_, err = Reserve(context.Background(), db, user, "192.0.2.19", Cost{Bytes: 65537})
	if !errors.As(err, &denied) || denied.Reason != "daily_bytes" {
		t.Fatal("byte budget bypassed")
	}
}

func TestSharedNetworkAndDisabledAccount(t *testing.T) {
	t.Setenv("CDF_DATA_DAILY_REQUESTS", "10")
	db := isolatedBudgetDB(t)
	limits := config.DataLimits{Requests: 1000, Records: 10000, Bytes: 1 << 20, Symbols: 40}
	first := budgetUser(t, db, limits)
	second := budgetUser(t, db, limits)
	// Use an independent test subnet/day entry and remove it after the test.
	hash := digest("ip:" + ipIdentity("2001:db8:17::1"))
	day := time.Now().In(Tehran).Format("2006-01-02")
	db.Exec(`DELETE FROM auth.data_ip_usage WHERE day=$1 AND ip_hash=$2`, day, hash)
	t.Cleanup(func() { db.Exec(`DELETE FROM auth.data_ip_usage WHERE day=$1 AND ip_hash=$2`, day, hash) })
	if _, err := Reserve(context.Background(), db, first, "2001:db8:17::1", Cost{Requests: 100}); err != nil {
		t.Fatal(err)
	}
	_, err := Reserve(context.Background(), db, second, "2001:db8:17::2", Cost{Requests: 1})
	var denied *Denied
	if !errors.As(err, &denied) || denied.Reason != "shared_network_budget" {
		t.Fatal("multiple accounts or rotating IPv6 bypassed shared network budget")
	}
	if _, err := db.Exec(`UPDATE auth.data_policies SET enabled=false WHERE user_id=(SELECT id FROM auth.users WHERE username=$1)`, second); err != nil {
		t.Fatal(err)
	}
	_, err = Reserve(context.Background(), db, second, "192.0.2.77", Cost{Requests: 1})
	if !errors.As(err, &denied) || denied.Reason != "disabled" {
		t.Fatal("disabled account still reads data")
	}
}

func TestJSONCostsAndReset(t *testing.T) {
	cost, err := JSONCost([]byte(`{"rows":[{"symbol":"A","values":[1,2]},{"company_name":"B"}],"nested":{"items":[3]}}`))
	if err != nil || cost.Records != 5 || len(cost.Targets) != 2 || cost.Bytes == 0 {
		t.Fatalf("incorrect nested accounting: %+v", cost)
	}
	now := time.Date(2026, 11, 7, 20, 45, 0, 0, time.UTC)
	reset := resetAt(now)
	if reset.Hour() != 0 || reset.Day() != 9 {
		t.Fatalf("incorrect Tehran reset %s", reset)
	}
	if ipIdentity("2001:db8::1") != ipIdentity("2001:db8::9") {
		t.Fatal("IPv6 /64 grouping failed")
	}
}
