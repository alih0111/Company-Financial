package handlers

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"go-app/integration"

	"github.com/gin-gonic/gin"
)

// chat_agent.go — حلقه‌ی tool-calling دستیار.
//
// مدل زبانی اینجا فقط «مسیریاب و نویسنده» است: ابزار انتخاب می‌کند و متن
// می‌نویسد. هر عددی که به کاربر می‌رسد از خروجی ابزارها (chat_tools.go) می‌آید.
//
// مسیریابی مدل (قابل تنظیم با AI_MODEL / AI_MODEL_HARD / AI_MODEL_CHEAP):
//   - اصلی  : پیش‌فرض گفت‌وگو و ابزارها
//   - سخت   : پرسش‌های سنگین‌تر (چند شرکت، سبد، مقایسه‌ی عمیق)
//   - ارزان : کارهای ساده

const (
	agentSystemPromptFa = `تو دستیار تحلیل مالی فارسیزبان سامانهی غربالگری بورس تهران هستی.
قواعد قطعی:
۱) هیچ عددی از خودت نساز. هر عدد (امتیاز، قیمت، رشد، حاشیه، ریسک، وزن) باید از خروجی ابزارها بیاید. اگر ابزاری داده نداد، بگو «دادهاش موجود نیست».
۲) برای هر پرسش دربارهی شرکت/بازار، اول ابزار مناسب را صدا بزن؛ برای چند شرکت، ابزار را چند بار یا compare_companies را صدا بزن.
	۳) اگر کاربر سبد می‌خواهد، ابزار build_portfolio را صدا بزن و خروجی‌اش (وزن‌ها، متریک‌های ریسک و محدودیت‌ها) را خلاصه کن. پیش‌فرض همین ابزار (هموزن سقف‌دار) در بک‌تست PIT بهترین شارپ را داشته و min_variance افت کمتر ولی بازده کمتر؛ وزن را خودت نساز و یادآوری کن که عملکرد گذشته تضمین آینده نیست. جدول وزنها و «مبالغ تقریبی» خروجی این ابزار را کامل و بدون حذف در پاسخ بیاور.
۴) پاسخ کوتاه، با بولت، فارسی و خوانا. عددها را با واحدشان بنویس.
۵) در پایان هر تحلیل یک خط اضافه کن: «این تحلیل بر اساس دادههای کمی است و توصیهی خرید/فروش نیست.»
۶) اگر دادهی پرسش کهنه است یا پوششش ناقص است، صریح بگو.
۷) واحد پول همیشه ریال است. اگر کاربر با تومان گفت، ضریب ۱۰ اعمال کن و در پاسخ صریح بنویس «۵۰۰ میلیون تومان = ۵ میلیارد ریال». قبل از set_my_preferences عدد ریالی را با کاربر تأیید کن.`
	agentMaxRounds   = 4
	agentCallTimeout = 45 * time.Second
	agentBudget      = 90 * time.Second
	// agentHistoryMessages تعداد پیام‌های قبلی که همراه هر درخواست به مدل
	// می‌رود. هر پیام در هر دور ابزار دوباره ارسال و دوباره حساب می‌شود، پس
	// کوتاه نگه‌داشتنش مستقیم روی هزینه اثر دارد.
	agentHistoryMessages = 4
)

type agentMessage struct {
	Role       string          `json:"role"`
	Content    string          `json:"content,omitempty"`
	ToolCalls  []agentToolCall `json:"tool_calls,omitempty"`
	ToolCallID string          `json:"tool_call_id,omitempty"`
	Name       string          `json:"name,omitempty"`
	// ReasoningContent is returned by reasoning models (e.g. glm-5.3-flash)
	// before the visible answer; the visible content may still be empty when the
	// token budget is spent on reasoning.
	ReasoningContent string `json:"reasoning_content,omitempty"`
}

