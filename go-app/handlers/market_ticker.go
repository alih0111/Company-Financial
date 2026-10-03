package handlers

// نوار قیمت لحظه‌ای صفحه‌ی اصلی (عمومی — بدون احراز هویت).
// منابع:
//   - TSETMC (old.tsetmc.com/tsev2/data/MarketWatchInit.aspx): شاخص کل، سهام شاخص‌ساز و صندوق‌های طلا
//   - TGJU   (call1.tgju.org/ajax.json): ارز، طلا و سکه
// نتیجه ۶۰ ثانیه در حافظه کش می‌شود و اگر منبع در دسترس نباشد، نسخه‌ی کهنه برگردانده می‌شود.

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

type TickerItem struct {
	Key       string  `json:"key"`
	Title     string  `json:"title"`
	Price     float64 `json:"price"`
	Unit      string  `json:"unit"`
	ChangePct float64 `json:"change_pct"`
	Source    string  `json:"source"`
	Group     string  `json:"group"` // کد گروه صنعت TSETMC (برای نمادهای بورسی)
}

type tickerCache struct {
	mu        sync.Mutex
	items     []TickerItem
	fetchedAt time.Time
	have      bool
}

var marketTickerCache tickerCache

var marketHTTPClient = &http.Client{Timeout: 12 * time.Second}

// tgju قیمت‌ها را ریال می‌دهد؛ تقسیم بر ۱۰ آن را به تومان تبدیل می‌کند.
type tgjuQuote struct {
	P  string  `json:"p"`
	DP float64 `json:"dp"`
}

type tgjuFeed struct {
	Current map[string]tgjuQuote `json:"current"`
}

var tgjuItems = []struct {
	Key     string
	Title   string
	ToToman bool // false → عدد به همان واحد (اونس جهانی دلاری است)
}{
	{"price_dollar_rl", "دلار", true},
	{"price_eur", "یورو", true},
	{"geram18", "طلای ۱۸ عیار", true},
	{"mesghal", "مسکوک", true},
	{"sekee", "سکه امامی", true},
	{"sekeb", "سکه بهار", true},
	{"nim", "نیم‌سکه", true},
	{"rob", "ربع‌سکه", true},
	{"ons", "اونس جهانی", false},
}

// نمادهای منتخب بورس/فرابورس و صندوق‌های طلا. تطبیق با نرمال‌سازی حروف عربی/فارسی انجام می‌شود.
var tsetmcSymbols = []struct {
	Match   string // نماد با املای فارسی استاندارد
	Display string
}{
	{"فولاد", "فولاد"},
	{"فملی", "فملی"},
	{"شپنا", "شپنا"},
	{"خودرو", "خودرو"},
	{"وبملت", "وبملت"},
	{"شستا", "شستا"},
	{"پارسان", "پارسان"},
	{"کگل", "کگل"},
	{"شپدیس", "شپدیس"},
	{"برکت", "برکت"},
	{"کچاد", "کچاد"},
	{"وبصادر", "وبصادر"},
	{"شبندر", "شبندر"},
	{"طلا", "صندوق طلا"},
	{"عیار", "صندوق عیار"},
	{"مثقال", "صندوق مثقال"},
	{"کهربا", "صندوق کهربا"},
}

// TSETMC نمادها را با حروف عربی (ي/ك) و فاصله‌های اضافی می‌نویسد.
var tsetmcNormalizer = strings.NewReplacer(
	"ي", "ی", "ك", "ک", "أ", "ا", "إ", "ا",
	"\u200c", "", "\u200f", "", "\u200e", "", "\u00a0", "", " ", "",
)

var firstFloatRe = regexp.MustCompile(`-?\d+(?:\.\d+)?`)

func fetchTGJU(ctx context.Context) ([]TickerItem, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, "https://call1.tgju.org/ajax.json", nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (compatible; RFA-Ticker/1.0)")
	resp, err := marketHTTPClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if err != nil {
		return nil, err
	}
	var feed tgjuFeed
	if err := json.Unmarshal(body, &feed); err != nil {
		return nil, err
	}

	items := make([]TickerItem, 0, len(tgjuItems))
	for _, cfg := range tgjuItems {
		q, ok := feed.Current[cfg.Key]
		if !ok {
			continue
		}
		price, err := strconv.ParseFloat(strings.ReplaceAll(q.P, ",", ""), 64)
		if err != nil || price == 0 {
			continue
		}
		if cfg.ToToman {
			price /= 10
		}
		unit := "تومان"
		if !cfg.ToToman {
			unit = "دلار"
		}
		items = append(items, TickerItem{
			Key:       cfg.Key,
			Title:     cfg.Title,
			Price:     price,
			Unit:      unit,
			ChangePct: q.DP,
			Source:    "tgju",
			Group:     "",
		})
	}
	if len(items) == 0 {
		return nil, fmt.Errorf("tgju: no usable quotes")
	}
	return items, nil
}

