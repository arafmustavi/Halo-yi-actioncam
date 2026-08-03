/* ============================================================
   Halo — gallery logic (vanilla JS)
   Pagination · IndexedDB thumb cache · dark mode · download-all
   ============================================================ */
const $  = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

const PAGE_SIZE = 24;
const MAX_CONCURRENT_THUMBS = 3;

const state = {
  filter: "all", page: 0, hasMore: true, loading: false, total: 0,
  loaded: [], recording: false, recTimer: null,
};

const post = async (u) => (await fetch(u, { method: "POST" })).json();
const get  = async (u) => (await fetch(u)).json();

/* ---------- dark mode ---------- */
(function initTheme(){
  const saved = localStorage.getItem("halo-theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const theme = saved || (prefersDark ? "dark" : "light");
  document.documentElement.setAttribute("data-theme", theme);
})();
function toggleTheme(){
  const cur = document.documentElement.getAttribute("data-theme");
  const next = cur === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("halo-theme", next);
}
$("#themeToggle")?.addEventListener("click", toggleTheme);

/* ---------- toast ---------- */
let toastTimer;
function toast(msg, kind = "") {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast show " + kind; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
}
function fmtTime(s){const m=Math.floor(s/60),sec=s%60;return `${m}:${sec.toString().padStart(2,"0")}`;}

/* ---------- IndexedDB thumbnail cache ---------- */
const ThumbCache = (() => {
  const DB="halo-cache", STORE="thumbs", VER=1; let dbp;
  const open=()=> dbp || (dbp=new Promise((res,rej)=>{
    const rq=indexedDB.open(DB,VER);
    rq.onupgradeneeded=()=>rq.result.createObjectStore(STORE);
    rq.onsuccess=()=>res(rq.result); rq.onerror=()=>rej(rq.error);
  }));
  const get=async(k)=>{try{const db=await open();return await new Promise(r=>{
    const t=db.transaction(STORE,"readonly").objectStore(STORE).get(k);
    t.onsuccess=()=>r(t.result||null);t.onerror=()=>r(null);});}catch{return null;}};
  const set=async(k,b)=>{try{const db=await open();await new Promise(r=>{
    const t=db.transaction(STORE,"readwrite").objectStore(STORE).put(b,k);
    t.onsuccess=()=>r();t.onerror=()=>r();});}catch{}};
  return {get,set};
})();

/* ---------- concurrency limiter ---------- */
class Limiter{
  constructor(max){this.max=max;this.active=0;this.q=[];}
  run(task){return new Promise((res,rej)=>{this.q.push({task,res,rej});this._next();});}
  _next(){if(this.active>=this.max||!this.q.length)return;this.active++;
    const {task,res,rej}=this.q.shift();
    task().then(res,rej).finally(()=>{this.active--;this._next();});}
}
const thumbLimiter=new Limiter(MAX_CONCURRENT_THUMBS);

async function hydrateThumb(imgEl,m){
  const cached=await ThumbCache.get(m.name);
  if(cached){imgEl.src=URL.createObjectURL(cached);return;}
  try{
    const blob=await thumbLimiter.run(async()=>{
      const r=await fetch(m.src);
      if(!r.ok||r.status===204)throw new Error("no-thumb");
      return await r.blob();
    });
    ThumbCache.set(m.name,blob);
    imgEl.src=URL.createObjectURL(blob);
  }catch{ imgEl.replaceWith(placeholderTile(m)); }
}
function placeholderTile(m){const d=document.createElement("div");d.className="ph";
  d.textContent=m.type==="video"?"🎬":"🖼";return d;}

/* ---------- status ---------- */
async function refreshStatus(){
  try{
    const s=await get("/api/status");
    setConnected(!!s.connected);
    if(s.battery&&s.battery.level!=null){$("#battery").hidden=false;$("#batteryText").textContent=`${s.battery.level}%`;}
    if(s.recording!==undefined&&s.recording!==state.recording)setRecording(s.recording);
  }catch(_){setConnected(false);}
}
function setConnected(on){$("#statusDot").className="dot "+(on?"on":"off");$("#statusText").textContent=on?"Connected":"Offline";}

/* ---------- gallery / pagination ---------- */
function resetGallery(){state.page=0;state.hasMore=true;state.loading=false;state.total=0;state.loaded=[];
  $("#gallery").innerHTML="";$("#emptyState").hidden=true;}
async function loadNextPage(){
  if(state.loading||!state.hasMore)return;
  state.loading=true;$("#sentinel").hidden=false;
  if(state.page===0)$("#gallery").innerHTML=Array(6).fill('<div class="skeleton"></div>').join("");
  const next=state.page+1;
  let r;
  try{ r=await get(`/api/gallery?page=${next}&page_size=${PAGE_SIZE}&filter=${state.filter}`);}
  catch(e){state.loading=false;$("#sentinel").hidden=true;
    if(state.page===0)showEmpty("Couldn’t reach the camera","Make sure you’re on the YDXJ_ Wi-Fi network.");return;}
  if(state.page===0)$("#gallery").innerHTML="";
  if(!r.ok){state.loading=false;$("#sentinel").hidden=true;
    if(state.page===0)showEmpty("Couldn’t reach the camera",r.error||"Please try again.");return;}
  state.total=r.total;state.hasMore=r.has_more;state.page=next;
  if(!r.media.length&&state.loaded.length===0){
    showEmpty(state.filter==="all"?"No moments yet":`No ${state.filter}s`,
      state.filter==="all"?"Tap the shutter below to capture your first shot.":"Try a different filter.");
  }else{appendCards(r.media);updateSub();}
  state.loading=false;$("#sentinel").hidden=!state.hasMore;
  if(!state.hasMore)$("#loadMoreText").textContent="";
}
function appendCards(media){
  const g=$("#gallery");
  media.forEach((m,i)=>{
    const idx=state.loaded.length;state.loaded.push(m);
    const card=document.createElement("div");card.className="card";
    card.style.animationDelay=`${Math.min(i*35,350)}ms`;
    const badge=m.type==="video"?`<span class="badge">● VIDEO</span><div class="play"><span></span></div>`:"";
    const img=document.createElement("img");img.loading="lazy";img.alt=m.name;
    card.appendChild(img);
    card.insertAdjacentHTML("beforeend",`${badge}<div class="meta">${m.name}</div>`);
    card.onclick=()=>openLightbox(idx);
    g.appendChild(card);
    hydrateThumb(img,m);
  });
}
function updateSub(){$("#gallerySub").textContent=`${state.loaded.length} of ${state.total} shown · cached for instant reloads`;}
function showEmpty(title,msg){$("#gallery").innerHTML="";$("#sentinel").hidden=true;
  const e=$("#emptyState");e.hidden=false;$("#emptyTitle").textContent=title;$("#emptyMsg").textContent=msg;}
const io=new IntersectionObserver((es)=>{if(es.some(e=>e.isIntersecting))loadNextPage();},{rootMargin:"600px 0px"});
io.observe($("#sentinel"));

/* ---------- filters ---------- */
$$(".seg").forEach(btn=>{btn.onclick=()=>{
  if(btn.classList.contains("active"))return;
  $$(".seg").forEach(b=>b.classList.remove("active"));btn.classList.add("active");
  state.filter=btn.dataset.filter;resetGallery();loadNextPage();};});

/* ---------- refresh ---------- */
async function hardRefresh(){
  toast("Refreshing…");
  await get(`/api/gallery?page=1&page_size=${PAGE_SIZE}&filter=${state.filter}&refresh=1`);
  resetGallery();loadNextPage();
}
$("#btnRefresh").onclick=hardRefresh;
$("#emptyRetry").onclick=hardRefresh;
$("#statusBtn").onclick=refreshStatus;

/* ---------- capture / record ---------- */
$("#btnCapture").onclick=async()=>{
  const s=$("#btnCapture");s.classList.add("flash");setTimeout(()=>s.classList.remove("flash"),220);
  toast("Capturing…");
  const r=await post("/api/capture");
  if(r.ok){toast("Photo captured","ok");setTimeout(hardRefresh,900);}else toast(r.error||"Capture failed","err");
};
function setRecording(on){state.recording=on;const btn=$("#btnRecord");btn.classList.toggle("active",on);$("#recTime").hidden=!on;
  if(on){let s=0;$("#recTime").textContent="0:00";clearInterval(state.recTimer);
    state.recTimer=setInterval(()=>{s++;$("#recTime").textContent=fmtTime(s);},1000);}else clearInterval(state.recTimer);}
$("#btnRecord").onclick=async()=>{
  const url=state.recording?"/api/record/stop":"/api/record/start";
  toast(state.recording?"Stopping…":"Recording…");
  const r=await post(url);
  if(r.ok){setRecording(r.recording);if(!r.recording){toast("Recording saved","ok");setTimeout(hardRefresh,1200);}}
  else toast(r.error||"Record failed","err");
};

/* ---------- Download All ---------- */
let dlPoll=null;
$("#btnDownloadAll").onclick=async()=>{
  const r=await post(`/api/download-all/start?filter=${state.filter}`);
  if(!r.ok){toast(r.error||"Couldn’t start download","err");return;}
  openDlSheet(r.total,r.folder);
  clearInterval(dlPoll);
  dlPoll=setInterval(pollDownload,700);
};
function openDlSheet(total,folder){
  $("#dlSheet").hidden=false;$("#dlBar").style.width="0%";
  $("#dlTitle").textContent="Downloading to your PC…";
  $("#dlStatus").textContent=`0 / ${total}`;
  $("#dlFolder").textContent=folder||"";
  $("#dlClose").hidden=true;
}
async function pollDownload(){
  let p; try{p=await get("/api/download-all/progress");}catch{return;}
  const pct=p.total?Math.round(p.done/p.total*100):0;
  $("#dlBar").style.width=pct+"%";
  $("#dlStatus").textContent=`${p.done} / ${p.total}` + (p.current?` · ${p.current}`:"");
  $("#dlFolder").textContent=p.folder||"";
  if(p.finished){
    clearInterval(dlPoll);
    const errs=p.errors?.length?` (${p.errors.length} failed)`:"";
    $("#dlTitle").textContent="Download complete ✓";
    $("#dlStatus").textContent=`Saved ${p.done-(p.errors?.length||0)} of ${p.total}${errs}`;
    $("#dlClose").hidden=false;
    toast("Download complete","ok");
  }
}
$("#dlClose").onclick=()=>{$("#dlSheet").hidden=true;};

/* ---------- lightbox ---------- */
let lbIndex=0;
function openLightbox(index){lbIndex=index;renderLightbox();$("#lightbox").hidden=false;document.body.style.overflow="hidden";}
function renderLightbox(){
  const m=state.loaded[lbIndex];const stage=$("#lbStage");
  stage.innerHTML=m.type==="photo"?`<img src="${m.full}" alt="${m.name}">`:`<video src="${m.full}" controls autoplay playsinline></video>`;
  $("#lbName").textContent=`${m.name}   ·   ${lbIndex+1} / ${state.loaded.length}`;
  $("#lbDownload").href="/api/download?url="+encodeURIComponent(m.url);
  $("#lbDownload").setAttribute("download",m.name);
}
function closeLightbox(){$("#lightbox").hidden=true;$("#lbStage").innerHTML="";document.body.style.overflow="";}
function step(d){lbIndex=(lbIndex+d+state.loaded.length)%state.loaded.length;renderLightbox();}
$("#lbClose").onclick=closeLightbox;$("#lbPrev").onclick=()=>step(-1);$("#lbNext").onclick=()=>step(1);
$("#lightbox").onclick=(e)=>{if(e.target.id==="lightbox")closeLightbox();};
document.addEventListener("keydown",(e)=>{if($("#lightbox").hidden)return;
  if(e.key==="Escape")closeLightbox();if(e.key==="ArrowLeft")step(-1);if(e.key==="ArrowRight")step(1);});

/* ---------- boot ---------- */
refreshStatus();resetGallery();loadNextPage();setInterval(refreshStatus,8000);