type agentToolCall struct {
	ID       string `json:"id"`
	Type     string `json:"type"`
	Function struct {
		Name      string `json:"name"`
		Arguments string `json:"arguments"`
	} `json:"function"`
}

type agentToolSpec struct {
	Type     string `json:"type"`
	Function struct {
		Name        string         `json:"name"`
		Description string         `json:"description"`
		Parameters  map[string]any `json:"parameters"`
	} `json:"function"`
}

type agentRequest struct {
	Model       string          `json:"model"`
	Messages    []agentMessage  `json:"messages"`
	Tools       []agentToolSpec `json:"tools,omitempty"`
	ToolChoice  string          `json:"tool_choice,omitempty"`
	Temperature float64         `json:"temperature"`
	MaxTokens   int             `json:"max_tokens,omitempty"`
}

type agentResponse struct {
	Choices []struct {
		FinishReason string       `json:"finish_reason"`
		Message      agentMessage `json:"message"`
	} `json:"choices"`
	Usage *struct {
		PromptTokens     int `json:"prompt_tokens"`
		CompletionTokens int `json:"completion_tokens"`
		TotalTokens      int `json:"total_tokens"`
		ReasoningTokens  int `json:"-"`
	} `json:"usage"`
	Error *struct {
		Message string `json:"message"`
		Type    string `json:"type"`
	} `json:"error"`
}

// aiConfigured reports whether the LLM path is usable (URL + key present).
func aiConfigured() bool {
	return strings.TrimSpace(os.Getenv("AI_CHAT_URL")) != "" && strings.TrimSpace(os.Getenv("AI_API_KEY")) != ""
}

// aiModel picks the model for a task class: "", "hard", "cheap".
func aiModel(class string) string {
	pick := func(keys ...string) string {
		for _, k := range keys {
			if v := strings.TrimSpace(os.Getenv(k)); v != "" {
				return v
			}
		}
		return ""
	}
	switch class {
	case "hard":
		return pick("AI_MODEL_HARD", "AI_MODEL")
	case "cheap":
		return pick("AI_MODEL_CHEAP", "AI_MODEL")
	default:
		return pick("AI_MODEL")
	}
}

// looksHard پرسش‌های سنگین‌تر را تشخیص می‌دهد تا به مدل قوی‌تر بسپاریم.
func looksHard(norm string) bool {
	hard := []string{"سبد", "پورتفوی", "پورتفولیو", "مقایسه", "بهینه", "ریسک", "تخصیص", "چند شرکت", "استراتژی", "بازار"}
	for _, w := range hard {
		if strings.Contains(norm, w) {
			return true
		}
	}
	return false
}

