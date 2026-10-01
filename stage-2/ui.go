package main

import (
	"embed"
	"io/fs"
	"net/http"
	"path"
	"strings"
)

//go:embed web
var webFS embed.FS

const htmlContentType = "text/html; charset=utf-8"

const assetPrefix = "/assets/"

// uiPaths always get the UI shell on GET; sharedPaths share their URL with the JSON API
// and get the shell only when the client asks for text/html.
var (
	uiPaths     = map[string]bool{"/": true, "/split": true, "/signup": true, "/login": true}
	sharedPaths = map[string]bool{"/requests": true, "/authorizations": true}
)

var assetTypes = map[string]string{
	".js":    "text/javascript; charset=utf-8",
	".css":   "text/css; charset=utf-8",
	".woff2": "font/woff2",
	".txt":   "text/plain; charset=utf-8",
	".svg":   "image/svg+xml",
	".json":  "application/json; charset=utf-8",
}

func wantsHTML(r *http.Request) bool {
	return strings.Contains(strings.ToLower(r.Header.Get("Accept")), "text/html")
}

// serveUI answers GET requests for the browser shell and its static assets.
// It reports whether it handled the request; otherwise the JSON API routes it.
func serveUI(w http.ResponseWriter, r *http.Request) bool {
	if r.Method != http.MethodGet {
		return false
	}
	p := r.URL.Path
	switch {
	case uiPaths[p] || (sharedPaths[p] && wantsHTML(r)):
		return serveShell(w)
	case strings.HasPrefix(p, assetPrefix):
		return serveAsset(w, strings.TrimPrefix(p, assetPrefix))
	}
	return false
}

func serveShell(w http.ResponseWriter) bool {
	b, err := fs.ReadFile(webFS, "web/index.html")
	if err != nil {
		return false
	}
	h := w.Header()
	h.Set("Content-Type", htmlContentType)
	h.Set("Cache-Control", "no-store")
	h.Set("X-Content-Type-Options", "nosniff")
	_, _ = w.Write(b)
	return true
}

func serveAsset(w http.ResponseWriter, name string) bool {
	ct, known := assetTypes[path.Ext(name)]
	if !known || name == "index.html" || !fs.ValidPath(name) {
		return false
	}
	b, err := fs.ReadFile(webFS, "web/"+name)
	if err != nil {
		return false
	}
	h := w.Header()
	h.Set("Content-Type", ct)
	h.Set("Cache-Control", "no-cache")
	h.Set("X-Content-Type-Options", "nosniff")
	_, _ = w.Write(b)
	return true
}
