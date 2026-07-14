# Evrak Asistanı

Yerel, uçtan uca, çok-ajanlı resmî belge işleme sistemi (Türkçe). Bir PDF/görsel bırakırsınız;
ajanlar belgeyi **okur (OCR)**, sınıflandırır, alanları çıkarır, özetler, kurallara göre denetler,
doğru birime yönlendirir ve resmî yazıyı taslaklar. Her şey **yerelde**, Docker içinde çalışır —
hiçbir veri dışarı çıkmaz.

> Bu depo şu an **Faz 0–2** çalışır durumdadır: kimlik/ortam (Docker), alım (intake) + yinelenen
> reddi, `call_agent` araç döngüsü ve **Okuyucu** (agentic OCR + yakınlaştırma). Faz 3+ (sınıflandırma,
> denetim, yönlendirme, taslak) planı `01-PROJECT-PLAN-PHASES.md` içindedir.

## Mimari (kısaca)

- **Docker Compose** tüm arka ucu çalıştırır: `ollama` (GPU, model sunucusu) + `sidecar`
  (FastAPI + LangGraph + DuckDB). Yalnızca **Wails** masaüstü penceresi ana makinede çalışır ve
  `http://127.0.0.1:8756` ile konuşur.
- Omurga **deterministik** bir LangGraph akışıdır; üstünde beş düğüm **araç kullanan ajandır**.
  Ajanlar `call_agent` sarmalayıcısından geçer: şema-kısıtlı çıktı + sınırlı araç döngüsü
  (`max_steps`, araç bütçesi, zaman aşımı, sert **tek-atış geri düşüşü**).
- **Model tag'i asla sabit kodlanmaz** — `MODEL_TAG` ortam değişkeniyle gelir.
  > Not: Plandaki `gemma4:12b` Ollama'da **yoktur**; gerçek aile `gemma3`'tür. Bu depo `gemma3:12b`
  > (ana) ve `gemma3:4b` (yedek) kullanır. 8 GB GPU'da 12B, sayfa görüntüsüyle OCR sırasında belleğe
  > sığmayabilir; sığmazsa `.env` içinde `MODEL_TAG=gemma3:4b` yapın (tek satır).

## Kurulum (depoyu klonlayıp çalıştırma)

### Önkoşullar (makine başına bir kez)
- **Docker Desktop** (WSL2 arka ucu + NVIDIA sürücüsü) — **zorunlu** (arka uç burada çalışır).
- Yalnızca **masaüstü uygulaması** için: **Go ≥1.23**, **Node LTS**, **Wails v2**
  (`go install github.com/wailsapp/wails/v2/cmd/wails@latest`). WebView2 Windows 11'de yerleşiktir.

### Çalıştırma (5 adım)
```powershell
# 1. klonla + ön kontrol (araçları denetler, .env.example'dan .env oluşturur)
git clone https://github.com/<kullanici>/evrak-asistani.git
cd evrak-asistani
.\scripts\setup.ps1

# 2. GPU'su ≤8 GB olan makinelerde .env'i düzenle:  MODEL_TAG=gemma3:4b
#    (varsayılan gemma3:12b — 12 GB+ GPU'da iyi; 8 GB'de OCR sırasında belleğe sığmaz)

# 3. arka ucu derle + başlat (ollama + sidecar)
docker compose up -d --build

# 4. modelleri ollama hacmine indir  (tek seferlik, birkaç GB)
.\scripts\pull-models.ps1

# 5. örnek birim/kullanıcı tohumlarını yükle
docker compose exec sidecar python -m db.seed
```

### Uygulamayı aç
- **Masaüstü penceresi** (Go + Wails gerekir): `.\scripts\dev.ps1` — arka ucu başlatır ve pencereyi açar.
  > Not: `wails dev` gerçek bir terminalden çalıştırılmalı. Alternatif: `wails build` ile üretilen
  > `build\bin\Evrak Asistani.exe` dosyasını çift tıklayın.
- **Go/Wails yoksa** — arka uç tek başına kullanılabilir: `http://127.0.0.1:8756/health`, ya da arayüzü
  tarayıcıda çalıştırın: `npm --prefix frontend install; npm --prefix frontend run dev`
  → `http://localhost:5173` (bunun için CORS açıktır).

### Durdurma
```powershell
docker compose down     # modeller + DB kalıcıdır (hacim/bind-mount içinde)
```

### Ekip için notlar
- **Modeller depoda yoktur** — 4. adım her makinede indirir (ilk çalıştırma bu yüzden büyük).
- **`.env` makineye özeldir** (git dışı). `setup.ps1` onu `.env.example`'dan üretir; herkes kendi
  GPU'suna göre `MODEL_TAG` ayarlar.
- **DuckDB şeması ilk açılışta otomatik göç eder**; **tohumlar** için 5. adım tek seferliktir.
- Modeller indikten sonra her şey **yerelde/çevrimdışı** çalışır — veri makineden çıkmaz.
- Hızlı sağlık kontrolü: uygulamaya bir PDF bırak → UUID'li satır belirir → tekrar bırak → "yinelenen"
  bildirimi. Loglar: `.\scripts\logs.ps1`.

## Doğrulama (bu depoda test edildi)

- `sidecar` konteyneri sağlıklı: `GET /health` → `{"status":"ok", ...}`
- Alım: PDF yükle → `202` + UUIDv7; aynı dosyayı tekrar yükle → `409 {"error":"duplicate"}`
- Birim testleri (`docker compose exec sidecar python -m pytest` veya host'ta `uv run pytest`):
  araç döngüsü + tek-atış geri düşüşü + alım/yinelenen reddi.

## Faydalı komutlar

```powershell
.\scripts\logs.ps1                                    # sidecar loglarını izle
docker compose exec sidecar python -m db.seed         # birim/kullanıcı tohumları
docker compose exec sidecar python -m pytest -q       # testler (konteyner içinde)
```

## Depo düzeni

`sidecar/` FastAPI + LangGraph + DuckDB (tüm Python); `main.go`/`app.go` Wails kabuğu;
`frontend/` Svelte arayüz; `data/` bind-mount (DB + dosyalar + tohumlar); `scripts/` PowerShell
yardımcıları; `docs/` mimari & metrikler. Ayrıntı: `01-PROJECT-PLAN-PHASES.md`.

## Ekip kuralı

Python **asla** ana makinede çalıştırılmaz — her şey konteyner içinde: `docker compose exec sidecar …`.
`uv.lock` ve imaj tag'leri yalnızca PR ile değişir. Araçlar **v1'de salt-okunurdur**; hiçbir araç
durumu değiştirmez, tüm yazma işlemleri ajan tipli cevabını döndürdükten sonra kod içinde olur.
