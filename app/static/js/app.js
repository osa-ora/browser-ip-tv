(() => {
  const $ = (id) => document.getElementById(id);
  const state = {passwordConfigured:false, authenticated:false, profiles:[], activeProfile:null, settings:{theme:"dark",home_order:["continue","movies","series","live"],show_expiry:true}, mediaType:"live", categories:[], items:[], catalogItems:[], catalogByType:{live:[],movies:[],series:[]}, favoritesByType:{live:[],movies:[],series:[]}, categoryId:null, currentItem:null, currentStreamUrl:null, currentNavigation:null, recent:[], lastRecentSave:0, resumeOnMetadata:null, movieFallbackTried:false, expiryRefreshAttempted:new Set()};
  const sectionMeta = {
    continue:{title:"Continue Watching", subtitle:"Pick up where you left off", icon:"◷"},
    movies:{title:"Movies", subtitle:"Feature films and favorites", icon:"▣"},
    series:{title:"Series", subtitle:"Your next episode awaits", icon:"▤"},
    live:{title:"Live TV", subtitle:"Watch what's on now", icon:"◉"}
  };
  const screens = ["loginScreen","setupScreen","homeScreen","browserScreen","playerScreen"];
  async function api(path, options={}) {
    const headers = {...(options.headers||{})};
    if (options.body && typeof options.body !== "string") {headers["Content-Type"]="application/json"; options.body=JSON.stringify(options.body);}
    const response = await fetch(path,{credentials:"same-origin",...options,headers});
    let data={}; try {data=await response.json()} catch {}
    if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
    return data;
  }
  function showScreen(id) {if(id!=="playerScreen"&&!$("playerScreen").classList.contains("hidden"))stopPlayback();screens.forEach(s=>$(s).classList.toggle("hidden",s!==id));}
  function toast(message, error=false) {const el=$("toast");el.textContent=message;el.classList.toggle("hidden",false);el.classList.toggle("error-toast",error);setTimeout(()=>el.classList.add("hidden"),3500);}
  function activeProfile(){return state.profiles.find(p=>p.id===state.activeProfile)||state.profiles[0]||null;}
  function setTheme(theme){const actual=theme==="system"?(matchMedia("(prefers-color-scheme: light)").matches?"light":"dark"):theme;document.documentElement.dataset.theme=actual;}
  function escapeHtml(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
  function getName(item){return item.name||item.title||item.stream_name||item.series_name||"Untitled";}
  function getIcon(type){return type==="live"?"◉":type==="movies"?"▣":"▤";}
  function poster(item,type){const img=item.stream_icon||item.cover||item.movie_image||item.icon;return `<div class="poster">${img?`<img loading="lazy" src="${escapeHtml(img)}" alt="" onerror="this.remove()">`:`<span class="poster-icon">${getIcon(type)}</span>`}<span class="poster-tag">${type==="live"?"LIVE":type==="movies"?"MOVIE":"SERIES"}</span></div>`;}
  function itemKey(item){return String(item.stream_url||item.stream_id||item.series_id||item.id||getName(item));}
  function isEpisode(item){return !!(item?._isEpisode || item?._parentSeries || item?._season != null || item?.episode_num != null);}
  function isFavorite(item,type){if(type==="series"&&isEpisode(item))return false;return (state.favoritesByType[type]||[]).some(x=>!isEpisode(x)&&itemKey(x)===itemKey(item));}
  function card(item,type,clickable=true){const id=item.stream_id??item.series_id??item.id??item.stream_url??getName(item);const fav=isFavorite(item,type);return `<article class="media-card" tabindex="0" role="button" data-item-id="${escapeHtml(id)}" data-type="${type}">${poster(item,type)}${type==="series"&&isEpisode(item)?"":`<button class="favorite-toggle ${fav?"is-favorite":""}" title="${fav?"Remove from favorites":"Add to favorites"}" aria-label="${fav?"Remove from favorites":"Add to favorites"}" data-favorite-id="${escapeHtml(id)}" data-favorite-type="${type}">⋮</button>`}<div class="card-info"><div class="card-title">${escapeHtml(getName(item))}</div><div class="card-subtitle">${escapeHtml(item.category_name||item.genre||item.year|| (type==="live"?"Live channel":""))}</div></div></article>`;}
  async function refreshState(){
    const data=await api("/api/state");
    state.passwordConfigured=data.password_configured;state.authenticated=data.authenticated;state.profiles=data.profiles||[];state.activeProfile=data.active_profile;state.settings={...state.settings,...(data.settings||{})};setTheme(state.settings.theme);
    renderProfileStatus();
    $("switchProfileTop").disabled=state.profiles.length<2 || (state.passwordConfigured&&!state.authenticated);
    $("switchProfileTop").title=state.profiles.length<2?"Add another IPTV profile to switch servers":"Switch to the next IPTV server";
    $("addProfileTop").classList.toggle("hidden",state.passwordConfigured&&!state.authenticated);
    $("settingsBtn").classList.toggle("hidden",state.passwordConfigured&&!state.authenticated);
    if(state.passwordConfigured&&!state.authenticated){showScreen("loginScreen");return;}
    if(!state.profiles.length){showScreen("setupScreen");return;}
    await refreshExpiryIfNeeded();renderProfileStatus();
    try{await loadRecent();}catch{}
    showScreen("homeScreen");await renderHome();
  }
  function renderProfileStatus(){
    const profile=activeProfile();
    const expiry=state.settings.show_expiry&&profile?.expiry?` (${profile.expiry})`:"";
    $("profileStatus").textContent=profile?`● ${profile.nickname}${expiry}`:"";
  }
  async function refreshExpiryIfNeeded(){
    const profile=activeProfile();
    if(!state.settings.show_expiry||!profile||profile.method!=="xtream"||profile.expiry||state.expiryRefreshAttempted.has(profile.id))return;
    state.expiryRefreshAttempted.add(profile.id);
    try{
      const data=await api("/api/profile/refresh",{method:"POST"});
      if(data.profile){state.profiles=state.profiles.map(p=>p.id===data.profile.id?{...p,...data.profile}:p);}
    }catch{}
  }
  async function loadProfiles(){const data=await api("/api/profiles");state.profiles=data.profiles||[];state.activeProfile=data.active_profile;}
  async function renderHome(){
    const host=$("homeSections");host.innerHTML="";
    for(const key of state.settings.home_order||["continue","movies","series","live"]){
      const section=document.createElement("section");section.className="home-section draggable";section.draggable=true;section.dataset.section=key;
      section.innerHTML=`<div class="section-head"><div><h2 style="display:inline">${sectionMeta[key].title}</h2><span class="section-sub">${sectionMeta[key].subtitle}</span></div><span class="section-actions">⠿ Drag to reorder</span></div><div class="media-row" id="row-${key}"><div class="empty-state">Loading…</div></div>`;
      host.appendChild(section);
      if(key==="continue"){renderContinue($(`row-${key}`));continue;}
      try{
        const [data,favData]=await Promise.all([api(`/api/catalog/${key}?profile_id=${encodeURIComponent(state.activeProfile)}`),api(`/api/favorites/${key}?profile_id=${encodeURIComponent(state.activeProfile)}`)]);
        state.favoritesByType[key]=(favData.items||[]).filter(i=>key!=="series"||!isEpisode(i));state.catalogByType[key]=data.items||[];
        const homeItems=["live","movies","series"].includes(key)&&state.favoritesByType[key].length?state.favoritesByType[key]:data.items||[];
        const items=homeItems.slice(0,5);
        $(`row-${key}`).innerHTML=items.length?items.map(i=>card(i,key)).join(""):`<div class="empty-state">No ${key==="live"?"channels":key} returned by this provider.</div>`;
      }catch(e){$(`row-${key}`).innerHTML=`<div class="empty-state">${escapeHtml(e.message)}</div>`;}
    }
    wireDragAndDrop();
  }
  async function loadRecent(){
    const data=await api(`/api/recent?profile_id=${encodeURIComponent(state.activeProfile)}`);
    state.recent=(data.items||[]).map(x=>({...x,profileId:x.profileId||state.activeProfile,navigation:x.navigation||x.item?._navigation||null}));
  }
  function renderContinue(host){
    const recent=state.recent.filter(x=>x.profileId===state.activeProfile).slice(0,10);
    host.innerHTML=recent.length?recent.map(x=>card(x.item,x.type)).join(""):`<div class="empty-state">Your Continue Watching list will appear here after you start watching.</div>`;
  }
  function persistRecent(position,duration){
    const item=state.currentItem,type=state.playerType,profileId=state.activeProfile;
    if(!item||!profileId||type==="live")return;
    const key=itemKey(item);const navigation=state.currentNavigation||item._navigation||{type,categoryId:item.category_id==null?null:String(item.category_id)};const record={profileId,type,item,navigation,position:Number.isFinite(position)?position:0,duration:Number.isFinite(duration)?duration:0,updated_at:Math.floor(Date.now()/1000)};
    state.recent=[record,...state.recent.filter(x=>!(x.profileId===profileId&&x.type===type&&itemKey(x.item)===key))].slice(0,50);
    return api("/api/recent",{method:"POST",body:{profile_id:profileId,media_type:type,item,navigation,position:record.position,duration:record.duration}}).catch(()=>{});
  }
  function wireDragAndDrop(){
    let dragging=null;
    document.querySelectorAll(".home-section").forEach(el=>{
      el.addEventListener("dragstart",()=>{dragging=el;el.classList.add("dragging");});
      el.addEventListener("dragend",async()=>{el.classList.remove("dragging");document.querySelectorAll(".home-section").forEach(x=>x.classList.remove("drop-target"));state.settings.home_order=[...$("homeSections").children].map(x=>x.dataset.section);try{await saveSettings(false);}catch{}});
      el.addEventListener("dragover",e=>{e.preventDefault();if(dragging&&dragging!==el){el.classList.add("drop-target");const rect=el.getBoundingClientRect();if(e.clientY>rect.top+rect.height/2)el.after(dragging);else el.before(dragging);}});
      el.addEventListener("dragleave",()=>el.classList.remove("drop-target"));
      el.addEventListener("drop",e=>{e.preventDefault();el.classList.remove("drop-target");});
    });
  }
  async function openBrowser(type,categoryId=null){
    state.mediaType=type;state.categoryId=categoryId;
    // Keep the selected browser category as the authoritative navigation context.
    state.currentNavigation={type,categoryId};showScreen("browserScreen");$("browserTitle").textContent=sectionMeta[type].title;$("browserSubtitle").textContent=`From ${activeProfile()?.nickname||"your IPTV profile"}`;$("searchInput").value="";
    $("categoryTree").innerHTML='<p class="muted small">Loading categories…</p>';$("mediaGrid").innerHTML='<div class="empty-state">Loading library…</div>';
    try{
      const [data,favData]=await Promise.all([api(`/api/catalog/${type}?profile_id=${encodeURIComponent(state.activeProfile)}`),api(`/api/favorites/${type}?profile_id=${encodeURIComponent(state.activeProfile)}`)]);
      state.categories=data.categories||[];state.catalogItems=data.items||[];state.catalogByType[type]=data.items||[];state.favoritesByType[type]=(favData.items||[]).filter(i=>type!=="series"||!isEpisode(i));
      state.items=categoryId==="__favorites__"?state.favoritesByType[type].slice():categoryId===null?state.catalogItems.slice():state.catalogItems.filter(i=>String(i.category_id??"")===String(categoryId));
      renderTree();renderItems();
    }catch(e){$("categoryTree").innerHTML="";$("mediaGrid").innerHTML=`<div class="empty-state">${escapeHtml(e.message)}</div>`;}
  }
  function renderTree(){
    const favorites=state.favoritesByType[state.mediaType]||[];
    const fav=`<button class="tree-item favorite-tree ${state.categoryId==="__favorites__"?"active":""}" data-category="__favorites__"><span class="tree-fav-star">★</span> Favorites <span class="tree-count">${favorites.length}</span></button>`;
    const all=`<button class="tree-item ${state.categoryId===null?"active":""}" data-category="">All ${sectionMeta[state.mediaType].title}<span class="tree-count">${state.catalogItems.length}</span></button>`;
    const cats=state.categories.map(c=>{const id=c.category_id??c.id??c.category_name;return `<button class="tree-item ${String(state.categoryId)===String(id)?"active":""}" data-category="${escapeHtml(id)}">${escapeHtml(c.category_name||c.name||"Category")}<span class="tree-count"></span></button>`}).join("");
    $("categoryTree").innerHTML=fav+all+cats;
  }
  function renderItems(){
    const query=$("searchInput").value.trim().toLowerCase();let items=state.items.filter(i=>getName(i).toLowerCase().includes(query));
    if($("sortSelect").value==="name")items.sort((a,b)=>getName(a).localeCompare(getName(b)));
    $("itemCount").textContent=`${items.length.toLocaleString()} item${items.length===1?"":"s"}`;
    $("mediaGrid").innerHTML=items.length?items.map(i=>card(i,state.mediaType)).join(""):'<div class="empty-state">No items found. Try another category or search term.</div>';
  }
  async function playItem(item,type){
    // Preserve the originating category/tree location for Back and Continue Watching.
    if(item?._navigation) state.currentNavigation={...item._navigation};
    else if(!state.currentNavigation || state.currentNavigation.type!==type) {
      const categoryId=item?.category_id!=null?String(item.category_id):(state.mediaType===type?state.categoryId:null);
      state.currentNavigation={type,categoryId:categoryId==="__favorites__"?"__favorites__":categoryId};
    }
    if(item?._isEpisode && item?._parentSeries) {
      state.currentNavigation={...(item._navigation||state.currentNavigation),type:"series"};
    }
    // Selecting a series opens every episode returned by Xtream, not just its first episode.
    if(type==="series" && !item._isEpisode && activeProfile()?.method==="xtream"){
      try{
        const seriesId=item.series_id??item.stream_id??item.id;
        const info=await api(`/api/series/${encodeURIComponent(seriesId)}?profile_id=${encodeURIComponent(state.activeProfile)}`);
        const episodes=info.episodes||{};
        const flattened=Object.entries(episodes).flatMap(([season,entries])=>(entries||[]).map(ep=>({
          ...ep, name:ep.title||ep.name||`Episode ${ep.episode_num??""}`.trim(),
          _isEpisode:true, _season:String(season), _parentSeries:item,
          _seriesId:String(seriesId), _navigation:{...(state.currentNavigation||{type:"series",categoryId:item.category_id??null}),type:"series"}
        })));
        if(!flattened.length){toast("No playable episodes were returned for this series.",true);return;}
        state.playerItems=flattened;
        state.playerType="series";
        await playItem(flattened[0],"series");
        return;
      }catch(e){toast(e.message,true);return;}
    }
    const id=item.stream_id??item.series_id??item.id;
    let streamUrl=item.stream_url;
    if(!streamUrl){try{const ext=item.container_extension||item.extension||(type==="live"?"m3u8":"mp4");const d=await api(`/api/stream-url/${type}/${encodeURIComponent(id)}?profile_id=${encodeURIComponent(state.activeProfile)}&extension=${encodeURIComponent(ext)}`);streamUrl=d.url;}catch(e){toast(e.message,true);return;}}
    // Stop any previous channel/episode before attaching the next stream.
    stopPlayback();
    state.currentItem=item;state.currentStreamUrl=streamUrl;state.playerType=type;state.movieFallbackTried=false;state.resumeOnMetadata=null;
    if(!item._isEpisode){
      const catalog=state.catalogByType[type]||state.catalogItems||[];
      const nav=state.currentNavigation?.type===type?state.currentNavigation:{type,categoryId:state.mediaType===type?state.categoryId:(item.category_id==null?null:String(item.category_id))};
      let playable;
      if(nav.categoryId==="__favorites__") playable=(state.favoritesByType[type]||[]).slice();
      else if(nav.categoryId!=null && nav.categoryId!=="") playable=catalog.filter(x=>String(x.category_id??"")===String(nav.categoryId));
      else if(item.category_id!=null && state.mediaType!==type) playable=catalog.filter(x=>String(x.category_id??"")===String(item.category_id));
      else playable=catalog.slice();
      playable=playable.filter(x=>String(x.stream_id??x.series_id??x.id??x.stream_url??getName(x))!=="");
      state.playerItems=playable.some(x=>String(x.stream_id??x.series_id??x.id??x.stream_url??getName(x))===String(id))?playable:[item];
    }
    showScreen("playerScreen");$("playerTitle").textContent=item._isEpisode?`${item._parentSeries?getName(item._parentSeries)+" · ":""}${getName(item)}`:getName(item);$("playerMeta").textContent=item._isEpisode?`Season ${item._season||"—"} · ${activeProfile()?.nickname||""}`:(activeProfile()?.nickname||"");renderPlayerTree(item);$("playerMessage").classList.add("hidden");
    const video=$("videoPlayer");
    const previous=state.recent.find(x=>x.profileId===state.activeProfile&&x.type===type&&itemKey(x.item)===itemKey(item));
    if(previous&&type!=="live"&&Number(previous.position)>5&&(!previous.duration||Number(previous.position)<Number(previous.duration)-45))state.resumeOnMetadata=Number(previous.position);
    persistRecent(previous?.position||0,previous?.duration||0);
    video._playbackTimer=setTimeout(()=>{if(video.readyState<2)showPlayerError("The stream has not started. The provider may reject this browser, require a different stream format, or block browser playback (CORS). Try another channel or contact the provider.");},15000);
    const isHls=/\.m3u8($|\?)/i.test(streamUrl);
    if(isHls&&video.canPlayType("application/vnd.apple.mpegurl")) {video.src=streamUrl;video.play().catch(()=>{});}
    else if(isHls){
      if(!document.getElementById("hlsScript")){
        const script=document.createElement("script");script.id="hlsScript";script.src="https://cdn.jsdelivr.net/npm/hls.js@1.5.17/dist/hls.min.js";document.head.appendChild(script);
        script.onload=()=>{if(state.currentStreamUrl===streamUrl)attachVideo(streamUrl,true);};script.onerror=()=>showPlayerError("Could not load HLS playback support.");
      }else if(window.Hls)attachVideo(streamUrl,true);
      else document.getElementById("hlsScript").addEventListener("load",()=>{if(state.currentStreamUrl===streamUrl)attachVideo(streamUrl,true);},{once:true});
    }else{video.src=streamUrl;video.play().catch(()=>{});}

  }
  function stopPlayback(){
    const video=$("videoPlayer");
    if(!video)return;
    if(video._playbackTimer){clearTimeout(video._playbackTimer);video._playbackTimer=null;}
    if(video._hls){video._hls.destroy();video._hls=null;}
    video.pause();video.removeAttribute("src");
    try{video.load();}catch{}
    state.currentStreamUrl=null;
  }
  function renderPlayerTree(current){
    const items=state.playerItems||[current];const favorites=state.favoritesByType[state.playerType]||[];
    const favKeys=new Set(favorites.map(itemKey));const ordered=[...items.filter(x=>favKeys.has(itemKey(x))),...items.filter(x=>!favKeys.has(itemKey(x)))];
    $("playerTree").innerHTML=`<div class="panel-title">${state.playerType==="live"?"CHANNELS":state.playerType==="movies"?"MOVIES":"EPISODES"}</div>`+ordered.map(item=>{
      const id=item.stream_id??item.series_id??item.id??item.stream_url??getName(item);const active=String(id)===String(current.stream_id??current.series_id??current.id??current.stream_url??getName(current));const episode=state.playerType==="series"&&isEpisode(item);const fav=isFavorite(item,state.playerType);
      return `<div class="player-tree-row"><button class="tree-item ${active?"active":""}" data-player-item="${escapeHtml(id)}">${fav?"★ ":""}${item._season?`S${escapeHtml(item._season)} · `:""}${escapeHtml(getName(item))}</button>${episode?"":`<button type="button" class="tree-more ${fav?"is-favorite":""}" data-favorite-id="${escapeHtml(id)}" data-favorite-type="${state.playerType}" title="${fav?"Remove from favorites":"Add to favorites"}" aria-label="${fav?"Remove from favorites":"Add to favorites"}">⋮</button>`}</div>`;
    }).join("");
  }
  function attachVideo(url,hls){const video=$("videoPlayer");if(video._playbackTimer)clearTimeout(video._playbackTimer);$("playerMessage").classList.add("hidden");if(hls&&window.Hls&&window.Hls.isSupported()){if(video._hls)video._hls.destroy();video._hls=new window.Hls({enableWorker:true,lowLatencyMode:false});video._hls.on(window.Hls.Events.ERROR,(_event,data)=>{if(data.fatal){showPlayerError(data.type==="networkError"?"The provider did not deliver the stream. Check the URL, credentials, or provider availability.":"The browser could not decode this stream format.");video._hls.destroy();video._hls=null;}});video._hls.loadSource(url);video._hls.attachMedia(video);video.play().catch(()=>{});}else{video.src=url;video.play().catch(()=>{});}}
  async function toggleFavorite(item,type){if(type==="series"&&isEpisode(item)){toast("Favorite the series itself, not an individual episode.",true);return;}try{const d=await api("/api/favorites",{method:"POST",body:{profile_id:state.activeProfile,media_type:type,item}});state.favoritesByType[type]=d.items||[];if(state.categoryId==="__favorites__")state.items=state.favoritesByType[type].slice();renderTree();renderItems();if(!$("homeScreen").classList.contains("hidden"))await renderHome();if(!$("playerScreen").classList.contains("hidden"))renderPlayerTree(state.currentItem);toast(d.favorited?"Added to favorites":"Removed from favorites");}catch(e){toast(e.message,true);}}
  function showPlayerError(message){$("playerMessage").textContent=message;$("playerMessage").classList.remove("hidden");}
  function openProfileModal(profile=null){
    $("profileForm").reset();$("editingProfileId").value=profile?.id||"";$("modalTitle").textContent=profile?"Edit IPTV profile":"Add IPTV profile";$("saveProfileBtn").textContent=profile?"Save changes":"Save profile";
    if(profile){$("profileNickname").value=profile.nickname;$("profileMethod").value=profile.method;$("serverUrl").value=profile.url||"";$("profileUsername").value=profile.username||"";$("profilePassword").value="";}
    $("testResult").textContent="";syncMethodFields();$("modalBackdrop").classList.remove("hidden");$("profileNickname").focus();
  }
  function syncMethodFields(){
    const m=$("profileMethod").value;const xtream=m==="xtream";
    $("usernameLabel").classList.toggle("hidden",!xtream);$("passwordLabel").classList.toggle("hidden",!xtream);
    $("serverUrlLabel").querySelector("span")?.remove();$("serverUrlLabel").firstChild.textContent=xtream?"Server URL":"Playlist URL";
    $("serverUrl").placeholder=xtream?"https://provider.example:8080":"https://provider.example/playlist.m3u";
    $("methodHint").textContent=xtream?"Use the base server URL, without player_api.php. Credentials are stored in the local application configuration.":"Paste a direct M3U/M3U8 playlist URL. M3U is used for Live TV; Movies and Series libraries require Xtream Codes metadata.";
  }
  function closeProfileModal(){$("modalBackdrop").classList.add("hidden");}
  function openSettings(){
    $("themeSelect").value=state.settings.theme||"dark";$("showExpiry").checked=state.settings.show_expiry!==false;$("newAppPassword").value="";$("passwordResult").textContent="";
    renderSettingsProfiles();$("settingsBackdrop").classList.remove("hidden");
  }
  function renderSettingsProfiles(){
    const host=$("settingsProfiles");
    host.innerHTML=state.profiles.length?state.profiles.map(p=>`<div class="profile-row"><div class="profile-name">${escapeHtml(p.nickname)}${p.id===state.activeProfile?" <span style='color:var(--accent)'>(active)</span>":""}<small>${escapeHtml(p.method==="xtream"?"Xtream Codes":"M3U playlist")}${p.expiry?` · Expires ${escapeHtml(p.expiry)}`:""}</small></div><button class="secondary" data-action="switch" data-id="${p.id}">${p.id===state.activeProfile?"Selected":"Use"}</button><button class="secondary" data-action="edit" data-id="${p.id}">Edit</button><button class="secondary" data-action="delete" data-id="${p.id}">Remove</button></div>`).join(""):'<p class="muted small">No profiles configured.</p>';
  }
  async function saveSettings(showToast=true){
    const wasShowingExpiry=state.settings.show_expiry!==false;
    state.settings.theme=$("themeSelect").value;state.settings.show_expiry=$("showExpiry").checked;setTheme(state.settings.theme);
    await api("/api/settings",{method:"PUT",body:state.settings});
    if(state.settings.show_expiry&&!wasShowingExpiry&&activeProfile())state.expiryRefreshAttempted.delete(activeProfile().id);
    await refreshExpiryIfNeeded();renderProfileStatus();
    if(showToast)toast("Settings saved");
    if(!$("homeScreen").classList.contains("hidden"))await renderHome();
  }
  async function handleProfileSubmit(e){
    e.preventDefault();
    const id=$("editingProfileId").value,method=$("profileMethod").value;
    const payload={nickname:$("profileNickname").value.trim(),method,url:$("serverUrl").value.trim(),playlist_url:$("serverUrl").value.trim(),username:$("profileUsername").value.trim(),password:$("profilePassword").value};
    try{
      const result=await api(id?`/api/profiles/${id}`:"/api/profiles",{method:id?"PUT":"POST",body:payload});
      if(!id&&result.profile)state.activeProfile=state.activeProfile||result.profile.id;
      await loadProfiles();closeProfileModal();await refreshState();toast(id?"Profile updated":"Profile saved");
    }catch(err){$("testResult").textContent=err.message;$("testResult").style.color="var(--danger)";}
  }
  async function testProfile(){
    const payload={nickname:$("profileNickname").value.trim()||"Test",method:$("profileMethod").value,url:$("serverUrl").value.trim(),playlist_url:$("serverUrl").value.trim(),username:$("profileUsername").value.trim(),password:$("profilePassword").value};
    $("testResult").textContent="Testing…";$("testResult").style.color="var(--muted)";
    try{const d=await api("/api/profiles/test",{method:"POST",body:payload});$("testResult").textContent=d.message+(d.expiry?` · Expires ${d.expiry}`:"");$("testResult").style.color="var(--accent)";}
    catch(e){$("testResult").textContent=e.message;$("testResult").style.color="var(--danger)";}
  }
  $("loginForm").addEventListener("submit",async e=>{e.preventDefault();$("loginError").textContent="";try{await api("/api/login",{method:"POST",body:{password:$("loginPassword").value}});$("loginPassword").value="";await refreshState();}catch(err){$("loginError").textContent=err.message;}});
  $("switchProfileTop").addEventListener("click",async()=>{
    if(state.profiles.length<2)return;
    const currentIndex=state.profiles.findIndex(p=>p.id===state.activeProfile);
    const next=state.profiles[(currentIndex+1+state.profiles.length)%state.profiles.length];
    try{await api(`/api/profiles/${next.id}/activate`,{method:"POST"});state.expiryRefreshAttempted.delete(next.id);await refreshState();toast(`Switched to ${activeProfile()?.nickname||"IPTV profile"}`);}
    catch(e){toast(e.message,true);}
  });
  $("firstProfileBtn").addEventListener("click",()=>openProfileModal());
  $("addProfileTop").addEventListener("click",()=>openProfileModal());
  $("profileMethod").addEventListener("change",syncMethodFields);
  $("profileForm").addEventListener("submit",handleProfileSubmit);
  $("testProfileBtn").addEventListener("click",testProfile);
  $("cancelProfileBtn").addEventListener("click",closeProfileModal);
  $("modalClose").addEventListener("click",closeProfileModal);
  $("settingsBtn").addEventListener("click",openSettings);
  $("settingsClose").addEventListener("click",()=>$("settingsBackdrop").classList.add("hidden"));
  $("saveSettings").addEventListener("click",async()=>{try{await saveSettings();$("settingsBackdrop").classList.add("hidden");}catch(e){toast(e.message,true);}});
  $("setAppPassword").addEventListener("click",async()=>{const password=$("newAppPassword").value;if(password.length<8){$("passwordResult").textContent="Use at least 8 characters.";return;}try{await api("/api/password",{method:"POST",body:{password}});$("passwordResult").textContent="Application password saved.";state.passwordConfigured=true;$("newAppPassword").value="";toast("Application password updated");}catch(e){$("passwordResult").textContent=e.message;}});
  $("removeAppPassword").addEventListener("click",async()=>{const password=prompt("Enter the current application password to remove it (leave blank if none is configured):");if(password===null)return;try{await api("/api/password",{method:"DELETE",body:{password:password||" "}});state.passwordConfigured=false;$("passwordResult").textContent="Application password removed.";toast("Application password removed");}catch(e){$("passwordResult").textContent=e.message;}});
  $("settingsProfiles").addEventListener("click",async e=>{const b=e.target.closest("button[data-action]");if(!b)return;const p=state.profiles.find(x=>x.id===b.dataset.id);if(!p)return;
    try{if(b.dataset.action==="edit"){openProfileModal(p);return;}if(b.dataset.action==="switch"){await api(`/api/profiles/${p.id}/activate`,{method:"POST"});await loadProfiles();await refreshState();renderSettingsProfiles();toast(`Switched to ${p.nickname}`);return;}if(b.dataset.action==="delete"){if(!confirm(`Remove profile "${p.nickname}"? This does not cancel the IPTV subscription.`))return;await api(`/api/profiles/${p.id}`,{method:"DELETE"});await loadProfiles();await refreshState();renderSettingsProfiles();toast("Profile removed");}}catch(err){toast(err.message,true);}
  });
  $("homeSections").addEventListener("click",e=>{const favBtn=e.target.closest("[data-favorite-id]");if(favBtn){e.preventDefault();e.stopPropagation();const item=[...(state.catalogByType[favBtn.dataset.favoriteType]||[]),...(state.favoritesByType[favBtn.dataset.favoriteType]||[]),...state.recent.map(x=>x.item)].find(i=>String(i.stream_id??i.series_id??i.id??i.stream_url??getName(i))===favBtn.dataset.favoriteId);if(item)toggleFavorite(item,favBtn.dataset.favoriteType);return;}const cardEl=e.target.closest(".media-card");if(cardEl){const item=[...(state.catalogByType[cardEl.dataset.type]||[]),...(state.favoritesByType[cardEl.dataset.type]||[]),...state.items].find(i=>String(i.stream_id??i.series_id??i.id??i.stream_url??getName(i))===cardEl.dataset.itemId);if(item){const type=cardEl.dataset.type;const showingFavorites=["live","movies","series"].includes(type)&&(state.favoritesByType[type]||[]).some(f=>itemKey(f)===itemKey(item));state.currentNavigation={type,categoryId:showingFavorites?"__favorites__":(item.category_id==null?null:String(item.category_id))};playItem(item,cardEl.dataset.type);return;}const recent=state.recent.find(x=>String(x.item.stream_id??x.item.series_id??x.item.id??x.item.stream_url??getName(x.item))===cardEl.dataset.itemId&&x.type===cardEl.dataset.type);if(recent){const resumed={...recent.item,_navigation:recent.navigation||recent.item._navigation||{type:recent.type,categoryId:recent.item.category_id==null?null:String(recent.item.category_id)}};state.currentNavigation={...resumed._navigation};playItem(resumed,recent.type);}return;}const section=e.target.closest(".home-section");if(section){openBrowser(section.dataset.section);}});
  $("homeSections").addEventListener("keydown",e=>{if((e.key==="Enter"||e.key===" ")&&e.target.closest(".home-section"))openBrowser(e.target.closest(".home-section").dataset.section);});
  $("categoryTree").addEventListener("click",e=>{const b=e.target.closest("[data-category]");if(b){const id=b.dataset.category;const categoryId=id===""?null:id;state.currentNavigation={type:state.mediaType,categoryId};openBrowser(state.mediaType,categoryId);}});
  $("playerTree").addEventListener("click",e=>{const favBtn=e.target.closest("[data-favorite-id]");if(favBtn){const item=(state.playerItems||[]).find(x=>String(x.stream_id??x.series_id??x.id??x.stream_url??getName(x))===favBtn.dataset.favoriteId);if(item)toggleFavorite(item,favBtn.dataset.favoriteType);return;}const b=e.target.closest("[data-player-item]");if(!b)return;const item=(state.playerItems||[]).find(x=>String(x.stream_id??x.series_id??x.id??x.stream_url??getName(x))===b.dataset.playerItem);if(item)playItem(item,state.playerType||state.mediaType);});
  $("mediaGrid").addEventListener("click",e=>{const favBtn=e.target.closest("[data-favorite-id]");if(favBtn){e.preventDefault();e.stopPropagation();const item=state.items.find(i=>String(i.stream_id??i.series_id??i.id??i.stream_url??getName(i))===favBtn.dataset.favoriteId);if(item)toggleFavorite(item,favBtn.dataset.favoriteType);return;}const el=e.target.closest(".media-card");if(!el)return;const item=state.items.find(i=>String(i.stream_id??i.series_id??i.id??i.stream_url??getName(i))===el.dataset.itemId);if(item){state.currentNavigation={type:state.mediaType,categoryId:state.categoryId};playItem(item,state.mediaType);}});
  $("searchInput").addEventListener("input",renderItems);$("sortSelect").addEventListener("change",renderItems);
  $("backHome").addEventListener("click",()=>{stopPlayback();showScreen("homeScreen");renderHome();});
  $("backBrowser").addEventListener("click",()=>{const nav=state.currentNavigation||{type:state.mediaType,categoryId:state.categoryId};stopPlayback();openBrowser(nav.type||state.mediaType,nav.categoryId??null);});
  $("brandHome").addEventListener("click",e=>{e.preventDefault();if(state.profiles.length){stopPlayback();showScreen("homeScreen");renderHome();}});
  $("closeBtn").addEventListener("click",async()=>{
    if(!confirm("Close Local IPTV and stop its server?"))return;
    const video=$("videoPlayer");
    if(video&&state.currentItem)await persistRecent(video.currentTime||0,video.duration||0);
    stopPlayback();
    try{await api("/api/shutdown",{method:"POST"});}catch{}
    window.close();
    document.body.innerHTML='<main style="font:16px system-ui;padding:3rem;max-width:40rem;margin:auto"><h1>Local IPTV stopped</h1><p>The application server has been shut down. You can close this browser tab.</p></main>';
  });
  $("modalBackdrop").addEventListener("click",e=>{if(e.target===$("modalBackdrop"))closeProfileModal();});
  $("settingsBackdrop").addEventListener("click",e=>{if(e.target===$("settingsBackdrop"))$("settingsBackdrop").classList.add("hidden");});
  const video=$("videoPlayer");
  video.addEventListener("loadedmetadata",()=>{
    if(state.resumeOnMetadata&&state.resumeOnMetadata>5){try{video.currentTime=state.resumeOnMetadata;}catch{}}
    state.resumeOnMetadata=null;
  });
  video.addEventListener("timeupdate",()=>{
    const now=Date.now();
    if(now-state.lastRecentSave>15000){state.lastRecentSave=now;persistRecent(video.currentTime||0,video.duration||0);}
  });
  video.addEventListener("pause",()=>{if(!video.ended&&state.currentItem)persistRecent(video.currentTime||0,video.duration||0);});
  video.addEventListener("playing",()=>{if(video._playbackTimer)clearTimeout(video._playbackTimer);$("playerMessage").classList.add("hidden");});
  video.addEventListener("error",async()=>{
    if(video._playbackTimer)clearTimeout(video._playbackTimer);
    const item=state.currentItem,type=state.playerType;
    const ext=String(item?.container_extension||item?.extension||"").toLowerCase();
    if(type==="movies"&&!state.movieFallbackTried&&ext&&ext!=="mp4"&&item&&!item.stream_url){
      state.movieFallbackTried=true;
      try{
        const id=item.stream_id??item.id;
        const d=await api(`/api/stream-url/movies/${encodeURIComponent(id)}?profile_id=${encodeURIComponent(state.activeProfile)}&extension=mp4`);
        state.currentStreamUrl=d.url;
        video.pause();video.removeAttribute("src");video.load();
        video.src=d.url;video.play().catch(()=>showPlayerError("The MP4 fallback could not start. The provider may not offer this movie in a browser-compatible format."));
        return;
      }catch{}
    }
    showPlayerError("Playback failed. This movie may be encoded in a format this browser cannot decode, or the provider may reject direct browser playback. The app tried an MP4 fallback when available. Try another title or use a provider/device that supports this format.");
  });
  video.addEventListener("waiting",()=>{if(!video._playbackTimer)video._playbackTimer=setTimeout(()=>showPlayerError("The stream is buffering for too long. Check provider availability or try another stream format."),15000);});
  window.addEventListener("beforeunload",()=>{const video=$("videoPlayer");if(video&&state.currentItem)persistRecent(video.currentTime||0,video.duration||0);stopPlayback();});
  refreshState().catch(e=>{showScreen("setupScreen");toast(e.message,true);});
})();