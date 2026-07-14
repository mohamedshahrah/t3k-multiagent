<script>
  export let documents = [];
  export let onOpen;

  const STATUS_CLASS = {
    ALINDI: "blue", OKUNUYOR: "amber", OKUNDU: "green",
    "İNCELEME_GEREKLİ": "amber", "TRİYAJ": "amber", "REDDEDİLDİ": "red",
  };
  const cls = (s) => STATUS_CLASS[s] || "";
  const when = (t) => (t ? String(t).replace("T", " ").slice(0, 19) : "");
</script>

{#if documents.length === 0}
  <p class="muted">Henüz evrak yok. Yukarıdan bir belge yükleyin.</p>
{:else}
  <table>
    <thead>
      <tr><th>Dosya</th><th>Tür</th><th>Sayfa</th><th>Durum</th><th>Alındığı zaman</th></tr>
    </thead>
    <tbody>
      {#each documents as d}
        <tr class="click" on:click={() => onOpen(d.id)}>
          <td>{d.filename}</td>
          <td>{d.is_scanned ? "Taranmış" : "Sayısal"}</td>
          <td>{d.page_count}</td>
          <td><span class="chip {cls(d.status)}">{d.status}</span></td>
          <td class="muted">{when(d.received_at)}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}
