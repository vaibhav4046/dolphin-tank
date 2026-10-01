package main

import "strings"

type handlerFunc func(s *Server, c *call) (int, []byte, *AppError)

type route struct {
	public bool // no bearer token needed
	handle handlerFunc
}

var fixedRoutes = map[string]route{
	"GET /health":          {true, handleHealth},
	"POST /_test/reset":    {true, handleReset},
	"GET /_test/export":    {true, handleExport},
	"POST /_test/import":   {true, handleImport},
	"POST /auth/signup":    {true, handleSignup},
	"POST /auth/login":     {true, handleLogin},
	"GET /me":              {false, handleMe},
	"POST /payments":       {false, handlePayment},
	"POST /requests":       {false, handleCreateRequest},
	"GET /requests":        {false, handleListRequests},
	"POST /splits":         {false, handleSplit},
	"GET /activity":        {false, handleActivity},
	"POST /settlements":    {false, handleSettlement},
	"POST /authorizations": {false, handleAuthorize},
	"GET /authorizations":  {false, handleListAuthorizations},
}

// subActions are the POST /<collection>/{id}/<action> routes.
var subActions = map[string]map[string]route{
	"/requests/": {
		"pay":     {false, handlePayRequest},
		"decline": {false, handleDecline},
		"cancel":  {false, handleCancel},
	},
	"/authorizations/": {
		"capture": {false, handleCapture},
		"void":    {false, handleVoid},
	},
}

// resolve maps method+path to a route; a wrong method on a known path is simply unknown.
func resolve(method, path string) (route, string, bool) {
	if rt, ok := fixedRoutes[method+" "+path]; ok {
		return rt, "", true
	}
	if method != "POST" {
		return route{}, "", false
	}
	for prefix, actions := range subActions {
		rest, ok := strings.CutPrefix(path, prefix)
		if !ok {
			continue
		}
		id, action, ok := strings.Cut(rest, "/")
		if !ok || id == "" {
			return route{}, "", false
		}
		rt, ok := actions[action]
		return rt, id, ok
	}
	return route{}, "", false
}
