<script>
  import { api, fileUrl } from "../api.js";
  export let docId;

  let detail = null;
  let trace = null;
  let loading = true;

  $: if (docId) load(docId);

  async function load(id) {
    loading = true;
    detail = await api("GET", `/documents/${id}`);
    trace = await api("GET", `/documents/${id}/trace`);
    loading = false;
  }

  $: renderCount = (trace?.tool_log || []).filter((t) => t.tool === "render_page").length;
  $: anySignature = (detail?.pages || []).some((p) => p.has_signature);
  $: anyStamp = (detail?.pages || []).some((p) => p.has_stamp);
  $: mime = detail?.document?.mime || "";
  $: isPdf = mime === "application/pdf";
  $: isImage = mime.startsWith("image/");
</script>

{#if !docId}
  <p class="muted">Soldaki listeden bir evrak seçin.</p>
{:else if loading}
  <p class="muted">Yükleniyor…</p>
{:else if detail?.document}
  <div class="card">
    <div style="display:flex; justify-content:space-between; align-items:center; gap:12px;">
      <div>
        <div class="h1" style="margin:0">{detail.document.filename}</div>
        <div class="muted">{detail.document.mime} • {detail.document.page_count} sayfa</div>
      </div>
      <div style="display:flex; gap:8px; flex-wrap:wrap;">
        <span class="chip">{detail.document.status}</span>
        <span class="chip {detail.document.is_scanned ? 'amber' : 'blue'}">
          {detail.document.is_scanned ? "Taranmış" : "Sayısal"}
        </span>
        {#if anySignature}<span class="chip green">İmza ✓</span>{:else}<span class="chip red">İmza yok</span>{/if}
        {#if anyStamp}<span class="chip green">Mühür ✓</span>{/if}
        {#if renderCount > 0}<span class="chip blue">🔍 {renderCount} kez yeniden okundu</span>{/if}
      </div>
    </div>
  </div>

  <div class="split">
    <div class="card">
      <h3>Belgenin aslı</h3>
      {#if isPdf}
        <iframe class="preview" title="Belge önizleme" src={fileUrl(docId)}></iframe>
      {:else if isImage}
        <img class="preview" alt="Belge önizleme" src={fileUrl(docId)} />
      {:else}
        <p class="muted">Bu dosya türü için önizleme yok.
          <a href={fileUrl(docId)} target="_blank" rel="noreferrer">İndir</a>
        </p>
      {/if}
    </div>
    <div class="card">
      <h3>Çıkarılan metin</h3>
      {#if detail.document.raw_text}
        <pre class="text">{detail.document.raw_text}</pre>
      {:else}
        <p class="muted">Metin henüz hazır değil (okuma sürüyor olabilir).</p>
      {/if}
    </div>
  </div>

  <div class="card">
    <h3>Sayfalar</h3>
    {#each detail.pages as p}
      <div class="trace-step">
        <strong>Sayfa {p.page_no}</strong>
        {#if p.has_signature}<span class="chip green" style="margin-left:6px">imza</span>{/if}
        {#if p.has_stamp}<span class="chip green" style="margin-left:6px">mühür</span>{/if}
        <div class="muted" style="margin-top:4px">{(p.text || "").slice(0, 160)}…</div>
      </div>
    {/each}
  </div>
{:else}
  <p class="muted">Evrak bulunamadı.</p>
{/if}
