package main

import "net/http"

const jsonContentType = "application/json; charset=utf-8"

type errorBody struct {
	Error errorDetail `json:"error"`
}

type errorDetail struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

const fallbackErrorBody = `{"error":{"code":"internal_error","message":"response encoding failed"}}`

// writeBody sends store bytes verbatim; a 204 carries no body.
func writeBody(w http.ResponseWriter, status int, body []byte) {
	w.Header().Set("Content-Type", jsonContentType)
	w.WriteHeader(status)
	if status != http.StatusNoContent {
		_, _ = w.Write(body)
	}
}

func writeErr(w http.ResponseWriter, e *AppError) {
	body, err := MarshalJSON(errorBody{Error: errorDetail{Code: e.Code, Message: e.Message}})
	if err != nil {
		writeBody(w, http.StatusInternalServerError, []byte(fallbackErrorBody))
		return
	}
	writeBody(w, e.Status, body)
}
