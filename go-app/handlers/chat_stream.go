package handlers

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

// chat_stream.go — POST /api/chat/stream: همان Chat با رویدادهای SSE.
//
// رویدادها (event: / data: JSON):
//
//	open     {"ok":true}
//	progress {"type":"round"|"tool_start"|"tool_done"|"tool_error", ...}
//	notice   {"message":"…"}          // مثلاً fallback به موتور قاعده‌ای
//	final    chatResponseBody         // پاسخ نهایی
//	error    {"error":"…"}
//
// استریم فقط «پیشرفت» است؛ متن پاسخ در رویداد final یک‌جا می‌آید. استریم
// توکن‌به‌توکن نیازمند stream:true سمت provider است و بعداً اضافه می‌شود.
func ChatStream(c *gin.Context) {
	var body chatRequestBody
	if err := c.ShouldBindJSON(&body); err != nil || len(body.Messages) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "messages is required"})
		return
	}

	w := c.Writer
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	// پراکسی‌ها (nginx و مانند آن) نباید استریم را بافر کنند.
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)
	flusher, ok := w.(http.Flusher)
	if !ok {
		return
	}
	send := func(event string, data any) {
		b, err := json.Marshal(data)
		if err != nil {
			return
		}
		fmt.Fprintf(w, "event: %s\ndata: %s\n\n", event, string(b))
		flusher.Flush()
	}
	// بخشی از کلاینت‌ها (پروکسی‌های قدیمی) قبل از اولین flush کوت می‌شوند؛
	// یک رویداد فوری اتصال را گرم نگه می‌دارد.
	send("open", gin.H{"ok": true})

	userMsg := ""
	for i := len(body.Messages) - 1; i >= 0; i-- {
		if body.Messages[i].Role == "user" {
			userMsg = strings.TrimSpace(body.Messages[i].Content)
			break
		}
	}
	if userMsg == "" {
		send("final", chatResponseBody{Reply: greetingReply(), Intent: "greeting"})
		return
	}

	if aiConfigured() {
		sink := func(e agentEvent) { send("progress", e) }
		reply, used, err := runChatAgent(c, userMsg, body.Messages, sink)
		if err == nil && strings.TrimSpace(reply) != "" {
			send("final", chatResponseBody{Reply: reply, Intent: "agent", ToolsUsed: used})
			return
		}
		log.Printf("chat-stream: agent failed, falling back to rules: %v", err)
		send("notice", gin.H{"message": "پاسخ مدل در دسترس نبود؛ پاسخ قاعده‌ای ارسال می‌شود."})
	}

	send("final", ruleFallbackReply(c, userMsg, body))
}
