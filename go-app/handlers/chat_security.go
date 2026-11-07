package handlers

import (
	"fmt"
	"net/http"
	"unicode/utf8"
)

func validChatHistory(messages []chatIncomingMessage) bool {
	if len(messages) == 0 || len(messages) > 40 {
		return false
	}
	total := 0
	for _, message := range messages {
		if message.Role != "user" && message.Role != "assistant" {
			return false
		}
		if !utf8.ValidString(message.Content) || len(message.Content) > 16000 {
			return false
		}
		total += len(message.Content)
	}
	return total <= 64000
}

func rejectAIRedirect(_ *http.Request, _ []*http.Request) error {
	return fmt.Errorf("AI redirects are disabled")
}
