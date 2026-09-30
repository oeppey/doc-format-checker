/* Live frontend integration for template and review APIs. */
const apiRequest = async (path, options = {}) => {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || ('请求失败：' + response.status));
  return data;
};
let ruleCatalog = [];
let templateFile = null;
let reviewFile = null;
const ROLE_NAMES = {
  title:'文件标题', heading1:'一级标题', heading2:'二级标题', heading3:'三级标题',
  heading4:'四级标题', body:'正文', wenhao:'文号', secrecy:'密级',
  attachment:'附件', signature:'署名', date:'成文日期'
};
const byRuleId = id => ruleCatalog.find(x => x.id === id) || {id, label:id, group:'其他', kind:'text', capability:'unavailable'};
const STATUS_LABEL = {supported:'可自动检查', partial:'部分支持', unavailable:'待实现', needs_render:'需渲染校验'};

renderList = function(){
  const box = $('tplGrid');
  if (!TEMPLATES.length) {
    box.innerHTML = '<div class="empty"><h3>还没有模板</h3><p>上传 DOCX 提取候选格式，并确认要执行的规则。</p><button class="btn btn-primary" onclick="startWizard()">新建模板</button></div>';
    return;
  }
  box.innerHTML = TEMPLATES.map(t => `
    <article class="tpl-card">
      <div class="tpl-hd"><div class="tpl-tt"><h3>${esc(t.name)} ${t.builtin ? '<span class="tag tag-green">内置</span>' : ''}</h3>
      <div class="sub"><span>${esc(t.source || '')}</span><i></i><span>${t.active_rule_count || 0} 条生效规则</span></div></div></div>
      <div class="tpl-ft"><div class="meta">${esc(t.description || '')}</div>
      <div class="acts"><button class="btn btn-sm" onclick="openDetail('${t.id}')">查看详情</button>
      <button class="btn btn-sm btn-primary" onclick="useTemplate('${t.id}')">用于审查</button>
      ${t.builtin ? '' : `<button class="btn btn-sm btn-ghost" onclick="delTemplate('${t.id}')">删除</button>`}
      </div></div></article>`).join('');
};
renderStats = function(){ $('navTplCount').textContent = TEMPLATES.length; };
renderRevTpls = function(){
  if (!TEMPLATES.some(t => t.id === reviewTplId)) reviewTplId = TEMPLATES[0]?.id || null;
  $('revTpls').innerHTML = TEMPLATES.map(t => `
    <div class="rev-tpl ${t.id === reviewTplId ? 'on' : ''}" onclick="selectRevTpl('${t.id}')">
      <div class="rt-main"><div class="rt-name">${esc(t.name)}</div>
      <div class="rt-desc">${esc(t.description || '')}</div>
      <div class="rt-meta">${t.active_rule_count || 0} 条生效规则</div></div>
      <div class="rt-check">✓</div></div>`).join('');
};
delTemplate = function(id){
  const t = TEMPLATES.find(x => x.id === id);
  if (!t || t.builtin) return;
  openModal('删除模板', '删除模板「' + t.name + '」？', async () => {
    try {
      await apiRequest('/api/templates/' + encodeURIComponent(id), {method:'DELETE'});
      closeModal(); await loadTemplates(); toast('ok', '模板已删除');
    } catch (err) { closeModal(); toast('err', err.message); }
  });
};
openDetail = async function(id){
  try {
    const t = await apiRequest('/api/templates/' + encodeURIComponent(id));
    const rules = t.compiled_rules || [];
    $('dName').textContent = t.name;
    $('dMeta').textContent = '生效规则 ' + rules.length + ' 条 · ' + (t.builtin ? '内置 YAML' : '用户确认的标准');
    const render = (items) => items.map(r => `<tr><td class="k">${esc(r.name || r.id)}</td><td class="v" colspan="4">${esc(JSON.stringify(r.params))}</td></tr>`).join('');
    $('dtPage').innerHTML = render(rules.filter(r => r.checker === 'page_setup' || r.checker === 'page_number' || r.checker === 'odd_even_setting'));
    $('dtFont').innerHTML = render(rules.filter(r => r.checker === 'font_format' || r.checker === 'char_spacing'));
    $('dtPara').innerHTML = render(rules.filter(r => r.checker === 'line_spacing'));
    $('dtPageNum').innerHTML = render(rules.filter(r =>
      ['page_number','odd_even_setting','page_number_padding'].includes(r.checker)));
    $('dtExtra').innerHTML = render(rules.filter(r => ['secrecy','heading_number','attachment','signature'].includes(r.checker)));
    ['dc1','dc2','dc3','dc4','dc5'].forEach(id => $(id).textContent = '');
    $('paperDetail').innerHTML = '<p style="padding:30px">此处为版式示意。真实逐页预览将在 PDF 定位阶段接入。</p>';
    showView('detail');
  } catch (err) { toast('err', err.message); }
};

