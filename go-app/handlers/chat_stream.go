package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"go-app/dataaccess"
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
	if err := c.ShouldBindJSON(&body); err != nil || !validChatHistory(body.Messages) {
		c.JSON(http.StatusBadRequest, gin.H{"error": "messages is required"})
		return
	}

	streamContext, cancelStream := context.WithCancel(c.Request.Context())
	defer cancelStream()
	c.Request = c.Request.WithContext(streamContext)
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
	streamBytes, streamStopped := 0, false
	send := func(event string, data any) {
		if streamStopped {
			return
		}
		b, err := json.Marshal(data)
		if err != nil {
			return
		}
		size := len(event) + len(b) + 20
		if !c.GetBool("isAdmin") && streamBytes+size > 63<<10 {
			streamStopped = true
			cancelStream()
			fmt.Fprint(w, "event: error\ndata: {\"error\":\"پاسخ بیش از حد بزرگ است؛ پرسش محدودتری انتخاب کنید.\"}\n\n")
			flusher.Flush()
			return
		}
		streamBytes += size
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
		var denied *dataaccess.Denied
		if errors.As(err, &denied) {
			send("error", gin.H{"error": "سهمیهٔ دریافت داده کافی نیست؛ پرسش محدودتری انتخاب کنید یا پس از بازنشانی سهمیه تلاش کنید.", "code": "data_quota_exceeded", "resets_at": denied.Reset})
			return
		}
		log.Printf("chat-stream: agent failed, falling back to rules: %v", err)
		send("notice", gin.H{"message": "پاسخ مدل در دسترس نبود؛ پاسخ قاعده‌ای ارسال می‌شود."})
	}

	send("final", ruleFallbackReply(c, userMsg, body))
}
