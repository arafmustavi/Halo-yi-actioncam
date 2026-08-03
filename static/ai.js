/* ============================================================
   Halo AI — object detection page
   Start a YOLO job, poll progress, render side-by-side pairs
   as each photo finishes.
   ============================================================ */
const $ = (s) => document.querySelector(s);
const post = async (u) => (await fetch(u, { method: "POST" })).json();
const get  = async (u) => (await fetch(u)).json();

/* ---------- dark mode (shared behavior) ---------- */
(function initTheme(){
  const saved = localStorage.getItem("halo-theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.setAttribute("data-theme", saved || (prefersDark ? "dark" : "light"));
})();
$("#themeToggle")?.addEventListener("click", () => {
  const cur = document.documentElement.getAttribute("data-theme");
  const next = cur === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("halo-theme", next);
});

/* ---------- toast ---------- */
let toastTimer;
function toast(msg, kind=""){
  const t=$("#toast"); t.textContent=msg; t.className="toast show "+kind; t.hidden=false;
  clearTimeout(toastTimer); toastTimer=setTimeout(()=>t.classList.remove("show"),2600);
}

let poll=null;
let renderedCount=0;

/* ---------- availability check ---------- */
async function checkAvailable(){
  try{
    const a=await get("/api/ai/available");
    if(!a.ok){
      $("#aiUnavailable").hidden=false;
      $("#aiUnavailableMsg").textContent=a.message||"";
      $("#btnStart").disabled=true;
    }else{
      $("#aiEmpty").hidden=false;
    }
  }catch{ $("#aiEmpty").hidden=false; }
}

/* ---------- start detection ---------- */
$("#btnStart").onclick=async()=>{
  const limit=$("#aiLimit").value;   // "0" == all
  $("#aiEmpty").hidden=true;
  $("#aiResults").innerHTML="";
  renderedCount=0;
  $("#btnStart").disabled=true;

  const q = limit==="0" ? "" : `&limit=${limit}`;
  const r=await post(`/api/ai/start?filter=photo${q}`);
  if(!r.ok){toast(r.error||"Couldn’t start","err");$("#btnStart").disabled=false;return;}

  $("#aiProgress").hidden=false;
  $("#aiBar").style.width="0%";
  $("#aiCount").textContent=`0 / ${r.total}`;
  $("#aiCurrent").textContent="Warming up the model…";
  clearInterval(poll);
  poll=setInterval(pollProgress,800);
};

/* ---------- poll + incremental render ---------- */
async function pollProgress(){
  let p; try{p=await get("/api/ai/progress");}catch{return;}

  if(p.error){
    clearInterval(poll);
    $("#aiProgress").hidden=true;
    $("#aiUnavailable").hidden=false;
    $("#aiUnavailableMsg").textContent=p.error;
    $("#btnStart").disabled=false;
    return;
  }

  const pct=p.total?Math.round(p.done/p.total*100):0;
  $("#aiBar").style.width=pct+"%";
  $("#aiCount").textContent=`${p.done} / ${p.total}`;
  $("#aiCurrent").textContent=p.finished?"Done":(p.current?`Analyzing ${p.current}…`:"");

  // render any new results that arrived since last poll
  for(let i=renderedCount;i<p.results.length;i++) renderPair(p.results[i]);
  renderedCount=p.results.length;

  if(p.finished){
    clearInterval(poll);
    $("#btnStart").disabled=false;
    $("#aiCurrent").textContent="";
    const withObjects=p.results.filter(r=>r.ok&&r.count>0).length;
    toast(`Analyzed ${p.results.length} · objects found in ${withObjects}`, "ok");
  }
}

/* ---------- render one side-by-side pair ---------- */
function renderPair(res){
  const wrap=document.createElement("div");
  wrap.className="pair"+(res.ok?"":" err");

  if(!res.ok){
    wrap.innerHTML=`
      <div class="pair-head"><span class="name">${res.name}</span></div>
      <div class="pair-error">⚠ ${res.error||"Detection failed"}</div>`;
    $("#aiResults").appendChild(wrap);
    return;
  }

  const tags = Object.keys(res.summary||{}).length
    ? Object.entries(res.summary).map(([k,v])=>`<span class="tag">${k} ×${v}</span>`).join("")
    : `<span class="tag none">No objects</span>`;

  wrap.innerHTML=`
    <div class="pair-head">
      <span class="name">${res.name}</span>
      <div class="pair-tags">${tags}</div>
    </div>
    <div class="pair-imgs">
      <figure><figcaption>Original</figcaption><img loading="lazy" src="${res.original}" alt="original"></figure>
      <figure><figcaption>AI Detected</figcaption><img loading="lazy" src="${res.annotated}" alt="annotated"></figure>
    </div>`;
  $("#aiResults").appendChild(wrap);
}

/* ---------- boot ---------- */
checkAvailable();
