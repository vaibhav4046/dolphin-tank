package main

import (
	"io/fs"
	"net/http"
	"net/http/httptest"
	"path"
	"regexp"
	"strings"
	"testing"
)

func TestUIShellNegotiation(t *testing.T) {
	h, token := newTestServer(t)
	for _, p := range []string{"/", "/split", "/signup", "/login"} {
		for _, accept := range []string{"", "application/json", "text/html", "*/*"} {
			rec := do(h, "GET", p, "", map[string]string{"Accept": accept})
			if rec.Code != 200 || rec.Header().Get("Content-Type") != htmlContentType || rec.Header().Get("Cache-Control") != "no-store" {
				t.Errorf("GET %s accept=%q: %d %q %q", p, accept, rec.Code, rec.Header().Get("Content-Type"), rec.Header().Get("Cache-Control"))
			}
			if !strings.Contains(rec.Body.String(), `<link rel="icon" href="data:,">`) {
				t.Errorf("GET %s: shell lacks the data: icon", p)
			}
		}
	}
	for _, p := range []string{"/requests", "/authorizations"} {
		html := do(h, "GET", p, "", map[string]string{"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"})
		if html.Code != 200 || html.Header().Get("Content-Type") != htmlContentType {
			t.Errorf("GET %s text/html: %d %q", p, html.Code, html.Header().Get("Content-Type"))
		}
		wantErr(t, "GET "+p+" without token", do(h, "GET", p, "", nil), 401, "unauthenticated")
		wantErr(t, "GET "+p+" json without token", do(h, "GET", p, "", map[string]string{"Accept": "application/json"}), 401, "unauthenticated")
		api := do(h, "GET", p, "", map[string]string{"Authorization": "Bearer " + token, "Accept": "application/json"})
		if api.Code != 200 || api.Header().Get("Content-Type") != jsonContentType {
			t.Errorf("GET %s json: %d %q", p, api.Code, api.Header().Get("Content-Type"))
		}
	}
	for _, c := range []struct{ method, path string }{
		{"POST", "/"}, {"POST", "/login"}, {"HEAD", "/"}, {"DELETE", "/requests"}, {"GET", "/nope"}, {"GET", "/requests/"}, {"GET", "/authorizations/x/capture"},
	} {
		wantErr(t, c.method+" "+c.path, do(h, c.method, c.path, "", map[string]string{"Accept": "text/html"}), 404, "not_found")
	}
}

func TestStaticAssets(t *testing.T) {
	h, _ := newTestServer(t)
	wantType := map[string]string{".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8"}
	count := 0
	err := fs.WalkDir(webFS, "web", func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() || p == "web/index.html" {
			return err
		}
		count++
		url := assetPrefix + strings.TrimPrefix(p, "web/")
		rec := do(h, "GET", url, "", nil)
		if ct, ok := wantType[path.Ext(p)]; ok && (rec.Code != 200 || rec.Header().Get("Content-Type") != ct) {
			t.Errorf("GET %s: %d %q, want %q", url, rec.Code, rec.Header().Get("Content-Type"), ct)
		}
		if rec.Header().Get("Cache-Control") != "no-cache" && rec.Code == 200 {
			t.Errorf("GET %s: Cache-Control %q", url, rec.Header().Get("Cache-Control"))
		}
		if rec.Code == 200 && rec.Body.Len() == 0 {
			t.Errorf("GET %s: empty body", url)
		}
		return nil
	})
	if err != nil || count < 20 {
		t.Fatalf("walked %d asset files: %v", count, err)
	}
	for _, p := range []string{"/assets/index.html", "/assets/nope.js", "/assets/js", "/assets/", "/assets/../go.mod", "/assets/js/../../go.mod", "/assets/%2e%2e/go.mod"} {
		wantErr(t, "GET "+p, do(h, "GET", p, "", nil), 404, "not_found")
	}
	wantErr(t, "POST asset", do(h, "POST", "/assets/js/main.js", "", nil), 404, "not_found")
}

var externalURL = regexp.MustCompile(`(?i)(https?:)?//[a-z0-9.-]+\.[a-z]{2,}|@import|url\(\s*["']?(https?:|//)`)

