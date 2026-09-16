const API = window.RA_STUDIO_API || 'http://localhost:8000';
const $ = s => document.querySelector(s);
const show = (id, data) => $(id).textContent = JSON.stringify(data, null, 2);
const token = () => localStorage.getItem('raStudioToken') || window.RA_STUDIO_TOKEN || '';
async function call(path, method='GET', body){
  const headers = {};
  if(body) headers['content-type']='application/json';
  if(token()) headers['authorization']=`Bearer ${token()}`;
  const r = await fetch(`${API}${path}`, {method, headers, body: body ? JSON.stringify(body) : undefined});
  const data = await r.json(); if(!r.ok) throw new Error(data.detail || JSON.stringify(data)); return data;
}
$('#token').value = token();
$('#save-token').onclick = () => { localStorage.setItem('raStudioToken', $('#token').value.trim()); };
document.querySelectorAll('nav button').forEach(btn => btn.onclick = () => { document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === btn.dataset.view)); if(btn.dataset.view==='library') loadModules(); });
async function health(){try{await call('/health'); $('#health').textContent='backend online'; $('#health').className='ok'}catch{$('#health').textContent='backend offline'; $('#health').className='bad'}}
async function loadModules(){try{const items=await call('/modules'); $('#module-list').innerHTML=items.length?items.map(x=>`<article><strong>${x.name}</strong><div>${x.module_id.value} · ${x.revision_id.value} · ${x.state}</div><code>${x.content_hash.value}</code></article>`).join(''):'<p>No modules yet.</p>'}catch(e){$('#module-list').textContent=e.message}}
function formJson(form){return Object.fromEntries(new FormData(form).entries())}
function blankToNull(obj, key){if(obj[key]==='') obj[key]=null;}
$('#module-form').onsubmit=async e=>{e.preventDefault();const b=formJson(e.target);try{show('#lab-result',await call('/modules','POST',b));loadModules()}catch(x){show('#lab-result',{error:x.message})}};
$('#candidate-form').onsubmit=async e=>{e.preventDefault();const b=formJson(e.target);try{show('#lab-result',await call(`/modules/${encodeURIComponent(b.revision_id)}/candidate`,'POST'))}catch(x){show('#lab-result',{error:x.message})}};
$('#sandbox-form').onsubmit=async e=>{e.preventDefault();const b=formJson(e.target),rev=b.revision_id;delete b.revision_id;b.expected_contains=b.expected_contains?[b.expected_contains]:[];try{show('#sandbox-result',await call(`/modules/${encodeURIComponent(rev)}/sandbox`,'POST',b))}catch(x){show('#sandbox-result',{error:x.message})}};
$('#compare-form').onsubmit=async e=>{e.preventDefault();const b=formJson(e.target);b.expected_contains=b.expected_contains?[b.expected_contains]:[];try{show('#sandbox-result',await call('/effects/compare','POST',b))}catch(x){show('#sandbox-result',{error:x.message})}};
$('#compose-form').onsubmit=async e=>{e.preventDefault();const b=formJson(e.target);b.revision_ids=b.revision_ids.split(',').map(x=>x.trim()).filter(Boolean);try{show('#canvas-result',await call('/compositions','POST',b))}catch(x){show('#canvas-result',{error:x.message})}};
$('#build-form').onsubmit=async e=>{e.preventDefault();const b=formJson(e.target),id=b.composition_id;delete b.composition_id;blankToNull(b,'predecessor_baseline_id');try{show('#canvas-result',await call(`/compositions/${encodeURIComponent(id)}/build`,'POST',b))}catch(x){show('#canvas-result',{error:x.message})}};
$('#review-form').onsubmit=async e=>{e.preventDefault();const b=formJson(e.target);b.passed=e.target.elements.passed.checked;try{show('#gov-result',await call('/reviews','POST',b))}catch(x){show('#gov-result',{error:x.message})}};
$('#freeze-form').onsubmit=async e=>{e.preventDefault();try{show('#gov-result',await call('/freezes','POST',formJson(e.target)))}catch(x){show('#gov-result',{error:x.message})}};
$('#baseline-form').onsubmit=async e=>{e.preventDefault();const b=formJson(e.target);blankToNull(b,'expected_predecessor_baseline_id');try{show('#gov-result',await call('/baselines','POST',b))}catch(x){show('#gov-result',{error:x.message})}};
$('#deploy-form').onsubmit=async e=>{e.preventDefault();try{show('#gov-result',await call('/deployments','POST',formJson(e.target)))}catch(x){show('#gov-result',{error:x.message})}};
$('#refresh').onclick=loadModules; health(); loadModules();