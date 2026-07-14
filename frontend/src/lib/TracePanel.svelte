<script>
  import { api } from "../api.js";
  export let docId;
  let trace = null;

  $: if (docId) load(docId);
  async function load(id) { trace = await api("GET", `/documents/${id}/trace`); }
</script>

{#if !docId}
  <p class="muted">Bir evrak seçildiğinde ajanların akıl yürütme izi burada görünür.</p>
{:else if !trace}
  <p class="muted">Yükleniyor…</p>
{:else}
  {#each trace.agent_log as a}
    <div class="card">
      <div style="display:flex; justify-content:space-between;">
        <strong>{a.agent}</strong>
        <span class="muted">{a.model} • {a.latency_ms} ms • {a.tool_steps} adım</span>
      </div>
      {#if a.degraded}<span class="chip amber">degraded → tek-atış'a düştü</span>{/if}
      {#each (trace.tool_log || []).filter((t) => t.agent_log_id === a.id) as t}
        <div class="trace-step {t.ok ? '' : 'degraded'}">
          🔎 <strong>{t.tool}</strong>
          <span class="muted">({JSON.stringify(t.args)})</span>
          → {t.result_summary}
          <div class="muted" style="font-style:italic">{t.thought_tr}</div>
        </div>
      {/each}
    </div>
  {:else}
    <p class="muted">Bu evrak için henüz ajan kaydı yok.</p>
  {/each}
{/if}