// The only URL-shaped string allowed is the SVG XML namespace, which is never fetched.
const svgNamespace = "http://www.w3.org/2000/svg"

func TestNoExternalURLsInServedFiles(t *testing.T) {
	h, _ := newTestServer(t)
	check := func(name, body string) {
		body = strings.ReplaceAll(body, svgNamespace, "")
		if m := externalURL.FindString(body); m != "" {
			t.Errorf("%s references an external resource: %q", name, m)
		}
	}
	check("/", do(h, "GET", "/", "", nil).Body.String())
	_ = fs.WalkDir(webFS, "web", func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() || !(strings.HasSuffix(p, ".js") || strings.HasSuffix(p, ".css")) {
			return err
		}
		b, _ := fs.ReadFile(webFS, p)
		check(p, string(b))
		return nil
	})
	fontFace := regexp.MustCompile(`url\("([^"]+)"\)`)
	css, _ := fs.ReadFile(webFS, "web/css/tokens.css")
	for _, m := range fontFace.FindAllStringSubmatch(string(css), -1) {
		if !strings.HasPrefix(m[1], assetPrefix) {
			t.Errorf("font url %q is not served from %s", m[1], assetPrefix)
		}
		if rec := do(h, "GET", m[1], "", nil); rec.Code != 200 || rec.Header().Get("Content-Type") != "font/woff2" {
			t.Errorf("font %s: %d", m[1], rec.Code)
		}
	}
}

// Every API route, hit with hostile bodies and headers, must answer below 500, and every API
// 4xx must carry the error envelope.
func TestGarbageSweepNo5xx(t *testing.T) {
	h, token := newTestServer(t)
	routes := []struct{ method, path string }{
		{"GET", "/me"}, {"POST", "/payments"}, {"POST", "/requests"}, {"GET", "/requests"}, {"POST", "/requests/rq_1/pay"},
		{"POST", "/requests/rq_1/decline"}, {"POST", "/requests/rq_1/cancel"}, {"POST", "/splits"}, {"GET", "/activity"},
		{"POST", "/settlements"}, {"POST", "/authorizations"}, {"GET", "/authorizations"},
		{"POST", "/authorizations/a_1/capture"}, {"POST", "/authorizations/a_1/void"}, {"POST", "/auth/login"}, {"POST", "/auth/signup"},
	}
	bodies := []string{"", "{", "[]", "null", "42", `"x"`, `{"amount":"1"}`, `{"amount":1e400}`, `{"to_handle":null}`, "\xff\xfe", `{"amount":1,"final":"yes"}`,
		`{"amount":null,"to_handle":"bob"}`, strings.Repeat("a", 5000), `{"note":"` + strings.Repeat("é", 300) + `","to_handle":"bob","amount":1}`}
	headers := []map[string]string{
		{"Authorization": "Bearer " + token, "Idempotency-Key": "k1"},
		{"Authorization": "Bearer " + token},
		{"Authorization": "Bearer " + token, "Idempotency-Key": strings.Repeat("k", 300)},
		{"Idempotency-Key": "k1"},
		{"Authorization": "Bearer " + token, "Idempotency-Key": "k2", "Accept": "text/html"},
	}
	for _, rt := range routes {
		for _, b := range bodies {
			for _, hd := range headers {
				req := httptest.NewRequest(rt.method, rt.path+"?limit=abc&offset=-1&direction=x&status=y", strings.NewReader(b))
				for k, v := range hd {
					req.Header.Set(k, v)
				}
				rec := httptest.NewRecorder()
				h.ServeHTTP(rec, req)
				if rec.Code >= 500 {
					t.Fatalf("%s %s body %.30q hdr %v: %d %s", rt.method, rt.path, b, hd, rec.Code, rec.Body)
				}
				if rec.Code >= 400 && rec.Header().Get("Content-Type") == jsonContentType && !strings.Contains(rec.Body.String(), `"error"`) {
					t.Errorf("%s %s: 4xx without envelope: %s", rt.method, rt.path, rec.Body)
				}
			}
		}
	}
	_ = http.StatusOK
}
