const API = window.RA_STUDIO_API || '/api';
const $ = s => document.querySelector(s);
const show = (id, data) => $(id).textContent = JSON.stringify(data, null, 2);
const session = () => ({
  token: localStorage.getItem('raStudioToken') || window.RA_STUDIO_TOKEN || '',
  workspace: localStorage.getItem('raStudioWorkspace') || 'integration-ws',
  recoveryEpoch: Number(localStorage.getItem('raStudioRecoveryEpoch') || '1')
});
const uid = prefix => `${prefix}-${crypto.randomUUID()}`;
async function call(path, method='GET', body){
  const s=session(), headers={};
  if(body) headers['content-type']='application/json';
  if(s.token) headers['authorization']=`Bearer ${s.token}`;
  const r=await fetch(`${API}${path}`,{method,headers,body:body?JSON.stringify(body):undefined});
  const data=await r.json();
  if(!r.ok) throw new Error(data.detail || JSON.stringify(data));
  return data;
}
async function command(op,target,payload={},idem=null){
  const s=session();
  return call('/commands','POST',{
    command_id:uid('cmd'),
    operation_descriptor_id:op,
    exact_target_ref:target,
    workspace_ref:s.workspace,
    idempotency_key:idem || uid('idem'),
    expected_recovery_epoch:s.recoveryEpoch,
    payload
  });
}
function formJson(form){return Object.fromEntries(new FormData(form).entries())}
function blankToNull(obj,key){if(obj[key]==='') obj[key]=null}

$('#token').value=session().token;
$('#workspace').value=session().workspace;
$('#recovery-epoch').value=String(session().recoveryEpoch);
$('#save-session').onclick=()=>{
  localStorage.setItem('raStudioToken',$('#token').value.trim());
  localStorage.setItem('raStudioWorkspace',$('#workspace').value.trim());
  localStorage.setItem('raStudioRecoveryEpoch',$('#recovery-epoch').value);
};
document.querySelectorAll('nav button').forEach(btn=>btn.onclick=()=>{
  document.querySelectorAll('.view').forEach(v=>v.classList.toggle('active',v.id===btn.dataset.view));
  if(btn.dataset.view==='library') loadModules();
});
async function health(){try{await call('/health');$('#health').textContent='backend online';$('#health').className='ok'}catch{$('#health').textContent='backend offline';$('#health').className='bad'}}
async function loadModules(){try{const items=await call('/modules');$('#module-list').innerHTML=items.length?items.map(x=>`<article><strong>${x.name}</strong><div>${x.module_id.value} · ${x.revision_id.value} · ${x.state}</div><code>${x.content_hash.value}</code></article>`).join(''):'<p>No modules yet.</p>'}catch(e){$('#module-list').textContent=e.message}}

$('#module-form').onsubmit=async e=>{
  e.preventDefault(); const b=formJson(e.target), revision=b.revision_id; delete b.revision_id;
  try{show('#lab-result',await command('op:factory:module-revision-create',revision,b));loadModules()}
  catch(x){show('#lab-result',{error:x.message})}
};
$('#sandbox-form').onsubmit=async e=>{
  e.preventDefault(); const b=formJson(e.target),rev=b.revision_id; delete b.revision_id;
  b.expected_contains=b.expected_contains?[b.expected_contains]:[];
  try{show('#sandbox-result',await command('op:factory:controlled-execution-run',rev,b))}
  catch(x){show('#sandbox-result',{error:x.message})}
};
$('#compose-form').onsubmit=async e=>{
  e.preventDefault(); const b=formJson(e.target),id=b.composition_id; delete b.composition_id;
  b.revision_ids=b.revision_ids.split(',').map(x=>x.trim()).filter(Boolean);
  try{show('#canvas-result',await command('op:factory:composition-realize',id,b))}
  catch(x){show('#canvas-result',{error:x.message})}
};
$('#build-form').onsubmit=async e=>{
  e.preventDefault(); const b=formJson(e.target),id=b.composition_id; delete b.composition_id;
  blankToNull(b,'predecessor_baseline_id');
  try{show('#canvas-result',await command('op:factory:candidate-build',id,b))}
  catch(x){show('#canvas-result',{error:x.message})}
};
$('#review-form').onsubmit=async e=>{
  e.preventDefault(); const b=formJson(e.target),id=b.candidate_id; delete b.candidate_id;
  b.passed=e.target.elements.passed.checked; b.blockers=[];
  try{show('#gov-result',await command('op:factory:review-decision-ingest',id,b))}
  catch(x){show('#gov-result',{error:x.message})}
};
$('#freeze-form').onsubmit=async e=>{
  e.preventDefault(); const b=formJson(e.target),id=b.candidate_id; delete b.candidate_id;
  try{show('#gov-result',await command('op:factory:exact-freeze',id,b))}
  catch(x){show('#gov-result',{error:x.message})}
};
$('#baseline-form').onsubmit=async e=>{
  e.preventDefault(); const b=formJson(e.target),frozen=b.frozen_artifact_id; delete b.frozen_artifact_id;
  blankToNull(b,'expected_predecessor_baseline_id');
  try{show('#gov-result',await command('op:factory:canonical-promote',frozen,b))}
  catch(x){show('#gov-result',{error:x.message})}
};
$('#deploy-form').onsubmit=async e=>{
  e.preventDefault(); const b=formJson(e.target),frozen=b.frozen_artifact_id; delete b.frozen_artifact_id;
  const payload={
    deployment_id:b.deployment_id,
    runtime_profile:{runtime:b.runtime_name},
    environment:{name:b.environment_name},
    provider_binding:{provider:b.provider_name},
    secret_scope:{}, permission_scope:{permissions:[]},
    policy:{authority_boundary:{network:false,tools:[]}},
    runtime_boundary:{network:false,tools:[]}
  };
  try{show('#runtime-result',await command('op:deployment:authorize-deployment',frozen,payload))}
  catch(x){show('#runtime-result',{error:x.message})}
};
$('#activate-form').onsubmit=async e=>{
  e.preventDefault(); const id=formJson(e.target).deployment_id;
  try{show('#runtime-result',await command('op:deployment:activate-runtime',id,{}))}
  catch(x){show('#runtime-result',{error:x.message})}
};
$('#stop-form').onsubmit=async e=>{
  e.preventDefault(); const id=formJson(e.target).deployment_id;
  try{show('#runtime-result',await command('op:deployment:stop-runtime',id,{}))}
  catch(x){show('#runtime-result',{error:x.message})}
};

$('#refresh').onclick=loadModules;
health(); loadModules();
