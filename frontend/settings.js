'use strict';
const settingElement = id => document.getElementById(id);
let settingsMode = 'local';
let settingsData = null;
let settingsDirty = false;
let apiProbePending = false;
let keyQuerySerial = 0;
let keyQueryTimer = null;
let keySavedForDraft = false;
let keyStatusError = false;
let pendingSettingsPayload = null;
let modalAction = null;
let modalPriorFocus = null;
const effortLevels = ['low','medium','high','xhigh','max','ultra'];
let effortUserTyped = false;
let effortActiveIndex = -1;

function closeEffortOptions() {
  settingElement('effort-options').hidden=true;
  settingElement('setting-api_reasoning_effort').setAttribute('aria-expanded','false');
  settingElement('setting-api_reasoning_effort').removeAttribute('aria-activedescendant');
  effortActiveIndex=-1;
}
function positionEffortOptions() {
  const popup=settingElement('effort-options');if(popup.hidden)return;
  const row=settingElement('effort-combobox').getBoundingClientRect();
  const shell=document.querySelector('.shell').getBoundingClientRect();
  const below=shell.bottom-row.bottom-12,above=row.top-shell.top-12;
  const height=Math.min(240,Math.max(80,Math.max(below,above)),popup.scrollHeight+2);
  popup.style.width=row.width+'px';popup.style.maxHeight=height+'px';
  popup.style.left=Math.max(8,row.left-shell.left-1)+'px';
  popup.style.top=(below<height&&above>below ? row.top-shell.top-height-6 : row.bottom-shell.top+6)+'px';
}
function selectEffort(value) {
  const input=settingElement('setting-api_reasoning_effort');
  input.value=value;effortUserTyped=false;settingsDirty=true;
  input.dispatchEvent(new Event('change',{bubbles:true}));
  closeEffortOptions();input.focus();closeEffortOptions();
}
function openEffortOptions() {
  const input=settingElement('setting-api_reasoning_effort'),popup=settingElement('effort-options');
  const query=effortUserTyped?input.value.trim().toLowerCase():'';
  const options=effortLevels.filter(level=>!query||level.includes(query));
  popup.replaceChildren();effortActiveIndex=-1;input.removeAttribute('aria-activedescendant');
  options.forEach((level,index)=>{
    const option=document.createElement('button');option.type='button';option.className='effort-option';
    option.id='effort-option-'+index;option.dataset.value=level;option.textContent=level;option.tabIndex=-1;
    option.setAttribute('role','option');option.setAttribute('aria-selected','false');
    option.addEventListener('mousedown',event=>event.preventDefault());
    option.addEventListener('click',()=>selectEffort(level));popup.append(option);
  });
  if(!options.length){const note=document.createElement('p');note.className='effort-empty';note.textContent='无匹配等级，可继续使用自定义值。';popup.append(note);}
  popup.hidden=false;input.setAttribute('aria-expanded','true');positionEffortOptions();
}
function stepEffort(direction) {
  const options=[...settingElement('effort-options').querySelectorAll('[role=option]')];
  if(!options.length)return;
  effortActiveIndex=effortActiveIndex<0?(direction>0?0:options.length-1):(effortActiveIndex+direction+options.length)%options.length;
  options.forEach((option,index)=>option.setAttribute('aria-selected',String(index===effortActiveIndex)));
  const option=options[effortActiveIndex];settingElement('setting-api_reasoning_effort').setAttribute('aria-activedescendant',option.id);option.scrollIntoView({block:'nearest'});
}

