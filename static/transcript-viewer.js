async function loadTranscript() {
  const viewer = document.getElementById("transcript-viewer");
  if (!viewer || viewer.dataset.loaded) return;
  const url = viewer.dataset.transcript;
  if (!url) return;
  try {
    const resp = await fetch(url);
    const data = await resp.json();
    const keys = Object.keys(data);
    let html = "";
    for (const key of keys) {
      const src = data[key];
      const active = key === keys[0] ? " active" : "";
      if (src.type === "srt" && src.segments) {
        let lines = "";
        for (const seg of src.segments) {
          const h = Math.floor(seg.start / 3600);
          const m = Math.floor((seg.start % 3600) / 60);
          const s = Math.floor(seg.start % 60);
          const ts = (h ? h + ":" : "") + String(m).padStart(2,"0") + ":" + String(s).padStart(2,"0");
          const escaped = seg.text.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
          lines += '<div class="transcript-line"><span class="timestamp" data-time="' + seg.start + '">' + ts + '</span><span class="transcript-text">' + escaped + '</span></div>';
        }
        html += '<div class="transcript-panel' + active + '" id="panel-' + key + '">' + lines + '</div>';
      } else {
        const escaped = src.text.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
        html += '<div class="transcript-panel' + active + '" id="panel-' + key + '"><div class="transcript-plain">' + escaped + '</div></div>';
      }
    }
    const loading = viewer.querySelector(".transcript-loading");
    if (loading) loading.remove();
    viewer.insertAdjacentHTML("beforeend", html);
    viewer.dataset.loaded = "1";
    // Bind timestamp clicks
    viewer.querySelectorAll(".timestamp").forEach(ts => {
      ts.addEventListener("click", () => {
        const time = ts.dataset.time;
        const iframe = document.querySelector("iframe");
        if (iframe) {
          const seconds = parseFloat(time);
          iframe.src = iframe.src.split("?")[0] + "?autoplay=1&start=" + Math.floor(seconds);
        }
      });
    });
  } catch(e) {
    const loading = viewer.querySelector(".transcript-loading");
    if (loading) loading.textContent = "Failed to load transcript.";
  }
}
loadTranscript();

function switchTab(tabName) {
  document.querySelectorAll(".transcript-tab").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".transcript-panel").forEach(p => p.classList.remove("active"));
  document.querySelector('.transcript-tab[data-tab="' + tabName + '"]').classList.add("active");
  document.getElementById("panel-" + tabName).classList.add("active");
}
document.querySelectorAll(".transcript-tab").forEach(tab => {
  tab.addEventListener("click", () => switchTab(tab.dataset.tab));
});

function toggleTranscriptFullscreen() {
  const viewer = document.querySelector(".transcript-viewer");
  const btn = document.querySelector(".expand-btn");
  if (viewer.classList.contains("fullscreen")) {
    viewer.classList.remove("fullscreen");
    btn.textContent = "⤢ Expand";
  } else {
    viewer.classList.add("fullscreen");
    btn.textContent = "⤓ Collapse";
  }
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    const viewer = document.querySelector(".transcript-viewer");
    if (viewer && viewer.classList.contains("fullscreen")) toggleTranscriptFullscreen();
  }
});