func fetchTSETMC(ctx context.Context) ([]TickerItem, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet,
		"https://old.tsetmc.com/tsev2/data/MarketWatchInit.aspx?h=0&r=0", nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (compatible; RFA-Ticker/1.0)")
	resp, err := marketHTTPClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if err != nil {
		return nil, err
	}
	text := string(body)

	items := make([]TickerItem, 0, len(tsetmcSymbols)+1)
	sections := strings.SplitN(text, "@", 3)
	if len(sections) != 3 {
		return nil, fmt.Errorf("tsetmc: unexpected payload shape")
	}

	// بخش هدر: <زمان>,F,<شاخص کل>,<div>تغییر واحد</div>[ <درصد>%],...
	// فرمت درصد در خروجی TSETMC ثابت نیست؛ درصد را از خودِ مقدار تغییر محاسبه می‌کنیم.
	header := strings.Split(sections[1], ",")
	if len(header) >= 4 {
		if idxVal, err := strconv.ParseFloat(strings.TrimSpace(header[2]), 64); err == nil && idxVal > 0 {
			pct := 0.0
			if m := firstFloatRe.FindString(header[3]); m != "" {
				if chg, err := strconv.ParseFloat(m, 64); err == nil && chg != 0 && idxVal != chg {
					pct = chg / (idxVal - chg) * 100
				}
			}
			items = append(items, TickerItem{
				Key: "tedex", Title: "شاخص کل", Price: idxVal,
				Unit: "واحد", ChangePct: pct, Source: "tsetmc",
			})
		}
	}

	// سطرها: InsID,ISIN,نماد,نام,زمان,اولین,آخرین,پایانی,تعداد,حجم,ارزش,...,بیشترین,پایانیِ دیروز(مبنا),...
	// توجه: درصد تغییر باید نسبت به ستون ۱۳ (پایانی دیروز = مبنای دامنه نوسان) حساب شود؛
	// ستون ۱۱ «دیروز» نیست و درصدهای متفاوت (اشتباه) می‌دهد.
	bySymbol := make(map[string][]string, 4096)
	for _, row := range strings.Split(sections[2], ";") {
		f := strings.Split(row, ",")
		if len(f) <= 14 {
			continue
		}
		sym := tsetmcNormalizer.Replace(f[2])
		if sym != "" {
			if _, seen := bySymbol[sym]; !seen {
				bySymbol[sym] = f
			}
		}
	}

	for _, cfg := range tsetmcSymbols {
		f, ok := bySymbol[tsetmcNormalizer.Replace(cfg.Match)]
		if !ok {
			continue
		}
		close_, err := strconv.ParseFloat(strings.TrimSpace(f[7]), 64)
		if err != nil || close_ <= 0 {
			continue
		}
		yest, err := strconv.ParseFloat(strings.TrimSpace(f[13]), 64)
		pct := 0.0
		if err == nil && yest > 0 {
			pct = (close_ - yest) / yest * 100
		}
		items = append(items, TickerItem{
			Key:       cfg.Match,
			Title:     cfg.Display,
			Price:     close_,
			Unit:      "ریال",
			ChangePct: pct,
			Source:    "tsetmc",
			Group:     strings.TrimSpace(f[18]),
		})
	}
	if len(items) <= 1 { // شاخص کل بدون سهم‌ها بی‌ارزش است
		return nil, fmt.Errorf("tsetmc: no matched symbols")
	}
	return items, nil
}

// GetMarketTicker قیمت‌های لحظه‌ای نوار متحرک را برمی‌گرداند.
// خروجی حتی هنگام قطعی منابع با آخرین نسخه‌ی کش‌شده ادامه می‌یابد (stale=true).
func GetMarketTicker(c *gin.Context) {
	const ttl = 60 * time.Second

	marketTickerCache.mu.Lock()
	cache := tickerCache{
		items:     marketTickerCache.items,
		fetchedAt: marketTickerCache.fetchedAt,
		have:      marketTickerCache.have,
	}
	marketTickerCache.mu.Unlock()

	fresh := cache.have && time.Since(cache.fetchedAt) < ttl
	if !fresh {
		ctx, cancel := context.WithTimeout(c.Request.Context(), 12*time.Second)
		defer cancel()

		var (
			tg   []TickerItem
			tse  []TickerItem
			tgErr, tseErr error
		)
		var wg sync.WaitGroup
		wg.Add(2)
		go func() { defer wg.Done(); tg, tgErr = fetchTGJU(ctx) }()
		go func() { defer wg.Done(); tse, tseErr = fetchTSETMC(ctx) }()
		wg.Wait()

		var merged []TickerItem
		merged = append(merged, tse...)
		merged = append(merged, tg...)
		if len(merged) > 0 {
			marketTickerCache.mu.Lock()
			marketTickerCache.items = merged
			marketTickerCache.fetchedAt = time.Now()
			marketTickerCache.have = true
			marketTickerCache.mu.Unlock()
			cache.items = merged
			cache.fetchedAt = time.Now()
			cache.have = true
		} else if !cache.have {
			// هیچ منبعی در دسترس نیست و کش هم خالی است.
			c.JSON(http.StatusServiceUnavailable, gin.H{
				"items": []TickerItem{},
				"stale": true,
				"error": fmt.Sprintf("tgju=%v tsetmc=%v", tgErr, tseErr),
			})
			return
		}
	}

	stale := time.Since(cache.fetchedAt) > ttl
	c.JSON(http.StatusOK, gin.H{
		"items":     cache.items,
		"as_of":     cache.fetchedAt.UTC().Format(time.RFC3339),
		"stale":     stale,
	})
}
