/* Halo — frontend logic (vanilla JS) */
const $  = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const state = { media: [], filter: "all", recording: false, recTimer: null };
const post = async (u) => (await fetch(u, { method: "POST" })).json();
const get  = async (u) => (await fetch(u)).json();

let toastTimer;
function toast(msg, kind = "") {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast show " + kind; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
}
function fmtTime(s){const m=Math.floor(s/60),sec=s%60;return `${m}:${sec.toString().padStart(2,"0")}`;}

async function refreshStatus() {
  try {
    const s = await get("/api/status");
    setConnected(!!s.connected);
    if (s.battery && s.battery.level != null){$("#battery").hidden=false;$("#batteryText").textContent=`${s.battery.level}%`;}
    if (s.recording!==undefined && s.recording!==state.recording) setRecording(s.recording);
  } catch(_){ setConnected(false); }
}
function setConnected(on){
  $("#statusDot").className="dot "+(on?"on":"off");
  $("#statusText").textContent=on?"Connected":"Offline";
}

async function loadGallery() {
  const g=$("#gallery");
  g.innerHTML=Array(6).fill('<div class="skeleton"></div>').join("");
  $("#emptyState").hidden=true; g.hidden=false;
  const r=await get("/api/gallery");
  if(!r.ok){showEmpty("Couldn’t reach the camera", r.error||"Make sure you’re on the YDXJ_ Wi-Fi network.");return;}
  state.media=r.media||[]; renderGallery();
  if(state.media.length) toast(`${r.count} moment${r.count===1?"":"s"} loaded`, "ok");
}
function renderGallery() {
  const g=$("#gallery");
  const items=state.media.filter(m=>state.filter==="all"||m.type===state.filter);
  if(!items.length){
    if(!state.media.length) showEmpty("No moments yet","Tap the shutter below to capture your first shot.");
    else showEmpty(`No ${state.filter}s`,"Try a different filter or capture something new.");
    return;
  }
  $("#emptyState").hidden=true; g.hidden=false; g.innerHTML="";
  items.forEach((m,i)=>{
    const card=document.createElement("div");
    card.className="card"; card.style.animationDelay=`${Math.min(i*40,400)}ms`;
    const badge=m.type==="video"?`<span class="badge">● VIDEO</span><div class="play"><span></span></div>`:"";
    const preview=m.type==="photo"
      ?`<img loading="lazy" src="${m.src}" alt="${m.name}">`
      :`<video muted preload="metadata" src="${m.src}#t=0.5"></video>`;
    card.innerHTML=`${preview}${badge}<div class="meta">${m.name}</div>`;
    card.onclick=()=>openLightbox(items.indexOf(m),items);
    g.appendChild(card);
  });
}
function showEmpty(title,msg){
  $("#gallery").hidden=true;
  const e=$("#emptyState"); e.hidden=false;
  $("#emptyTitle").textContent=title; $("#emptyMsg").textContent=msg;
}

$$(".seg").forEach(btn=>{
  btn.onclick=()=>{
    $$(".seg").forEach(b=>b.classList.remove("active")); btn.classList.add("active");
    state.filter=btn.dataset.filter; renderGallery();
  };
});

$("#btnCapture").onclick=async()=>{
  const s=$("#btnCapture"); s.classList.add("flash"); setTimeout(()=>s.classList.remove("flash"),220);
  toast("Capturing…");
  const r=await post("/api/capture");
  if(r.ok){toast("Photo captured","ok");setTimeout(loadGallery,900);}
  else toast(r.error||"Capture failed","err");
};

function setRecording(on){
  state.recording=on;
  const btn=$("#btnRecord"); btn.classList.toggle("active",on); $("#recTime").hidden=!on;
  if(on){let secs=0;$("#recTime").textContent="0:00";clearInterval(state.recTimer);
    state.recTimer=setInterval(()=>{secs++;$("#recTime").textContent=fmtTime(secs);},1000);}
  else clearInterval(state.recTimer);
}
$("#btnRecord").onclick=async()=>{
  const url=state.recording?"/api/record/stop":"/api/record/start";
  toast(state.recording?"Stopping…":"Recording…");
  const r=await post(url);
  if(r.ok){setRecording(r.recording);if(!r.recording){toast("Recording saved","ok");setTimeout(loadGallery,1200);}}
  else toast(r.error||"Record failed","err");
};
$("#btnRefresh").onclick=loadGallery;
$("#emptyRetry").onclick=loadGallery;
$("#statusBtn").onclick=refreshStatus;

let lbItems=[],lbIndex=0;
function openLightbox(index,items){lbItems=items;lbIndex=index;renderLightbox();$("#lightbox").hidden=false;document.body.style.overflow="hidden";}
function renderLightbox(){
  const m=lbItems[lbIndex]; const stage=$("#lbStage");
  stage.innerHTML=m.type==="photo"?`<img src="${m.src}" alt="${m.name}">`:`<video src="${m.src}" controls autoplay playsinline></video>`;
  $("#lbName").textContent=`${m.name}   ·   ${lbIndex+1} / ${lbItems.length}`;
  $("#lbDownload").href="/api/download?url="+encodeURIComponent(m.url);
  $("#lbDownload").setAttribute("download",m.name);
}
function closeLightbox(){$("#lightbox").hidden=true;$("#lbStage").innerHTML="";document.body.style.overflow="";}
function step(dir){lbIndex=(lbIndex+dir+lbItems.length)%lbItems.length;renderLightbox();}
$("#lbClose").onclick=closeLightbox;
$("#lbPrev").onclick=()=>step(-1);
$("#lbNext").onclick=()=>step(1);
$("#lightbox").onclick=(e)=>{if(e.target.id==="lightbox")closeLightbox();};
document.addEventListener("keydown",(e)=>{
  if($("#lightbox").hidden)return;
  if(e.key==="Escape")closeLightbox();
  if(e.key==="ArrowLeft")step(-1);
  if(e.key==="ArrowRight")step(1);
});

refreshStatus(); loadGallery(); setInterval(refreshStatus,8000);
