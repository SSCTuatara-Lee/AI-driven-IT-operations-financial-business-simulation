'use strict';
let loadPollTimer, selectedLoadId, selectedLoadReport, loadRuns = [], loadRefreshBusy = false;
const loadActive = new Set(['PREPARING','RUNNING','VERIFYING','STOPPING']);
const loadStatuses = {PREPARING:'准备账户',RUNNING:'发压中',VERIFYING:'账务核对中',STOPPING:'等待在途请求结束',STOPPED:'已停止',COMPLETED:'已完成',FAILED:'执行失败',INTERRUPTED:'已中断'};
const loadScenarios = {...names,idempotency:'幂等重放'};
function renderLoadReport(r){
  const active=loadActive.has(r.status), lat=r.latency_ms||{};
  const metric=(title,value,unit,foot)=>'<div class="metric"><div class="metric-label">'+title+'</div><div class="metric-value">'+escapeHTML(value??'—')+'<small>'+unit+'</small></div><div class="metric-foot">'+escapeHTML(foot)+'</div></div>';
  const errors=(r.business_rejections||0)+(r.http_errors||0)+(r.transport_errors||0)+(r.invalid_responses||0);
  let content='<article class="card"><div class="card-heading"><div><h2>'+escapeHTML(loadScenarios[r.scenario])+' · '+r.concurrency+' 并发</h2><p class="code">'+escapeHTML(r.id)+'</p></div><div class="button-row"><span class="tag '+(r.status==='FAILED'||r.status==='INTERRUPTED'?'red':active?'amber':'')+'">'+escapeHTML(loadStatuses[r.status]||r.status)+'</span>'+(active?'<button class="button danger" data-stop-load="'+r.id+'">停止继续发压</button>':'')+'<button class="button secondary" id="export-load-report">导出 JSON</button></div></div>';
  content+='<progress class="load-progress" max="'+r.request_count+'" value="'+(r.completed||0)+'" aria-label="压测完成请求进度"></progress><div class="load-details"><span>完成 '+(r.completed||0)+' / '+r.request_count+'</span><span>在途 '+(r.in_flight||0)+' · 峰值 '+(r.peak_in_flight||0)+'</span><span>请求测量窗口 '+(r.elapsed_seconds??0)+' 秒</span><span>数据库 '+escapeHTML(r.database)+'</span><span>停止原因 '+escapeHTML({user_stop:'主动停止',duration_limit:'达到发压时限'}[r.stop_reason]||'—')+'</span></div>';
  content+='<div class="metrics">'+metric('请求吞吐',r.requests_per_second,'RPS','包含成功、拒绝和重放')+metric('已确认交易吞吐',r.confirmed_transactions_per_second,'TPS','按成功交易编号去重')+metric('P95 响应延迟',lat.p95,'ms','客户端端到端耗时')+metric('非成功请求比例',((r.failure_rate||0)*100).toFixed(2),'%',errors+' 次拒绝或错误')+'</div>';
  content+=table(['成功响应 / 独立交易','幂等重放','业务拒绝','HTTP 错误','网络 / 响应异常','P50 / P99 / 最大（ms）'],[[String(r.success_requests||0)+' / '+(r.unique_succeeded_transactions||0),String(r.replayed_requests||0),String(r.business_rejections||0),String(r.http_errors||0),String((r.transport_errors||0)+(r.invalid_responses||0)),[lat.p50??'—',lat.p99??'—',lat.max??'—'].join(' / ')]]);
  if(r.reconciliation)content+='<div class="notice '+(r.reconciliation.balanced?'':'error')+'">'+(r.reconciliation.balanced?'结束时账务核对通过':'发现账务差异，请进入账务页面核查')+' · '+r.reconciliation.account_count+' 个账户 · '+r.reconciliation.entry_count+' 条分录</div>';
  if(r.warning)content+='<div class="notice error">'+escapeHTML(r.warning)+'</div>';
  if(r.error_samples?.length)content+='<h2 style="margin-top:20px">错误样本（最多 12 条）</h2>'+table(['幂等键 · 可在交易中心查询','错误','追踪日志'],r.error_samples.map(e=>['<span class="code">'+escapeHTML(e.idempotency_key)+'</span>',escapeHTML(e.error),e.trace_id?traceButton(e.trace_id):'未返回 Trace ID']));
  content+='<p class="muted">账户准备与结束对账不计入吞吐量。每次使用独立合成账户，交易和日志保留。停止会等待已发送请求返回或超时；超时不等于未记账。</p></article>';
  $('#loadtest-report').innerHTML=content;
}
async function loadLoadtests(){
  clearTimeout(loadPollTimer);
  if(loadRefreshBusy)return;
  loadRefreshBusy=true;
  try{
    loadRuns=await api('/api/loadtests');
    if(!selectedLoadId&&loadRuns.length)selectedLoadId=loadRuns[0].id;
    selectedLoadReport=loadRuns.find(r=>r.id===selectedLoadId);
    if(selectedLoadId&&!selectedLoadReport)selectedLoadReport=await api('/api/loadtests/'+selectedLoadId);
    if(selectedLoadReport)renderLoadReport(selectedLoadReport);
    $('#loadtest-start').disabled=loadRuns.some(r=>loadActive.has(r.status));
    $('#loadtest-history').innerHTML=table(['开始时间','场景 / 并发','完成请求','RPS / 已确认 TPS','状态','报告'],loadRuns.map(r=>[time(r.created_at),escapeHTML(loadScenarios[r.scenario])+' / '+r.concurrency,String(r.completed||0)+' / '+r.request_count,String(r.requests_per_second??'—')+' / '+(r.confirmed_transactions_per_second??'—'),escapeHTML(loadStatuses[r.status]||r.status),'<button class="button secondary" data-view-load="'+r.id+'">查看</button>']));
  }finally{
    loadRefreshBusy=false;
    if(current==='loadtests'&&loadRuns.some(r=>loadActive.has(r.status)))loadPollTimer=setTimeout(()=>loadLoadtests().catch(showError),1000);
  }
}
$('#loadtest-form').addEventListener('submit',async event=>{
  event.preventDefault();$('#loadtest-start').disabled=true;
  try{
    const data=Object.fromEntries(new FormData(event.currentTarget));
    for(const key of ['concurrency','request_count','amount_cents','timeout_seconds','max_duration_seconds'])data[key]=Number(data[key]);
    const r=await post('/api/loadtests',data);selectedLoadId=r.id;selectedLoadReport=r;renderLoadReport(r);await loadLoadtests();toast('压测已启动，切换页面后仍会继续');
  }catch(error){showError(error)}finally{$('#loadtest-start').disabled=loadRuns.some(r=>loadActive.has(r.status))}
});
document.addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button)return;
  try{
    if(button.dataset.viewLoad){selectedLoadId=button.dataset.viewLoad;await loadLoadtests()}
    if(button.dataset.stopLoad){button.disabled=true;await post('/api/loadtests/'+button.dataset.stopLoad+'/stop');await loadLoadtests();toast('已停止继续发压，等待在途请求结束')}
    if(button.id==='export-load-report'&&selectedLoadReport){
      const blob=new Blob([JSON.stringify(selectedLoadReport,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');
      link.href=url;link.download='loadtest-'+selectedLoadReport.id+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }
  }catch(error){button.disabled=false;showError(error)}
});
