package main

import (
	"bufio"
	"bytes"
	"context"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/wailsapp/wails/v2/pkg/runtime"
)

const sidecarBase = "http://127.0.0.1:8756"

// App is bound to the frontend; its exported methods become JS-callable functions.
type App struct {
	ctx         context.Context
	manageStack bool
}

func NewApp() *App {
	return &App{manageStack: true}
}

func (a *App) startup(ctx context.Context) {
	a.ctx = ctx

	// Native drag & drop: the OS hands us real file paths; upload each and let the UI refresh.
	runtime.OnFileDrop(ctx, func(x, y int, paths []string) {
		for _, p := range paths {
			if res, err := a.UploadFile(p); err == nil {
				runtime.EventsEmit(a.ctx, "sidecar:document_ingested", res)
			}
		}
	})

	go func() {
		if a.manageStack && !a.sidecarHealthy() {
			runtime.EventsEmit(a.ctx, "stack:starting", "Servis başlatılıyor…")
			if err := a.composeUp(); err != nil {
				runtime.EventsEmit(a.ctx, "stack:error", err.Error())
				return
			}
		}
		a.waitHealthy(60 * time.Second)
		runtime.EventsEmit(a.ctx, "stack:ready", true)
		a.relaySSE() // blocks, auto-reconnects
	}()
}

// --- stack management ------------------------------------------------------

func (a *App) sidecarHealthy() bool {
	c := http.Client{Timeout: 2 * time.Second}
	resp, err := c.Get(sidecarBase + "/health")
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode == 200
}

func (a *App) waitHealthy(timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if a.sidecarHealthy() {
			return true
		}
		time.Sleep(2 * time.Second)
	}
	return false
}

func (a *App) composeUp() error {
	dir, _ := os.Getwd()
	cmd := exec.Command("docker", "compose", "up", "-d")
	cmd.Dir = dir
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("docker compose up failed: %v — %s", err, string(out))
	}
	return nil
}

// StackStatus is callable from the UI: "ok" | "down".
func (a *App) StackStatus() string {
	if a.sidecarHealthy() {
		return "ok"
	}
	return "down"
}

// StartStack lets the UI retry bringing the backend up.
func (a *App) StartStack() error {
	if err := a.composeUp(); err != nil {
		return err
	}
	if !a.waitHealthy(60 * time.Second) {
		return fmt.Errorf("sidecar sağlıklı hale gelmedi")
	}
	return nil
}

// --- HTTP proxy to the sidecar --------------------------------------------

// Api proxies a JSON request to the sidecar. method: GET/POST/... path: "/documents".
func (a *App) Api(method, path, body string) (string, error) {
	var reader io.Reader
	if body != "" {
		reader = strings.NewReader(body)
	}
	req, err := http.NewRequest(method, sidecarBase+path, reader)
	if err != nil {
		return "", err
	}
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 400 {
		return string(data), fmt.Errorf("HTTP %d", resp.StatusCode)
	}
	return string(data), nil
}

// OpenFileDialog opens a native picker and returns the selected path ("" if cancelled).
func (a *App) OpenFileDialog() (string, error) {
	return runtime.OpenFileDialog(a.ctx, runtime.OpenDialogOptions{
		Title: "Evrak seç",
		Filters: []runtime.FileFilter{
			{DisplayName: "Belgeler (*.pdf;*.png;*.jpg;*.jpeg)", Pattern: "*.pdf;*.png;*.jpg;*.jpeg"},
		},
	})
}

// UploadFile reads a local file and posts it as multipart to /documents.
// Returns the sidecar's JSON response (including a 409 duplicate body).
func (a *App) UploadFile(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()

	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	part, err := w.CreateFormFile("file", filepath.Base(path))
	if err != nil {
		return "", err
	}
	if _, err := io.Copy(part, f); err != nil {
		return "", err
	}
	w.Close()

	req, _ := http.NewRequest("POST", sidecarBase+"/documents", &buf)
	req.Header.Set("Content-Type", w.FormDataContentType())
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	return string(data), nil
}

// --- SSE relay: sidecar /events -> Wails runtime events --------------------

func (a *App) relaySSE() {
	for {
		func() {
			resp, err := http.Get(sidecarBase + "/events")
			if err != nil {
				return
			}
			defer resp.Body.Close()
			scanner := bufio.NewScanner(resp.Body)
			scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
			var eventName string
			for scanner.Scan() {
				line := scanner.Text()
				switch {
				case strings.HasPrefix(line, "event:"):
					eventName = strings.TrimSpace(line[len("event:"):])
				case strings.HasPrefix(line, "data:"):
					data := strings.TrimSpace(line[len("data:"):])
					if eventName == "" {
						eventName = "message"
					}
					runtime.EventsEmit(a.ctx, "sidecar:"+eventName, data)
					eventName = ""
				}
			}
		}()
		time.Sleep(2 * time.Second) // reconnect
	}
}
