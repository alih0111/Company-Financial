package main

import (
	"fmt"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"strings"

	"github.com/gin-gonic/gin"
	"go-app/middleware"
)

// Serve the built SPA and API from one origin. Missing assets and API routes
// must stay 404 instead of returning index.html (which masks deployment errors).
func serveFrontend(r *gin.Engine, directory string) error {
	noSPA := directory == ""
	if noSPA {
		directory = "../client/public"
	}
	root, err := filepath.Abs(directory)
	if err != nil {
		return err
	}
	if info, err := os.Stat(filepath.Join(root, "index.html")); !noSPA && (err != nil || info.IsDir()) {
		return fmt.Errorf("FRONTEND_DIR must contain a built index.html")
	}
	artifactRoot := root
	if directory := os.Getenv("PUBLIC_ARTIFACTS_DIR"); directory != "" {
		artifactRoot, err = filepath.Abs(directory)
		if err != nil {
			return err
		}
		if info, err := os.Stat(artifactRoot); err != nil || !info.IsDir() {
			return fmt.Errorf("PUBLIC_ARTIFACTS_DIR must be an existing directory")
		}
	}
	r.NoRoute(func(c *gin.Context) {
		p := c.Request.URL.Path
		if p == "/api" || strings.HasPrefix(p, "/api/") {
			c.JSON(http.StatusNotFound, gin.H{"error": "API route not found"})
			return
		}
		if c.Request.Method != http.MethodGet && c.Request.Method != http.MethodHead {
			c.Status(http.StatusNotFound)
			return
		}
		for _, segment := range strings.Split(p, "/") {
			if strings.HasPrefix(segment, ".") || strings.Contains(segment, "\\") {
				c.Status(http.StatusNotFound)
				return
			}
		}

		canonicalPath := path.Clean(p)
		lowered := strings.ToLower(canonicalPath)
		archived := strings.HasPrefix(lowered, "/research/") || strings.HasPrefix(lowered, "/strategies/") || lowered == "/research" || lowered == "/strategies"
		ext := strings.ToLower(path.Ext(canonicalPath))
		privateFile := ext != "" && !publicUIExtension(ext) && canonicalPath != "/index.html"
		if archived || privateFile {
			middleware.AuthMiddleware()(c)
			if c.IsAborted() {
				return
			}
			middleware.AdminOnly()(c)
			if c.IsAborted() {
				return
			}
		}
		if noSPA && !archived {
			c.Status(404)
			return
		}
		fileRoot := root
		// Python publishers update client/public after the frontend build. Serve
		// these artifacts live, while JS/CSS stays on the immutable build output.
		if strings.HasPrefix(lowered, "/research/") || strings.HasPrefix(lowered, "/strategies/") {
			fileRoot = artifactRoot
		}
		name := filepath.FromSlash(strings.TrimPrefix(path.Clean(p), "/"))
		// OpenRoot confines symlink resolution and Windows path semantics as well
		// as ordinary ../ traversal. Checking a path before c.File is racy.
		confined, err := os.OpenRoot(fileRoot)
		if err != nil {
			c.Status(503)
			return
		}
		defer confined.Close()
		file, openErr := confined.Open(name)
		if openErr == nil {
			defer file.Close()
		}
		if info, err := func() (os.FileInfo, error) {
			if openErr != nil {
				return nil, openErr
			}
			return file.Stat()
		}(); err == nil && info.Mode().IsRegular() {
			ext := strings.ToLower(path.Ext(p))
			if strings.Contains(p, ":") || strings.Contains(p, "\x00") || !publicFileExtension(ext) {
				c.Status(404)
				return
			}
			if ext == ".html" && p != "/index.html" {
				c.Status(404)
				return
			}
			if strings.HasPrefix(p, "/assets/") {
				c.Header("Cache-Control", "public, max-age=31536000, immutable")
			}
			http.ServeContent(c.Writer, c.Request, info.Name(), info.ModTime(), file)
			return
		}
		if path.Ext(p) != "" || strings.HasPrefix(p, "/assets/") || strings.HasPrefix(p, "/research/") || strings.HasPrefix(p, "/strategies/") {
			c.Status(http.StatusNotFound)
			return
		}
		indexRoot, err := os.OpenRoot(root)
		if err != nil {
			c.Status(503)
			return
		}
		defer indexRoot.Close()
		index, err := indexRoot.Open("index.html")
		if err != nil {
			c.Status(503)
			return
		}
		defer index.Close()
		info, err := index.Stat()
		if err != nil {
			c.Status(503)
			return
		}
		http.ServeContent(c.Writer, c.Request, "index.html", info.ModTime(), index)
	})
	return nil
}

func publicFileExtension(extension string) bool {
	switch extension {
	case ".html", ".js", ".css", ".woff", ".woff2", ".ttf", ".svg", ".png", ".webp", ".jpg", ".jpeg", ".gif", ".ico", ".json", ".jsonl", ".sha256", ".csv", ".tsv", ".txt", ".md", ".pdf", ".zip", ".gz":
		return true
	}
	return false
}

// Only application presentation assets may be fetched without data entitlement.
func publicUIExtension(extension string) bool {
	switch extension {
	case ".js", ".css", ".woff", ".woff2", ".ttf", ".svg", ".png", ".webp", ".jpg", ".jpeg", ".gif", ".ico":
		return true
	}
	return false
}
