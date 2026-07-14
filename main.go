package main

import (
	"embed"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
)

//go:embed all:frontend/dist
var assets embed.FS

// Thin desktop shell: a native WebView window that talks to the containerized sidecar
// on http://127.0.0.1:8756. All real work happens in the sidecar; this process only
// manages the Docker stack, proxies HTTP, opens file dialogs, and relays SSE events.
func main() {
	app := NewApp()

	err := wails.Run(&options.App{
		Title:  "Evrak Asistanı",
		Width:  1280,
		Height: 860,
		AssetServer: &assetserver.Options{
			Assets: assets,
		},
		// Native OS file drop is handled in Go (app.startup registers OnFileDrop);
		// disable the webview's own HTML5 drop so a dropped file isn't uploaded twice.
		DragAndDrop: &options.DragAndDrop{
			EnableFileDrop:     true,
			DisableWebViewDrop: true,
		},
		OnStartup: app.startup,
		Bind: []interface{}{
			app,
		},
	})
	if err != nil {
		println("Error:", err.Error())
	}
}
