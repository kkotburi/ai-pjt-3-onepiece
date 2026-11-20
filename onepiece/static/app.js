const el = id => document.getElementById(id);
const sid = localStorage.plannerSession || (localStorage.plannerSession = crypto.randomUUID());
const q = "?session_id=" + sid;
let slot;
let openPlanId;
const koreanTime = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short"
});
function planText(plan) {
  const created = new Date(plan.created.replace(" ", "T") + "Z");
  return plan.episode+"화 · "+koreanTime.format(new Date(plan.start))+" ~ "+
    koreanTime.format(new Date(plan.end))+" · 생성 "+koreanTime.format(created);
}
async function showPlan(id) {
  openPlanId = id;
  const plan = await api("plans/"+id+q);
  if(openPlanId === id) el("detail").textContent = planText(plan);
}
async function api(path, method="GET", body) {
  const res = await fetch("/api/" + path, {method, headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const data = await res.json();
  if (!res.ok) throw Error(typeof data.detail === "string" ? data.detail : "입력값을 확인하세요.");
  return data;
}
function action(fn) {
  return async event => {
    try {await fn(event);} catch(error) {el("answer").textContent = error.message;}
  };
}
function button(label, fn) {
  const b=document.createElement("button"); b.textContent=label; b.onclick=action(fn); return b;
}
async function refresh() {
  const plans = await api("plans"+q);
  el("plans").replaceChildren(...plans.map(p=>{
    const row=document.createElement("p");
    row.append(planText(p),
      button("상세",()=>showPlan(p.id)),button("계획 수정",async()=>{
        const episodeText=prompt("회차 번호",p.episode);
        if(episodeText===null) return;
        const episode=Number(episodeText.trim());
        if(!/^\d+$/.test(episodeText.trim()) || !Number.isSafeInteger(episode) || episode<=0) {
          throw Error("회차 번호는 양의 정수로 입력하세요.");
        }
        const start=prompt("시작 시각 (ISO 형식)",p.start);
        if(!start) return;
        const end=prompt("종료 시각 (ISO 형식)",p.end);
        if(!end) return;
        const result=await api("plans/"+p.id+q,"PUT",{episode,start,end});
        statusSaved(result);
        await refresh();
        if(openPlanId === p.id) await showPlan(p.id);
      }),button("삭제",async()=>{
        await api("plans/"+p.id+q,"DELETE");
        if(openPlanId === p.id) {
          openPlanId = undefined;
          el("detail").textContent="";
        }
        await refresh();
      }));
    return row;
  }));
}
function statusSaved(result) {
  el("answer").textContent=result.overlaps.length ? "저장됨 · 시간이 겹치는 계획: "+result.overlaps.join(", ") : "계획을 저장했습니다.";
}
let running=false;
async function runChat(endpoint,message,character,character_id){
  if(running) return;
  running=true;
  const submit=el("chat").querySelector("button");
  submit.disabled=true; el("confirm").hidden=true; el("sources").replaceChildren(); el("trace").textContent="";
  el("answer").textContent="요청을 처리하고 있습니다…";
  const run_id=crypto.randomUUID();
  let after=0, polling=false, done=false;
  const timer=setInterval(async()=>{
    if(polling) return;
    polling=true;
    try{
      const events=await api("logs/"+sid+"?run_id="+run_id+"&after="+after);
      if(done) return;
      for(const e of events){
        const data=JSON.parse(e.payload);
        el("trace").textContent+=JSON.stringify({kind:e.kind,...data})+"\n";
        el("answer").textContent="처리 중 · "+(data.reason || data.tool || data.stage || e.kind);
        after=e.id;
      }
    }catch{}finally{polling=false;}
  },350);
  try {
    const data=await api(endpoint,"POST",{session_id:sid,run_id,message,character,character_id});
    el("answer").textContent=data.answer; slot=data.slot; el("confirm").hidden=!slot;
    el("trace").textContent=data.trace.map(t=>JSON.stringify(t)).join("\n");
    for(const url of data.sources){const a=document.createElement("a");a.href=url;a.textContent=new URL(url).hostname;el("sources").append(a," ");}
  } finally {done=true; clearInterval(timer); submit.disabled=false; running=false;}
}
el("chat").onsubmit=action(async e=>{
  e.preventDefault(); await runChat("chat",el("message").value);
});
el("confirm").onclick=action(async()=>{el("confirm").disabled=true;try {statusSaved(await api("plans"+q,"POST",slot));el("confirm").hidden=true;await refresh();}finally{el("confirm").disabled=false;}});
el("logs").onclick=action(async()=>{const rows=await api("logs"+q);
  el("history").replaceChildren(...rows.map(r=>button("현재 세션 · "+r.events+"개 이벤트 · 상세",async()=>{
    el("history").textContent=JSON.stringify(await api("logs/"+r.sid),null,2);
  })));
  if(!rows.length) el("history").textContent="저장된 기록이 없습니다.";});
el("clear").onclick=action(async()=>{if(confirm("현재 세션의 기록을 삭제할까요?")){await api("logs/"+sid,"DELETE");el("history").textContent="";}});
action(refresh)();

el("search").onsubmit=action(async e=>{
  e.preventDefault();
  const box=el("matches");
  box.textContent="캐릭터를 검색하고 있습니다…";
  const result=await api("characters?name="+encodeURIComponent(el("name").value.trim()));
  if(!result.ok){
    box.textContent=({NO_RESULTS:"일치하는 캐릭터가 없습니다.",ENGLISH_NAME_REQUIRED:"다른 한글 표기나 이름의 일부로 검색해 주세요."})[result.error.code] || "검색에 실패했습니다. 잠시 후 다시 시도해 주세요.";
    return;
  }
  box.replaceChildren(...result.data.map(c=>button(c.korean_name ? c.korean_name+" ("+c.name+")" : c.name,()=>runChat("character-info",c.name,c.name,c.id))));
});

el("name").addEventListener("focus", async function loadNames(){
  try {
    const rows=await api("characters/names");
    el("character-names").replaceChildren(...rows.map(row=>{
      const option=document.createElement("option");
      option.value=row.korean_name;
      option.label=row.name;
      return option;
    }));
    el("name").removeEventListener("focus",loadNames);
  } catch {
    // 목록을 불러오지 못해도 입력한 이름으로 검색할 수 있다.
  }
});
