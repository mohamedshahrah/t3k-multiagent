<script>
  export let view;
  export let onNavigate;
  const items = [
    { id: "gelen",   label: "Gelen Evrak",   icon: "📥" },
    { id: "detay",   label: "Evrak Detayı",  icon: "📄" },
    { id: "kutu",    label: "Gelen Kutusu",  icon: "✉️" },
    { id: "yonetim", label: "Yönetim",       icon: "⚙️" },
    { id: "denetim", label: "Denetim Kaydı", icon: "🔎" },
  ];
</script>

<aside class="sidebar">
  <div class="brand">Evrak Asistanı<small>yerel • çok-ajanlı</small></div>
  {#each items as it}
    <div class="nav-item {view === it.id ? 'active' : ''}" on:click={() => onNavigate(it.id)}>
      <span>{it.icon}</span><span>{it.label}</span>
    </div>
  {/each}
</aside>