function switchView(name) {
  closeEffortOptions();
  settingElement('chat-view').hidden = name !== 'chat';
  settingElement('settings-view').hidden = name !== 'settings';
  if(name === 'chat') settingElement('input').focus();
}
function updateSettingsSections() {
  settingElement('mode-local').setAttribute('aria-pressed', String(settingsMode==='local'));
  settingElement('mode-api').setAttribute('aria-pressed', String(settingsMode==='api'));
  settingElement('local-fields').hidden = settingsMode !== 'local';
  settingElement('api-fields').hidden = settingsMode !== 'api';
  const anthropic = settingElement('setting-api_protocol').value === 'anthropic';
  settingElement('openai-fields').hidden = anthropic;
  settingElement('anthropic-fields').hidden = !anthropic;
  settingElement('thinking-budget-row').hidden = !anthropic || settingElement('setting-api_thinking_mode').value !== 'budget';
  settingElement('token-field-row').hidden = anthropic || settingElement('setting-api_endpoint').value !== 'chat';
}
function updateSettingsState() {
  const pending = !!state.saving || ['loading','unloading'].includes(state.state);
  settingElement('settings-save').disabled = !backend || pending || !!state.busy;
  settingElement('settings-save').textContent = state.saving ? '正在应用…' : '保存设置';
  settingElement('settings-stop').hidden = !state.busy;
  settingElement('api-model-list').disabled = !backend || apiProbePending;
  settingElement('api-model-list').textContent=apiProbePending?'正在获取并测试…':'获取模型列表并测试连接';
  settingElement('key-clear').disabled = (!keySavedForDraft&&!keyStatusError) || pending || !!state.busy || apiProbePending;
}
function clearFieldErrors() {
  document.querySelectorAll('.field.invalid').forEach(node=>node.classList.remove('invalid'));
  document.querySelectorAll('.field-error').forEach(node=>node.remove());
}
function populateSettings(data, force=false) {
  settingsData = data;
  for(const id of ['cache_type_k','cache_type_v']) {
    const select = settingElement('setting-'+id), previous=select.value;
    select.replaceChildren();
    for(const value of ['', ...data.kv_types]) {
      const option=document.createElement('option');option.value=value;option.textContent=value||'未设置';select.append(option);
    }
    select.value=previous;
  }
  if(!settingsDirty || force) {
    settingsMode=data.values.mode;
    for(const [field,value] of Object.entries(data.values)) {
      const element=settingElement('setting-'+field);
      if(element) { if(element.type==='checkbox') element.checked=!!value; else element.value=String(value); }
    }
    settingElement('setting-api_key').value='';
    settingElement('setting-api_key').type='password';
    settingElement('key-visible').textContent='显示';
    settingElement('key-visible').setAttribute('aria-pressed','false');
    settingsDirty=false;
    effortUserTyped=false;closeEffortOptions();
    clearFieldErrors();
  }
  for(const [field,value] of Object.entries(data.defaults)) {
    const element=settingElement('setting-'+field);
    if(element && element.tagName==='INPUT' && element.type!=='checkbox') element.placeholder='默认：'+value;
  }
  settingElement('setting-api_key').placeholder='输入新密钥，或留空保留已保存密钥';
  updateSettingsSections();updateSettingsState();refreshKeyStatus();
}
function collectSettings() {
  const values={mode:settingsMode};
  document.querySelectorAll('[data-field]').forEach(element=>{
    values[element.dataset.field]=element.type==='checkbox' ? element.checked : element.value.trim();
  });
  return {values,confirmed:false};
}
function fieldErrors(errors) {
  clearFieldErrors();
  for(const error of errors) {
    const element=settingElement('setting-'+error.field);
    const field=element?.closest('.field');
    if(field) {
      field.classList.add('invalid');
      const note=document.createElement('span');note.className='field-error';note.textContent=error.message;field.append(note);
    }
  }
  showModal({title:'请检查参数',message:'设置尚未保存，请修改以下参数。',items:errors.map(e=>e.message),confirmText:'返回修改'});
}
function clientValidation() {
  const errors=[];
  const active=settingElement(settingsMode==='local' ? 'local-fields' : 'api-fields');
  active.querySelectorAll('[data-kind]').forEach(element=>{
    if(element.closest('[hidden]'))return;
    const value=element.value.trim();if(!value)return;
    const valid=element.dataset.kind==='int' ? /^[+-]?[0-9]+$/.test(value) : /^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/.test(value);
    if(!valid || !Number.isFinite(Number(value))) errors.push({field:element.dataset.field,message:element.closest('.field').childNodes[0].textContent.trim()+'：请输入合法的'+(element.dataset.kind==='int'?'整数':'有限数字')+'。'});
  });
  if(errors.length){fieldErrors(errors);return false;}return true;
}
function submitSettings() {
  if(!backend || settingElement('settings-save').disabled || !clientValidation())return;
  clearFieldErrors();pendingSettingsPayload=collectSettings();backend.saveSettings(JSON.stringify(pendingSettingsPayload));
}
function refreshKeyStatus() {
  if(!backend || !settingsData)return;
  const serial=++keyQuerySerial;
  const protocol=settingElement('setting-api_protocol').value;
  const base_url=settingElement('setting-api_base_url').value.trim() || settingsData.api_urls[protocol];
  backend.keyStatus(JSON.stringify({protocol,base_url}), raw=>{
    if(serial!==keyQuerySerial)return;
    const value=JSON.parse(raw);
    settingElement('key-status').textContent=value.error ? value.error : value.saved ? '此地址已保存密钥。留空保留；输入新密钥替换。' : '此地址尚未保存密钥，请填写后保存。';
    keySavedForDraft=!!value.saved;keyStatusError=!!value.error;updateSettingsState();
  });
}
function showModal({title,message='',items=[],diagnostic=null,confirmText='知道了',cancelText=null,action=null}) {
  closeEffortOptions();
  modalPriorFocus=document.activeElement;
  settingElement('modal-title').textContent=title;settingElement('modal-message').textContent=message;
  const list=settingElement('modal-items');list.replaceChildren();list.hidden=!items.length;
  items.forEach(text=>{const item=document.createElement('li');item.textContent=text;list.append(item);});
  settingElement('modal-details').hidden=!diagnostic;settingElement('modal-details').open=false;
  settingElement('modal-diagnostic').textContent=diagnostic ? diagnostic.summary+'\n\n'+diagnostic.details : '';
  settingElement('modal-tools').hidden=!diagnostic;
  settingElement('modal-confirm').textContent=confirmText;
  settingElement('modal-cancel').hidden=!cancelText;settingElement('modal-cancel').textContent=cancelText||'返回修改';
  modalAction=action;settingElement('modal-layer').hidden=false;
  settingElement('chat-view').inert=true;settingElement('settings-view').inert=true;
  settingElement('modal-confirm').focus();
}
function closeModal() {
  settingElement('modal-layer').hidden=true;modalAction=null;
  settingElement('chat-view').inert=false;settingElement('settings-view').inert=false;
  if(modalPriorFocus?.isConnected)modalPriorFocus.focus();
}
function handleSettingsEvent(event) {
  switch(event.type) {
    case 'settings': populateSettings(event);switchView('settings');settingElement('settings-message').textContent='';return true;
    case 'settings_confirm': {
      const payload=pendingSettingsPayload;
      showModal({title:'确认使用默认值',items:event.defaults.map(d=>d.message),confirmText:'确认使用默认值',cancelText:'返回修改',action:()=>{
        if(!payload)return;
        payload.confirmed=true;backend.saveSettings(JSON.stringify(payload));
      }});return true;
    }
    case 'settings_invalid': fieldErrors(event.errors);return true;
    case 'settings_error': showModal({title:'操作未完成',message:event.message+(event.diagnostic?.reason?'\n'+event.diagnostic.reason:''),diagnostic:event.diagnostic});return true;
    case 'settings_saved':
      pendingSettingsPayload=null;populateSettings(event,true);
      settingElement('settings-message').textContent=event.reload?'设置已保存，正在应用新的推理配置。':'设置已保存，采样参数从下一次生成生效。';return true;
    case 'file_selected': settingElement('setting-'+event.field).value=event.path;settingsDirty=true;return true;
    case 'api_probe_pending': apiProbePending=event.pending;updateSettingsState();settingElement('settings-message').textContent=event.pending?'正在获取模型列表并测试连接与鉴权…':settingElement('settings-message').textContent;return true;
    case 'api_models': {
      const list=settingElement('api-models');list.replaceChildren();
      event.models.forEach(model=>{const option=document.createElement('option');option.value=model.id;option.label=model.name;list.append(option);});
      settingElement('settings-message').textContent=event.message+' 已取得 '+event.models.length+' 个模型建议。';return true;
    }
    case 'key_cleared': settingElement('setting-api_key').value='';refreshKeyStatus();settingElement('settings-message').textContent='该地址已保存密钥已清除。';return true;
    default:return false;
  }
}
settingElement('settings-back').addEventListener('click',()=>switchView('chat'));
for(const mode of ['local','api']) settingElement('mode-'+mode).addEventListener('click',()=>{settingsMode=mode;settingsDirty=true;updateSettingsSections();});
settingElement('settings-form').addEventListener('submit',event=>{event.preventDefault();submitSettings();});
settingElement('settings-form').addEventListener('input',event=>{settingsDirty=true;event.target.closest('.field')?.classList.remove('invalid');event.target.closest('.field')?.querySelector('.field-error')?.remove();});
settingElement('settings-form').addEventListener('change',()=>{settingsDirty=true;updateSettingsSections();});
settingElement('settings-save').addEventListener('click',submitSettings);
settingElement('settings-stop').addEventListener('click',()=>backend&&backend.stop());
settingElement('browse-model').addEventListener('click',()=>backend&&backend.browseFile('model'));
settingElement('browse-engine').addEventListener('click',()=>backend&&backend.browseFile('engine'));
settingElement('edit-system').addEventListener('click',()=>backend&&backend.openPrompt('system'));
settingElement('edit-user').addEventListener('click',()=>backend&&backend.openPrompt('user'));
settingElement('key-visible').addEventListener('click',()=>{
  const input=settingElement('setting-api_key'),visible=input.type==='password';input.type=visible?'text':'password';
  settingElement('key-visible').textContent=visible?'隐藏':'显示';settingElement('key-visible').setAttribute('aria-pressed',String(visible));
});
settingElement('setting-api_protocol').addEventListener('change',()=>{
  if(settingsData) {
    const input=settingElement('setting-api_base_url');
    if(!input.value.trim()||Object.values(settingsData.api_urls).includes(input.value.trim())) input.value=settingsData.api_urls[settingElement('setting-api_protocol').value];
  }
  updateSettingsSections();refreshKeyStatus();
});
settingElement('setting-api_base_url').addEventListener('input',()=>{clearTimeout(keyQueryTimer);keyQueryTimer=setTimeout(refreshKeyStatus,180);});
settingElement('key-clear').addEventListener('click',()=>{
  if(!backend||!settingsData)return;
  showModal({title:'清除已保存密钥？',message:'只清除当前协议与地址的密钥。如果正在使用该 API，将停用当前连接。',confirmText:'清除密钥',cancelText:'取消',action:()=>backend.clearKey(JSON.stringify({protocol:settingElement('setting-api_protocol').value,base_url:settingElement('setting-api_base_url').value.trim()||settingsData.api_urls[settingElement('setting-api_protocol').value]}))});
});
settingElement('api-model-list').addEventListener('click',()=>{
  if(backend){settingElement('settings-message').textContent='';backend.probeApi(JSON.stringify(collectSettings()));}
});
settingElement('setting-api_reasoning_effort').addEventListener('focus',openEffortOptions);
settingElement('setting-api_reasoning_effort').addEventListener('click',openEffortOptions);
settingElement('setting-api_reasoning_effort').addEventListener('input',()=>{effortUserTyped=true;openEffortOptions();});
settingElement('setting-api_reasoning_effort').addEventListener('blur',()=>setTimeout(()=>{
  if(!settingElement('effort-combobox').contains(document.activeElement)&&!settingElement('effort-options').contains(document.activeElement))closeEffortOptions();
},0));
settingElement('setting-api_reasoning_effort').addEventListener('keydown',event=>{
  if(event.key==='ArrowDown'||event.key==='ArrowUp') {
    event.preventDefault();if(settingElement('effort-options').hidden)openEffortOptions();stepEffort(event.key==='ArrowDown'?1:-1);
  } else if(event.key==='Enter'&&!settingElement('effort-options').hidden) {
    event.preventDefault();event.stopPropagation();
    const selected=settingElement('effort-options').querySelector('[aria-selected=true]');if(selected)selectEffort(selected.dataset.value);else closeEffortOptions();
  } else if(event.key==='Escape'&&!settingElement('effort-options').hidden) {event.preventDefault();event.stopPropagation();closeEffortOptions();}
});
settingElement('effort-toggle').addEventListener('click',()=>{
  if(settingElement('effort-options').hidden){settingElement('setting-api_reasoning_effort').focus();openEffortOptions();}else closeEffortOptions();
});
document.addEventListener('pointerdown',event=>{if(!settingElement('effort-combobox').contains(event.target)&&!settingElement('effort-options').contains(event.target))closeEffortOptions();});
settingElement('settings-form').addEventListener('scroll',positionEffortOptions);
window.addEventListener('resize',positionEffortOptions);
settingElement('modal-cancel').addEventListener('click',()=>{pendingSettingsPayload=null;closeModal();});
settingElement('modal-confirm').addEventListener('click',()=>{const action=modalAction;closeModal();if(action)action();});
settingElement('diagnostic-copy').addEventListener('click',()=>backend&&backend.copyText(settingElement('modal-diagnostic').textContent));
settingElement('diagnostic-logs').addEventListener('click',()=>backend&&backend.openLogs());
document.addEventListener('keydown',event=>{
  if(settingElement('modal-layer').hidden)return;
  if(event.key==='Tab') {
    const controls=[...settingElement('modal-layer').querySelectorAll('button,summary')].filter(e=>e.getClientRects().length&&!e.disabled);
    const first=controls[0],last=controls[controls.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
  }
});
