package dataaccess

import (
	"encoding/json"
	"strings"
)

func JSONCost(body []byte) (Cost, error) {
	cost := Cost{Bytes: int64(len(body))}
	var value any
	if err := json.Unmarshal(body, &value); err != nil {
		return cost, err
	}
	targets := map[string]bool{}
	var walk func(any)
	walk = func(value any) {
		switch node := value.(type) {
		case []any:
			cost.Records += int64(len(node))
			for _, item := range node {
				walk(item)
			}
		case map[string]any:
			for _, key := range []string{"symbol", "company_name"} {
				if symbol, ok := node[key].(string); ok && strings.TrimSpace(symbol) != "" {
					targets[symbol] = true
					break
				}
			}
			for _, item := range node {
				walk(item)
			}
		}
	}
	walk(value)
	for target := range targets {
		cost.Targets = append(cost.Targets, target)
	}
	return cost, nil
}