// callAgentModel یک درخواست chat/completions با پشتیبانی از tools می‌فرستد.
func callAgentModel(req agentRequest) (agentMessage, string, error) {
	chatURL := strings.TrimSpace(os.Getenv("AI_CHAT_URL"))
	apiKey := strings.TrimSpace(os.Getenv("AI_API_KEY"))
	if chatURL == "" || apiKey == "" {
		return agentMessage{}, "", fmt.Errorf("AI_CHAT_URL or AI_API_KEY is empty")
	}
	body, err := json.Marshal(req)
	if err != nil {
		return agentMessage{}, "", err
	}
	httpReq, err := http.NewRequest(http.MethodPost, chatURL, bytes.NewReader(body))
	if err != nil {
		return agentMessage{}, "", err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Authorization", "Bearer "+apiKey)

	client := &http.Client{Timeout: agentCallTimeout}
	resp, err := client.Do(httpReq)
	if err != nil {
		return agentMessage{}, "", err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return agentMessage{}, "", fmt.Errorf("ai status=%d body=%s", resp.StatusCode, truncateForLog(string(raw), 300))
	}
	var parsed agentResponse
	if err := json.Unmarshal(raw, &parsed); err != nil {
		return agentMessage{}, "", fmt.Errorf("invalid ai response: %w", err)
	}
	if parsed.Error != nil {
		return agentMessage{}, "", fmt.Errorf("ai error: %s", parsed.Error.Message)
	}
	if len(parsed.Choices) == 0 {
		return agentMessage{}, "", fmt.Errorf("ai response has no choices")
	}
	if u := parsed.Usage; u != nil {
		log.Printf("chat-agent: tokens prompt=%d completion=%d total=%d", u.PromptTokens, u.CompletionTokens, u.TotalTokens)
	}
	return parsed.Choices[0].Message, parsed.Choices[0].FinishReason, nil
}

func truncateForLog(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}

// agentEvent رویدادهای پیشرفت دستیار برای استریم SSE است.
type agentEvent struct {
	Type  string `json:"type"` // round | tool_start | tool_done | tool_error
	Round int    `json:"round,omitempty"`
	Tool  string `json:"tool,omitempty"`
	Chars int    `json:"chars,omitempty"`
	Error string `json:"error,omitempty"`
}

type agentEventSink func(agentEvent)

func noopSink(agentEvent) {}

var toolLabelsFa = map[string]string{
	"search_companies":       "جست‌وجوی شرکت",
	"screen_companies":       "غربال بازار",
	"get_company_profile":    "پروفایل بنیادی شرکت",
	"get_company_financials": "صورت‌های مالی",
	"get_monthly_sales":      "فروش ماهانه",
	"get_price_stats":        "آمار ریسک قیمت",
	"get_my_portfolio":       "سبد شما",
	"compare_companies":      "مقایسه شرکت‌ها",
	"build_portfolio":        "ساخت سبد",
}

// runChatAgent حلقه‌ی ابزار را اجرا می‌کند و متن نهایی و فهرست ابزارهای
// استفاده‌شده را برمی‌گرداند. sink می‌تواند nil باشد.
func runChatAgent(c *gin.Context, userMessage string, history []chatIncomingMessage, sink agentEventSink) (string, []string, error) {
	if sink == nil {
		sink = noopSink
	}
	rows, err := integration.Default().FetchSummaryCanonical(c.Request.Context())
	if err != nil {
		return "", nil, err
	}
	tools := newChatToolset(rows)
	toolsUsed := make([]string, 0, 4)

	// ابزارها را برای مدل توصیف می‌کنیم
	specs := make([]agentToolSpec, 0, len(tools))
	byName := make(map[string]chatTool, len(tools))
	for _, t := range tools {
		var s agentToolSpec
		s.Type = "function"
		s.Function.Name = t.name
		s.Function.Description = t.description
		s.Function.Parameters = t.parameters
		specs = append(specs, s)
		byName[t.name] = t
	}

	model := aiModel("")
	if looksHard(normalizeFaText(userMessage)) {
		model = aiModel("hard")
	}
	log.Printf("chat-agent: model=%s tools=%d question=%q", model, len(specs), truncateForLog(userMessage, 80))

	msgs := []agentMessage{{Role: "system", Content: agentSystemPromptFa}}
	start := 0
	if len(history) > agentHistoryMessages {
		start = len(history) - agentHistoryMessages
	}
	for _, m := range history[start:] {
		if m.Role == "user" || m.Role == "assistant" {
			msgs = append(msgs, agentMessage{Role: m.Role, Content: m.Content})
		}
	}
	if len(msgs) == 1 || msgs[len(msgs)-1].Content != userMessage {
		msgs = append(msgs, agentMessage{Role: "user", Content: userMessage})
	}

	deadline := time.Now().Add(agentBudget)
	username := c.GetString("username")

	for round := 0; round < agentMaxRounds; round++ {
		if time.Now().After(deadline) {
			return "", toolsUsed, fmt.Errorf("agent budget exceeded")
		}
		sink(agentEvent{Type: "round", Round: round + 1})
		msg, finish, err := callAgentModel(agentRequest{
			Model:       model,
			Messages:    msgs,
			Tools:       specs,
			ToolChoice:  "auto",
			Temperature: 0.3,
		})
		if err != nil {
			return "", toolsUsed, err
		}
		if len(msg.ToolCalls) == 0 {
			out := strings.TrimSpace(msg.Content)
			if out == "" {
				return "", toolsUsed, fmt.Errorf("ai returned empty answer (finish=%s)", finish)
			}
			return out, toolsUsed, nil
		}

		// پیام دستیار با درخواست‌های ابزار + نتایج هر ابزار
		msgs = append(msgs, agentMessage{Role: "assistant", Content: msg.Content, ToolCalls: msg.ToolCalls})
		for _, call := range msg.ToolCalls {
			tool, ok := byName[call.Function.Name]
			if !ok {
				msgs = append(msgs, agentMessage{Role: "tool", ToolCallID: call.ID,
					Content: fmt.Sprintf("ابزار ناشناخته: %s", call.Function.Name)})
				continue
			}
			var args map[string]any
			if raw := strings.TrimSpace(call.Function.Arguments); raw != "" {
				if err := json.Unmarshal([]byte(raw), &args); err != nil {
					msgs = append(msgs, agentMessage{Role: "tool", ToolCallID: call.ID,
						Content: "آرگومان‌های ابزار قابل خواندن نبود: " + err.Error()})
					continue
				}
			}
			sink(agentEvent{Type: "tool_start", Tool: call.Function.Name})
			out, err := tool.run(c.Request.Context(), username, args)
			if err != nil {
				log.Printf("chat-agent: tool %s failed: %v", call.Function.Name, err)
				out = "خطا در اجرای ابزار: " + err.Error()
				sink(agentEvent{Type: "tool_error", Tool: call.Function.Name, Error: truncateForLog(err.Error(), 120)})
			} else {
				log.Printf("chat-agent: tool %s ok (%d chars)", call.Function.Name, len(out))
				sink(agentEvent{Type: "tool_done", Tool: call.Function.Name, Chars: len(out)})
				toolsUsed = append(toolsUsed, call.Function.Name)
			}
			msgs = append(msgs, agentMessage{Role: "tool", ToolCallID: call.ID, Content: out})
		}
	}
	return "", toolsUsed, fmt.Errorf("agent reached max rounds without a final answer")
}

// GetAIHealth یک بررسی سریع اتصال مدل است (بدون افشای کلید).
func GetAIHealth(c *gin.Context) {
	if !aiConfigured() {
		c.JSON(http.StatusOK, gin.H{"configured": false, "hint": "AI_CHAT_URL/AI_API_KEY در go-app/.env تنظیم نشده است"})
		return
	}
	start := time.Now()
	msg, finish, err := callAgentModel(agentRequest{
		Model:       aiModel(""),
		Messages:    []agentMessage{{Role: "user", Content: "پاسخ کوتاه بده: وضعیت آماده‌به‌کار است."}},
		Temperature: 0,
		MaxTokens:   512,
	})
	latency := time.Since(start).Milliseconds()
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"configured": true, "reachable": false, "error": err.Error(),
			"model": aiModel(""), "latency_ms": latency})
		return
	}
	// مدل‌های استدلالی ممکن است ابتدا reasoning_content بدهند؛ برای اینکه این
	// بررسی معنادار بماند، اگر متن قابل‌نمایش خالی بود از خلاصه‌ی استدلال استفاده می‌کنیم.
	sample := msg.Content
	if strings.TrimSpace(sample) == "" {
		sample = msg.ReasoningContent
	}
	c.JSON(http.StatusOK, gin.H{
		"configured": true, "reachable": true, "model": aiModel(""),
		"hard_model": aiModel("hard"), "cheap_model": aiModel("cheap"),
		"finish_reason": finish, "reply": truncateForLog(sample, 80), "latency_ms": latency,
	})
}
