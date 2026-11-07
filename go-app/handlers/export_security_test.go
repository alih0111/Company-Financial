package handlers

import (
	"encoding/csv"
	"strings"
	"testing"
)

func TestExportTextCannotBecomeSpreadsheetFormula(t *testing.T) {
	for _, value := range []string{`=HYPERLINK("https://example.com")`, "+cmd", "-cmd", "@SUM(1,2)", "\t=1+1", "\ufeff=1+1"} {
		row, err := csv.NewReader(strings.NewReader(csvStr(value) + "\n")).Read()
		if err != nil || len(row) != 1 || !strings.HasPrefix(row[0], "'") {
			t.Fatal("untrusted text can execute as a spreadsheet formula")
		}
	}
	value := `شرکت "نمونه"`
	row, err := csv.NewReader(strings.NewReader(csvStr(value) + "\n")).Read()
	if err != nil || row[0] != value {
		t.Fatal("ordinary CSV text changed")
	}
	if csvNum(-12.5, 1) != "-12.5" {
		t.Fatal("numeric cells were escaped as text")
	}
}
