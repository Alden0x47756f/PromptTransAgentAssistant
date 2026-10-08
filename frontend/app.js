/* The native bridge owns all inference and model state. No frontend network calls. */
'use strict';
const $ = id => document.getElementById(id);
let backend = null;
let state = {state:'unloaded',busy:false};
let activeBody = null;
let activeResult = null;
let output = '';
let submitting = false;
let pendingCopyButton = null;
let renderFrame = null;
let scrollFrame = null;

function notice(text='') { $('notice').textContent=text; $('notice').hidden=!text; }
function scroll() {
  if(scrollFrame!==null)return;
  scrollFrame=requestAnimationFrame(()=>{
    scrollFrame=null;
    const conversation=$('conversation');
    conversation.scrollTop=conversation.scrollHeight;
  });
}
function queueResultText() {
  if(renderFrame!==null)return;
  renderFrame=requestAnimationFrame(()=>{
    renderFrame=null;
    if(activeBody)activeBody.textContent=output;
    scroll();
  });
}
function updateState(next) {
  state=next;
  const pending=['loading','unloading'].includes(state.state);
  const loaded=state.state==='ready';
  $('status').textContent=state.detail;
  $('status-dot').className='status-dot'+(loaded?' ready':'')+(pending?' pending':'');
  $('model-toggle').className='toggle'+(loaded||state.state==='unloading'?' on':'')+(pending?' pending':'');
  $('model-toggle').disabled=pending||!!state.saving||!backend;
  $('model-toggle').setAttribute('aria-checked',String(loaded||state.state==='unloading'));
  $('model-toggle').setAttribute('aria-busy',String(pending));
  $('model-toggle').setAttribute('aria-label',state.mode==='api'?(loaded?'停用 API':'启用 API'):(loaded?'卸载模型':'加载模型'));
  if(typeof state.model_label==='string') { $('model-label').textContent=state.model_label;$('model-label').title=state.model_label; }
  if(typeof state.model_badge==='string') $('model-badge').textContent=state.model_badge;
  document.querySelector('.edition').textContent=state.mode==='api'?'API EDITION':'LOCAL EDITION';
  $('send').classList.toggle('stop',state.busy);
  $('send').setAttribute('aria-label',state.busy?'停止生成':'发送需求');
  $('send').disabled=!backend||!!state.saving||(!state.busy&&(!loaded||!$('input').value.trim()||submitting));
  $('new-chat').disabled=state.busy||submitting||!!state.saving;
  $('input').readOnly=state.busy||submitting;
  $('input-hint').textContent=state.busy?'正在处理 · 点击 ■ 停止':loaded?'Enter 发送 · Shift + Enter 换行':pending?'请等待操作完成':state.mode==='api'?'API 未启用，可打开右上角开关':'模型未加载，可打开右上角开关';
  updateSettingsState();
  if(state.state==='error') notice(state.detail);
}
function addMessage(role,text) {
  const article=document.createElement('article'); article.className='message '+role;
  const label=document.createElement('div'); label.className='message-label';
  const name=document.createElement('span'); name.textContent=role==='user'?'SOURCE':'RESULT'; label.append(name);
  const body=document.createElement('div'); body.className='message-body'; body.textContent=text;
  article.append(label,body); $('messages').append(article);
  return {article,label,body};
}
function appendFormatted(container,text) {
  // Render only emphasis and inline code, always using text nodes (no HTML).
  const pattern=/(\*\*([^\n]+?)\*\*|`([^`\n]+)`)/g;
  let cursor=0;
  for(const match of text.matchAll(pattern)) {
    container.append(document.createTextNode(text.slice(cursor,match.index)));
    const node=document.createElement(match[2]?'strong':'code');node.textContent=match[2]||match[3];container.append(node);
    cursor=match.index+match[0].length;
  }
  container.append(document.createTextNode(text.slice(cursor)));
}
function renderResult() {
  activeBody.replaceChildren();
  const pattern=/(`{3,})(?:prompt|text|markdown)?[ \t]*\r?\n([\s\S]*?)\r?\n\1/;
  const match=output.match(pattern);
  let copy=output;
  if(match) {
    const before=output.slice(0,match.index).trim();
    if(before) { const p=document.createElement('div'); appendFormatted(p,before); activeBody.append(p); }
    const block=document.createElement('pre'); block.className='prompt-block'; block.textContent=match[2].trim(); activeBody.append(block);
    const after=output.slice(match.index+match[0].length).trim();
    if(after) { const p=document.createElement('div'); appendFormatted(p,after); activeBody.append(p); }
    copy=match[2].trim();
  } else appendFormatted(activeBody,output);
  const button=document.createElement('button'); button.className='copy-button'; button.textContent='复制结果';
  button.addEventListener('click',()=>{pendingCopyButton=button;backend.copyText(copy);});
  const actions=document.createElement('div');actions.className='message-actions';actions.append(button);
  activeResult.article.append(actions);
}
function finish(note) {
  if(renderFrame!==null){cancelAnimationFrame(renderFrame);renderFrame=null;}
  if(activeBody) {
    if(output) renderResult(); else activeBody.textContent=note||'未生成内容';
    if(note&&output) { const p=document.createElement('div');p.className='result-note';p.textContent=note;activeBody.after(p); }
  }
  activeBody=null; activeResult=null; submitting=false; scroll();
}
function handleEvent(raw) {
  const event=JSON.parse(raw);
  if(handleSettingsEvent(event))return;
  switch(event.type) {
    case 'state': updateState(event);break;
    case 'accepted':
      submitting=false; notice();
      addMessage('user',event.text); activeResult=addMessage('assistant','');activeBody=activeResult.body;
      const wait=document.createElement('span');wait.className='thinking';wait.textContent=event.direction+' · 思考中…';activeBody.append(wait);
      output='';$('input').value='';scroll();break;
    case 'chunk': output+=event.text;if(activeBody)queueResultText();break;
    case 'progress': if(activeBody&&!output)activeBody.textContent=event.message;break;
    case 'done': finish(event.reason==='length'?'已达到输出长度上限，可在配置中调高 max_tokens。':'');break;
    case 'copied':
      if(pendingCopyButton?.isConnected){const button=pendingCopyButton;button.textContent='已复制';setTimeout(()=>button.textContent='复制结果',1600);pendingCopyButton=null;}
      else if(!$('modal-layer').hidden){$('diagnostic-copy').textContent='已复制';setTimeout(()=>$('diagnostic-copy').textContent='复制诊断信息',1600);}break;
    case 'cancelled': finish('已停止；本次内容未加入模型对话历史。');break;
    case 'error': notice(event.message);finish('本次生成未完成，输入已保留在对话中。');updateState(state);showModal({title:'操作未完成',message:event.message+(event.diagnostic?.reason?'\n'+event.diagnostic.reason:''),diagnostic:event.diagnostic});break;
    case 'reset':
      if(renderFrame!==null){cancelAnimationFrame(renderFrame);renderFrame=null;}
      activeBody=null;activeResult=null;output='';pendingCopyButton=null;
      $('messages').replaceChildren();notice('新对话已开始，提示词配置已重新读取。');break;
  }
}
function send() {
  if(!backend)return;
  if(state.busy){backend.stop();return;}
  const text=$('input').value.trim();
  if(!text||state.state!=='ready'||submitting)return;
  submitting=true;updateState(state);backend.send(text);
}
$('send').addEventListener('click',send);
$('input').addEventListener('input',()=>updateState(state));
$('input').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();send();}});
$('model-toggle').addEventListener('click',()=>{notice();state.state==='ready'?backend.unloadModel():backend.loadModel();});
$('new-chat').addEventListener('click',()=>backend&&backend.newConversation());
$('config').addEventListener('click',()=>backend&&backend.openConfig());
$('collapse').addEventListener('click',()=>backend&&backend.collapse());
document.querySelector('.titlebar').addEventListener('mousedown',event=>{if(backend&&event.button===0&&!event.target.closest('button'))backend.beginDrag();});
if(typeof qt!=='undefined'&&typeof QWebChannel!=='undefined') {
  new QWebChannel(qt.webChannelTransport,channel=>{backend=channel.objects.backend;backend.event.connect(handleEvent);backend.initialize();});
} else { $('status').textContent='桌面预览 · 请通过启动器使用'; notice('此页面需要桌面应用连接本地模型。'); }
document.addEventListener('keydown',event=>{
  if(event.key!=='Escape')return;
  if(!$('modal-layer').hidden)closeModal();
  else if(!$('settings-view').hidden)switchView('chat');
  else if(backend)backend.collapse();
});
