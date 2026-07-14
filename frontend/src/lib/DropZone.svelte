<script>
  import { createEventDispatcher } from "svelte";
  import { pickAndUpload, uploadBlob } from "../api.js";
  const dispatch = createEventDispatcher();
  let dragging = false;

  async function handleResult(r) {
    if (r.cancelled) return;
    if (!r.ok && r.result?.error === "duplicate") {
      dispatch("toast", { message: "Bu belge zaten yüklenmiş (yinelenen).", error: true });
    } else if (r.ok) {
      dispatch("toast", { message: `Evrak alındı: ${r.result.filename}`, error: false });
      dispatch("uploaded", r.result);
    } else {
      dispatch("toast", { message: "Yükleme başarısız.", error: true });
    }
  }

  async function pick() { handleResult(await pickAndUpload()); }

  async function onDrop(e) {
    e.preventDefault(); dragging = false;
    const file = e.dataTransfer?.files?.[0];
    if (file) handleResult(await uploadBlob(file, file.name));
  }
</script>

<div class="dropzone {dragging ? 'drag' : ''}"
     on:click={pick}
     on:dragover|preventDefault={() => (dragging = true)}
     on:dragleave={() => (dragging = false)}
     on:drop={onDrop}>
  <div style="font-size:32px">📄⬆️</div>
  <p><strong>Evrakı buraya sürükleyin</strong> ya da tıklayıp seçin</p>
  <p class="muted">PDF, PNG, JPG • yükleme sonrası okuma otomatik başlar</p>
</div>
