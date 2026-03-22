const el = document.querySelector<HTMLDivElement>('#app');
const TITLE = "stockradar-backend";
if (el) {
  el.innerHTML = `
    <main style="font-family:system-ui;padding:2rem;background:#0a0a0a;color:#e0e0e0;min-height:100vh;">
      <h1 style="letter-spacing:0.08em;">${TITLE}</h1>
      <p style="color:#888;">Open Adventure Workspace（最小模板）。运行 <code>npm install && npm run dev</code> 后刷新。</p>
    </main>
  `;
}