handleFile = function(file){
  if (!/\.docx$/i.test(file.name)) { toast('err', '当前只支持 .docx，请将 .doc 另存为 .docx'); return; }
  templateFile = file; curSpec = null;
  $('upName').textContent = file.name;
  $('upSize').textContent = Math.max(1, Math.round(file.size / 1024)) + ' KB · 已就绪';
  $('upFile').classList.add('on'); updateStep1Btn();
};
clearFile = function(){
  templateFile = null; fi.value = ''; curSpec = null;
  $('upFile').classList.remove('on'); $('upName').textContent = ''; $('upSize').textContent = '';
  if ($('wzNext')) updateStep1Btn();
};
wzNext = async function(){
  if (!templateFile) { toast('err', '请先上传 DOCX'); return; }
  gotoStep(2);
  $('scanList').innerHTML = '<div class="scan-item on"><div class="tx"><b>读取 DOCX 页面、段落与样式</b><span>解析进度由真实请求决定</span></div></div>';
  $('scanPct').textContent = '处理中';
  const form = new FormData(); form.append('file', templateFile);
  try {
    curSpec = await apiRequest('/api/templates/extract', {method:'POST', body:form});
    $('scanPct').textContent = '完成';
    buildResult(); gotoStep(3);
  } catch (err) { gotoStep(1); toast('err', err.message); }
};
const ruleInputValue = r => {
  const e = r.expected || {};
  const kind = byRuleId(r.id).kind;
  if (kind === 'size') return e.width && e.height ? `${e.width} × ${e.height} mm` : '';
  if (kind === 'padding') return String(e.value ?? 1);
  if (kind === 'font') return e.value || '';
  if (kind === 'bool') return String(e.value ?? false);
  if (kind === 'alignment' || kind === 'field') return e.value || '';
  if (kind === 'line_spacing') return e.mode === 'exact' ? `${e.value} ${e.unit}` : `${e.value} 倍`;
  if (kind === 'font_size') return `${e.value} ${e.unit || 'pt'}`;
  if (typeof e.value === 'number') return `${e.value} ${e.unit || ''}`.trim();
  return e.value == null ? '' : String(e.value);
};
const parseRuleValue = (r, raw, row) => {
  const meta = byRuleId(r.id); const kind = meta.kind; const value = raw.trim();
  if (kind === 'padding') {
    const direction = row.querySelector('.padding-direction').value;
    const count = Number(value);
    if (!Number.isInteger(count) || count < 0 || count > 10)
      throw new Error('页码留空字数请输入 0–10 的整数');
    return {direction, value:count, unit:'char'};
  }
  if (meta.capability === 'unavailable') return r.expected;
  if (kind === 'font') return {value, aliases:[]};
  if (kind === 'bool') return {value:value === 'true'};
  if (kind === 'alignment' || kind === 'field') return {value};
  if (kind === 'font_size') {
    const named = /^(初号|小初|一号|小一|二号|小二|三号|小三|四号|小四|五号|小五)$/.exec(value);
    if (named) return {value:named[1]};
    const match = /^(\d+(?:\.\d+)?)\s*(?:pt|磅)$/i.exec(value);
    if (!match) throw new Error('字号请输入“小二”或“18 pt”');
    return {value:Number(match[1]), unit:'pt'};
  }
  if (kind === 'line_spacing') {
    const multiple = /^(\d+(?:\.\d+)?)\s*倍$/.exec(value);
    if (multiple) return {mode:'multiple',value:Number(multiple[1])};
    const match = /^(\d+(?:\.\d+)?)\s*(pt|磅|cm|厘米)$/i.exec(value);
    if (!match) throw new Error('当前行距请输入“32 pt”或“0.8 cm”（固定值）');
    return {mode:'exact', value:Number(match[1]), unit:/^(cm|厘米)$/i.test(match[2])?'cm':'pt'};
  }
  if (kind === 'length') {
    const match = /^(\d+(?:\.\d+)?)\s*(cm|厘米|mm|毫米)$/i.exec(value);
    if (!match) throw new Error('长度请输入“3.8 cm”或“38 mm”');
    return {value:Number(match[1]), unit:/^(mm|毫米)$/i.test(match[2])?'mm':'cm'};
  }
  if (kind === 'signed_pt') {
    const match = /^(-?\d+(?:\.\d+)?)\s*(pt|磅)$/i.exec(value);
    if (!match) throw new Error('字符间距请输入“0.4 pt”或“0 pt”');
    return {value:Number(match[1]), unit:'pt'};
  }
  return {value};
};
const ruleControl = (r, i) => {
  const meta = byRuleId(r.id), value = ruleInputValue(r);
  if (meta.kind === 'padding') {
    const direction = r.expected?.direction || (r.id.endsWith('odd_padding') ? 'right' : 'left');
    return '<div class="padding-controls"><select class="padding-direction">'+
      [['right','右空'],['left','左空'],['none','不空']].map(([v,l])=>
        '<option value="'+v+'" '+(direction===v?'selected':'')+'>'+l+'</option>').join('')+
      '</select><input class="fv rule-value" data-index="'+i+'" type="number" min="0" max="10" step="1" value="'+esc(value)+'">'+
      '<span>字</span></div>';
  }
  if (meta.kind === 'bool' || meta.kind === 'alignment') {
    const values = meta.kind === 'bool' ? [['true','是'],['false','否']] :
      r.id === 'page_number.alignment' ? [['center','居中']] :
      [['left','左对齐'],['center','居中'],['right','右对齐']];
    return `<select class="rule-value" data-index="${i}">${values.map(([v,l]) =>
      `<option value="${v}" ${value===v?'selected':''}>${l}</option>`).join('')}</select>`;
  }
  return `<input class="fv rule-value" data-index="${i}" value="${esc(value)}" ${meta.kind==='field'||meta.capability==='unavailable'?'readonly':''}>`;
};
const canEnableRule = r => {
  const meta = byRuleId(r.id);
  return !['unavailable','needs_render'].includes(meta.capability) && !r.id.startsWith('structural.') &&
    r.id !== 'page_number.decoration' &&
    !(r.id === 'paragraph.line_spacing' && r.expected?.mode !== 'exact') &&
    !(r.id === 'font.character_spacing' && r.expected?.value < 0);
};
updatePaddingControls = function(){
  const switchRow=[...document.querySelectorAll('#fmtGroups .rule-row')].find(row=>
    curSpec?.candidates[Number(row.dataset.index)]?.id==='page_number.different_odd_even');
  const input=switchRow?.querySelector('.rule-value');
  if (input) input.onchange=updatePaddingControls;
  const switchEnabled=switchRow?.querySelector('.rule-enabled');
  if (switchEnabled) switchEnabled.onchange=updatePaddingControls;
  const enabled=Boolean(switchEnabled?.checked) && input?.value==='true';
  document.querySelectorAll('#fmtGroups .rule-row').forEach(row=>{
    const id=curSpec?.candidates[Number(row.dataset.index)]?.id;
    if (id==='page_number.odd_padding' || id==='page_number.even_padding') {
      const direction=row.querySelector('.padding-direction');
      const count=row.querySelector('.rule-value');
      const checkbox=row.querySelector('.rule-enabled');
      if (!enabled) checkbox.checked=false;
      checkbox.disabled=!enabled;
      direction.onchange=updatePaddingControls;
      direction.disabled=!enabled;
      if (direction.value==='none') count.value='0';
      else if (count.value==='0') count.value='1';
      count.disabled=!enabled || direction.value==='none';
    }
  });
};
const syncRules = () => {
  document.querySelectorAll('#fmtGroups .rule-row').forEach(row => {
    const i = Number(row.dataset.index), r = curSpec.candidates[i];
    r.enabled = Boolean(row.querySelector('.rule-enabled')?.checked);
    r.expected = parseRuleValue(r, row.querySelector('.rule-value').value, row);
  });
};
const newExpected = kind => ({
  length:{value:1,unit:'cm'}, font:{value:'宋体',aliases:[]},
  font_size:{value:12,unit:'pt'}, bool:{value:true},
  alignment:{value:'left'}, line_spacing:{mode:'exact',value:28,unit:'pt'},
  signed_pt:{value:0,unit:'pt'}, field:{value:'PAGE'},
  padding:{direction:'right',value:1,unit:'char'}
}[kind] || {value:''});
buildResult = function(){
  const candidates = curSpec.candidates || [];
  const groups = ['页面设置','字体与字号','段落格式','页码与版式','其他规范要求'];
  const available = ruleCatalog.filter(x => x.capability === 'supported' ||
    ['font.character_spacing','paragraph.alignment','paragraph.line_spacing',
     'page_number.alignment'].includes(x.id));
  const toolbar = `<div class="fmt-group"><div class="fg-hd"><b>添加样本中未出现的规则</b></div>
    <div class="fmt-rows"><select id="addRuleId">${available.map(x => `<option value="${x.id}">${esc(x.label)} · ${x.id}</option>`).join('')}</select>
    <select id="addRuleRole">${Object.entries(ROLE_NAMES).map(([k,v]) =>
      `<option value="${k}">${v}</option>`).join('')}</select>
    <button class="btn btn-sm" type="button" id="addRuleBtn">添加</button></div></div>`;
  $('fmtGroups').innerHTML = toolbar + groups.map(group => {
    const rows = candidates.map((r,i) => ({r,i})).filter(({r}) => byRuleId(r.id).group===group);
    return `<div class="fmt-group"><div class="fg-hd"><b>${group}</b><span class="cnt">${rows.length} 项候选</span></div>
      <div class="fmt-rows">${rows.map(({r,i}) => {
        const meta = byRuleId(r.id), role = r.scope?.role;
        return `<div class="fmt-row rule-row" data-index="${i}">
          <label><input type="checkbox" class="rule-enabled" ${r.enabled?'checked':''}
             ${canEnableRule(r)?'':'disabled'}> ${esc(role ? ROLE_NAMES[role]+' · '+meta.label : meta.label)}</label>
          ${ruleControl(r,i)}
          <span class="conf ${meta.capability==='supported'?'':'mid'}">${STATUS_LABEL[meta.capability]}</span>
          <small>${esc(r.observed?.location || '手动添加')}</small>
        </div>`;
      }).join('') || '<p style="padding:12px">样本文档未观察到此类属性；可在上方手动添加。</p>'}</div></div>`;
  }).join('') + `<div class="fmt-group"><div class="fg-hd"><b>尚未自动检查的项目</b></div>
    <div class="fmt-rows" style="padding:12px">${ruleCatalog.filter(x=>['unavailable','needs_render'].includes(x.capability) ||
      x.group==='其他规范要求' || x.id==='page_number.decoration').map(x=>esc(x.label)).join('、')}</div></div>`;
  $('resultDesc').textContent = curSpec.notice + ' 混合值 ' + (curSpec.mixed?.length || 0) +
    ' 项；未勾选的候选值不会进入审查规则。';
  updatePaddingControls();
  $('addRuleBtn').onclick = () => {
    try {
      syncRules();
      const id = $('addRuleId').value, meta = byRuleId(id);
      const scope = id.startsWith('font.') || id.startsWith('paragraph.') ?
        {part:'body',role:$('addRuleRole').value} :
        id.startsWith('page_number.') ? {part:'footer-all'} : {};
      if (candidates.some(r => r.id===id && JSON.stringify(r.scope)===JSON.stringify(scope)))
        throw new Error('这项规则已在列表中');
      const expected = newExpected(meta.kind);
      if (id === 'page_number.even_padding') expected.direction = 'left';
      candidates.push({id,scope,expected,enabled:false,
        severity:'error',required:false});
      buildResult();
    } catch (err) { toast('err',err.message); }
  };
};
buildSummary = function(){
  try { syncRules(); } catch(err){ toast('err',err.message); return; }
  const count = curSpec.candidates.filter(x=>x.enabled).length;
  $('saveSummary').innerHTML = `<div class="mini-row"><span class="mk">已确认的检测项</span>
    <span class="mv">${count} 项候选；保存时编译为可执行规则</span></div>
    <div class="mini-row"><span class="mk">样本</span><span class="mv">${esc(templateFile?.name || '')}</span></div>`;
  if (!$('tplName').value.trim()) $('tplName').value = templateFile?.name.replace(/\.docx$/i,'') || '';
};
saveTemplate = async function(){
  try {
    syncRules();
    const payload = {name:$('tplName').value.trim(), description:$('tplDesc').value.trim(),
      source:templateFile?.name || '', rules:curSpec.candidates};
    if (!payload.name) throw new Error('请填写模板名称');
    const checked = await apiRequest('/api/templates/validate', {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    await apiRequest('/api/templates', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({...payload,rules:checked.normalized_rules})});
    await loadTemplates(); showView('list'); curSpec=null;
    toast('ok','模板已保存，生效规则 '+checked.active_rule_count+' 条');
  } catch(err) { toast('err',err.message); }
};
showRevFileBar = function(name,size){
  const bar=$('revFileBar'); bar.hidden=false;
  bar.innerHTML=`<div class="fb-main"><div class="fb-name">${esc(name)}</div>
    <div class="fb-meta">${Math.round(size/1024)} KB · 已选择，审查时上传至本地服务</div></div>
    <button class="fb-x" type="button" onclick="clearRevFile()">移除</button>`;
};
clearRevFile = function(){ reviewFile=null; reviewText=''; hideRevFileBar(); $('revFile').value=''; };
readRevFile = async function(file){
  if (!/\.docx$/i.test(file.name)) { toast('err','当前只支持 .docx'); return; }
  reviewFile=file; reviewReport=null; showRevFileBar(file.name,file.size);
};
runReview = async function(){
  if (!reviewFile || !reviewTplId) { toast('err','请选择 DOCX 和标准模板'); return; }
  const form=new FormData(); form.append('template_id',reviewTplId); form.append('file',reviewFile);
  $('revResult').innerHTML='<div class="rv-hint">正在执行真实 DOCX 格式与错字检查……</div>';
  try { reviewReport=await apiRequest('/api/reviews',{method:'POST',body:form});
    renderReview(); toast('ok','审查完成');
  } catch(err){ $('revResult').innerHTML=''; toast('err',err.message); }
};
reviewJump = function(id){
  const marker = document.querySelector('[data-annotation="'+id+'"]');
  if (marker) {
    marker.scrollIntoView({behavior:'smooth',block:'center'});
    marker.focus({preventScroll:true});
  } else {
    toast('info','此问题未能可靠映射到页面坐标，请按逻辑位置查看');
  }
};
renderReview = function(){
  const r=reviewReport; if (!r) return;
  const f=r.format, t=r.typo, preview=r.preview || {};
  const fmt=f.findings || [], typo=t.findings || [];
  const annotations=preview.annotations || [];
  const byId=id=>annotations.find(x=>x.id===id);
  const item=(id,label,loc,msg,detail)=>{
    const a=byId(id), mapped=a && a.rects.length;
    return '<div class="fmt-row review-finding"><label>'+esc(label)+'</label>'+
      '<span>'+esc(loc)+' · '+esc(msg)+'</span><small>'+esc(detail)+'</small>'+
      (mapped ? '<button class="btn btn-sm" type="button" onclick="reviewJump(\''+id+'\')">跳转第'+a.rects[0].page+'页</button>'
              : '<small class="review-unlocated">页面坐标未定位</small>')+'</div>';
  };
  const pages=preview.status==='ready' ? (preview.pages || []).map(page=>{
    const overlays=annotations.flatMap(a=>(a.rects || []).filter(rect=>rect.page===page.number)
      .map((rect,k)=>{
        const left=100*rect.x/page.width_pt, top=100*rect.y/page.height_pt;
        const width=Math.max(0.35,100*rect.width/page.width_pt);
        const height=Math.max(0.65,100*rect.height/page.height_pt);
        const title=a.kind==='typo' ? '错别字' : '格式问题';
        return '<button type="button" class="review-mark '+a.kind+
          (a.precision==='page'?' page-level':'')+'" data-annotation="'+a.id+
          '" title="'+title+' · '+esc(a.location)+'" aria-label="'+title+' · '+esc(a.location)+
          '" style="left:'+left+'%;top:'+top+'%;width:'+width+'%;height:'+height+
          '%" onclick="reviewJump(\''+a.id+'\')"></button>';
      })).join('');
    return '<div class="review-page-block" id="review-page-'+page.number+'">'+
      '<div class="review-page-title">第 '+page.number+' / '+preview.pages.length+' 页</div>'+
      '<div class="review-page" style="aspect-ratio:'+page.width_pt+'/'+page.height_pt+'">'+
      '<img src="'+page.image_url+'" alt="第'+page.number+'页预览" loading="lazy">'+overlays+'</div></div>';
  }).join('') : '';
  const previewHtml=preview.status==='ready' ?
    '<div class="review-preview-head"><b>逐页预览</b><span>红色：错别字　黄色：格式问题</span>'+
    '<a href="'+preview.pdf_url+'" target="_blank" rel="noopener">打开 PDF</a></div>'+
    '<div class="rv-hint">坐标基于当前 PDF 渲染；缺少字体或 Word 与 LibreOffice 排版差异可能改变页位置。'+
    (preview.unlocated_count ? '另有 '+preview.unlocated_count+' 处未能可靠定位，见问题列表。' : '')+
    '</div><div class="review-pages">'+pages+'</div>' :
    '<div class="rv-hint">逐页预览生成失败：'+esc(preview.reason || '渲染器不可用')+
    '。检查结果仍按段落或节列出。</div>';
  $('revResult').innerHTML='<div class="rv-topbar"><b>格式：'+esc(f.status)+' · '+fmt.length+
    ' 处</b><b>错字：'+esc(t.status)+' · '+typo.length+' 处</b></div>'+
    '<div class="review-layout"><div class="review-findings">'+
    '<div class="fmt-group"><div class="fg-hd"><b>格式问题</b></div><div class="fmt-rows">'+
    (fmt.map((x,i)=>item('format-'+i,x.rule_name,x.location,x.message,
      '期望：'+x.expected+'；实际：'+x.actual)).join('') ||
      '<p style="padding:12px">已检查范围内无格式 Finding</p>')+'</div></div>'+
    '<div class="fmt-group"><div class="fg-hd"><b>错别字</b></div><div class="fmt-rows">'+
    (typo.map((x,i)=>item('typo-'+i,'错别字','第'+x.para_index+'段·第'+(x.sent_start+1)+'字',
      x.original+' → '+x.suggestion,x.reason)).join('') ||
      '<p style="padding:12px">已检查范围内无错字 Finding</p>')+'</div></div>'+
    '<div class="fmt-group"><div class="fg-hd"><b>覆盖与运行状态</b></div><div class="fmt-rows" style="padding:12px">'+
    '检测器：'+esc(t.detector_name)+'；精检：'+esc(t.corrector_name)+'<br>'+
    '格式未检查：'+esc((f.unchecked_parts||[]).join('；')||'无')+'<br>'+
    '错字过滤 '+t.skipped+' 句，失败 '+t.failed_sentences+' 句；未检查：'+
    esc((t.unchecked_parts||[]).join('；')||'无')+'</div></div></div>'+
    '<div class="review-preview-column">'+previewHtml+'</div></div>';
};
fixAndDownload = function(){ toast('info','原 DOCX 定点修复尚未接入'); };
async function loadTemplates(){
  try {
    const [catalog, list] = await Promise.all([apiRequest('/api/catalog'),apiRequest('/api/templates')]);
    ruleCatalog = catalog.items; TEMPLATES = list.templates;
    renderList(); renderStats(); renderRevTpls();
  } catch(err){ TEMPLATES=[]; renderList(); renderStats(); renderRevTpls(); toast('err','本地服务未连接：'+err.message); }
}
loadTemplates();

