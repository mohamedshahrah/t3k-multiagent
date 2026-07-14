<script>
  import { onMount } from "svelte";
  import Sidebar from "./lib/Sidebar.svelte";
  import DropZone from "./lib/DropZone.svelte";
  import DocumentList from "./lib/DocumentList.svelte";
  import DocumentDetail from "./lib/DocumentDetail.svelte";
  import TracePanel from "./lib/TracePanel.svelte";
  import { api, onSidecarEvent, inWails, startStack, SIDECAR_BASE } from "./api.js";

  let view = "gelen";
  let documents = [];
  let selectedId = null;
  let toast = null;
  let live = [];

  // Stack lifecycle: "ready" | "starting" | "error"
  let stackState = "starting";
  let stackError = "";
  let stackMsg = "Servis başlatılıyor…";

  onMount(() => {
    const cleanups = [];
    initStack();
    cleanups.push(onSidecarEvent(onEvent));
    if (inWails() && window.runtime) {
      window.runtime.EventsOn("stack:starting", (m) => { stackState = "starting"; stackMsg = m || stackMsg; });
      window.runtime.EventsOn("stack:ready", () => { stackState = "ready"; reload(); });
      window.runtime.EventsOn("stack:error", (e) => { stackState = "error"; stackError = e || "Bilinmeyen hata"; });
      cleanups.push(() => ["stack:starting", "stack:ready", "stack:error"].forEach((n) => window.runtime.EventsOff(n)));
    }
    return () => cleanups.forEach((f) => f && f());
  });

  async function initStack() {
    if (inWails()) {
      try {
        const st = await window.go.main.App.StackStatus();
        stackState = st === "ok" ? "ready" : "starting"; // Go is bringing it up if down
      } catch { stackState = "starting"; }
    } else {
      await probeHealth();
    }
    if (stackState === "ready") reload();
  }

  async function probeHealth() {
    try {
      const r = await fetch(`${SIDECAR_BASE}/health`);
      if (r.ok) { stackState = "ready"; }
      else { stackState = "error"; stackError = "Sidecar yanıt vermiyor."; }
    } catch {
      stackState = "error";
      stackError = "Arka uç (sidecar) çalışmıyor. Docker Desktop açık mı?";
    }
  }

  async function retry() {
    stackState = "starting";
    try {
      if (inWails()) { await startStack(); } else { await probeHealth(); }
      if (inWails()) stackState = "ready";
      if (stackState === "ready") reload();
    } catch (e) {
      stackState = "error";
      stackError = String(e);
    }
  }

  async function reload() {
    try { documents = await api("GET", "/documents"); } catch { documents = []; }
  }

  function onEvent(type, data) {
    if (type === "document_ingested" || type === "status") reload();
    if (type === "status" && data?.status) pushLive(`${short(data.doc_id)} → ${data.status}`);
    if (type === "tool_step" && data?.thought_tr) pushLive(`🔎 ${data.agent}: ${data.thought_tr}`);
    if (type === "agent_done") pushLive(`✓ ${data.agent} bitti (${data.tool_steps} adım${data.degraded ? ", degraded" : ""})`);
    if (type === "error") showToast(data?.message || "Hata", true);
  }

  const short = (id) => (id ? String(id).slice(0, 8) : "");
  function pushLive(msg) { live = [{ msg, t: Date.now() }, ...live].slice(0, 8); }
  function showToast(message, error = false) { toast = { message, error }; setTimeout(() => (toast = null), 4000); }
  function openDoc(id) { selectedId = id; view = "detay"; }
</script>

{#if stackState === "starting"}
  <div class="splash">⏳ {stackMsg}</div>
{:else if stackState === "error"}
  <div class="error-screen">
    <div class="icon">🔌</div>
    <h1 class="h1">Arka uç başlatılamadı</h1>
    <p class="muted">{stackError}</p>
    <p class="muted">Docker Desktop'ın çalıştığından emin olun.</p>
    <button class="btn" on:click={retry}>Yeniden dene</button>
  </div>
{:else}
  <div class="layout">
    <Sidebar {view} onNavigate={(v) => (view = v)} />

    <main class="main">
      {#if view === "gelen"}
        <h1 class="h1">Gelen Evrak</h1>
        <p class="sub">Belge yükleyin; sistem otomatik olarak okur (OCR) ve durumunu günceller.</p>
        <DropZone on:toast={(e) => showToast(e.detail.message, e.detail.error)} on:uploaded={reload} />
        {#if live.length}
          <div class="status-banner">
            <strong>Canlı akış</strong>
            {#each live as l}<div class="muted">{l.msg}</div>{/each}
          </div>
        {/if}
        <div style="height:16px"></div>
        <DocumentList {documents} onOpen={openDoc} />

      {:else if view === "detay"}
        <h1 class="h1">Evrak Detayı</h1>
        <p class="sub">Belgenin aslı, çıkarılan metin, imza/mühür bilgisi ve okuma izi.</p>
        <DocumentDetail docId={selectedId} />

      {:else if view === "denetim"}
        <h1 class="h1">Denetim Kaydı</h1>
        <p class="sub">Ajanların adım adım akıl yürütme izi (agent_log + tool_log).</p>
        <DocumentList {documents} onOpen={(id) => (selectedId = id)} />
        <div style="height:16px"></div>
        <TracePanel docId={selectedId} />

      {:else if view === "kutu"}
        <h1 class="h1">Gelen Kutusu</h1>
        <p class="sub">Yönlendirme ve yanıt akışı (Faz 4).</p>
        <p class="muted">Bu ekran, evraklar yönlendirilip taslak üretilmeye başlandığında dolacak.</p>

      {:else if view === "yonetim"}
        <h1 class="h1">Yönetim</h1>
        <p class="sub">Kullanıcı, birim ve kural yönetimi (Faz 5).</p>
        <p class="muted">Tohum verileri: 6 birim, 12 kullanıcı yüklendi.</p>
      {/if}
    </main>
  </div>
{/if}

{#if toast}
  <div class="toast {toast.error ? 'error' : ''}">{toast.message}</div>
{/if}
