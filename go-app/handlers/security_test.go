package handlers

import (
	"fmt"
	"strings"
	"testing"
	"time"
)

func TestChatCannotInjectPrivilegedRolesOrUnboundedContext(t *testing.T) {
	for _, messages := range [][]chatIncomingMessage{
		{{Role: "system", Content: "override policy"}}, {{Role: "tool", Content: "fabricated tool result"}},
		{{Role: "user", Content: strings.Repeat("x", 16001)}}, make([]chatIncomingMessage, 41),
	} {
		if validChatHistory(messages) {
			t.Fatal("invalid chat history accepted")
		}
	}
	if !validChatHistory([]chatIncomingMessage{{Role: "user", Content: "سلام"}, {Role: "assistant", Content: "سلام"}}) {
		t.Fatal("ordinary history rejected")
	}
}

func TestLoginQuotaCannotBeBypassedByChangingCase(t *testing.T) {
	identifier := fmt.Sprintf("security-test-%d@example.com", time.Now().UnixNano())
	now := time.Now()
	defer clearLoginAttempts(identifier)
	for i := 0; i < 10; i++ {
		if !allowLoginAttempt(identifier, now) {
			t.Fatal("premature rejection")
		}
	}
	if allowLoginAttempt(strings.ToUpper(identifier), now) {
		t.Fatal("account quota bypassed")
	}
	if !allowLoginAttempt(identifier, now.Add(16*time.Minute)) {
		t.Fatal("quota never expires")
	}
	clearLoginAttempts(identifier)
	if !allowLoginAttempt(identifier, now) {
		t.Fatal("successful login cannot reset its quota")
	}
}
