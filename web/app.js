const API = window.RA_STUDIO_API || 'http://localhost:8000';
const views = [...document.querySelectorAll('.view')];
document.querySelectorAll('nav button').forEach(btn => btn.onclick = () => {
  views.forEach(v => v.classList.toggle('active', v.id === btn.dataset.view));
  if (btn.dataset.view === 'library') loadModules();
});
async function loadModules(){
  const r = await fetch(`${API}/modules`); const items = await r.json();
  document.querySelector('#module-list').innerHTML = items.length ? items.map(x => `<article><strong>${x.name}</strong><div>${x.module_id.value} · ${x.revision_id.value}</div><code>${x.content_hash.value}</code><div>${x.state}</div></article>`).join('') : '<p>No modules yet.</p>';
}
document.querySelector('#module-form').onsubmit = async e => {
  e.preventDefault(); const body = Object.fromEntries(new FormData(e.target).entries());
  const r = await fetch(`${API}/modules`, {method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify(body)});
  document.querySelector('#lab-result').textContent = JSON.stringify(await r.json(), null, 2);
  if(r.ok) e.target.reset();
};
loadModules();