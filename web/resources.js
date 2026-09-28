'use strict';
let resourcePollTimer;
const resourcePercent = value => value == null ? '未设限 / 无数据' : (value*100).toFixed(1)+'%';
const resourceMiB = value => value == null ? '未设限 / 无数据' : (value/1048576).toFixed(1)+' MiB';
async function loadResources(){
  clearTimeout(resourcePollTimer);
  try{
    const result=await api('/api/resources'), c=result.container, alerts=result.alerts;
    const card=(label,value,detail)=>'<div class="metric"><div class="metric-label">'+escapeHTML(label)+'</div><div class="metric-value resource-value">'+escapeHTML(value)+'</div><div class="metric-foot">'+escapeHTML(detail)+'</div></div>';
    $('#resource-metrics').innerHTML=card('CPU 配额使用率',resourcePercent(c.cpu_used_ratio),'上限 '+(c.cpu_limit_cores??'未设置')+' 核 · 包含发压进程')+card('容器内存',resourceMiB(c.memory_bytes),'上限 '+resourceMiB(c.memory_limit_bytes)+' · '+resourcePercent(c.memory_used_ratio))+card('累计 CPU 限流',c.throttled_seconds==null?'—':c.throttled_seconds.toFixed(1)+' s','cgroup 累计值，不是故障持续时间')+card('观测到的 OOM kill',c.oom_kills??'—','容器重建后计数可能重置');
    $('#resource-scope').textContent=result.scope+(c.error?' '+c.error:'')+' 内存包含缓存和临时容量区，与 Docker stats 的工作集口径不同。';
    $('#resource-filesystems').innerHTML=table(['区域','已使用','容量','使用率','说明'],result.filesystems.map(f=>[f.name==='capacity'?'演练临时区':'数据文件系统',resourceMiB(f.used_bytes),resourceMiB(f.total_bytes),resourcePercent(f.used_ratio),escapeHTML(f.description)]));
    $('#capacity-controls').hidden=!result.capacity_drill_enabled;
    $('#capacity-status').textContent=result.capacity_expires_at?'将于 '+time(new Date(result.capacity_expires_at*1000))+' 自动清理':'当前没有容量填充任务';
    $('#resource-alert-status').textContent=alerts.available?'最近同步 '+time(alerts.updated_at):alerts.error;
    $('#resource-alert-status').className=alerts.available?'tag':'tag amber';
    const states={inactive:'正常',pending:'等待持续时间',firing:'已触发'};
    $('#resource-alerts').innerHTML=alerts.rules.length?table(['规则','当前状态','触发条件','持续要求'],alerts.rules.map(r=>[escapeHTML(r.name),'<span class="tag '+(!alerts.available?'gray':r.health!=='ok'?'red':r.state==='firing'?'red':r.state==='pending'?'amber':'')+'">'+(!alerts.available?'过期结果':r.health!=='ok'?'规则计算异常':escapeHTML(states[r.state]||r.state))+'</span>',escapeHTML(r.summary),r.duration_seconds+' 秒'])):'<div class="empty">暂未获取告警规则。请启动独立资源演练环境及 Prometheus。</div>';
  } finally {
    if(current==='resources')resourcePollTimer=setTimeout(()=>loadResources().catch(showError),5000);
  }
}
formHandler('#capacity-form',async data=>{
  const result=await post('/api/resources/capacity',{percent:Number(data.get('percent')),duration_seconds:Number(data.get('duration_seconds'))});
  toast(result.warning);await loadResources();
});
$('#clear-capacity').addEventListener('click',async()=>{
  try{await api('/api/resources/capacity',{method:'DELETE'});await loadResources();toast('临时容量区已清理，告警将在下次评估后恢复')}catch(error){showError(error)}
});
