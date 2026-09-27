// ==UserScript==
// @name         Chaoxing local playback controls
// @namespace    https://github.com/ieduer/chaoxing
// @version      1.0.0
// @description  Real HTML5 playback, mute and next chapter; respects platform pauses and challenges.
// @match        https://*.chaoxing.com/*
// @grant        none
// ==/UserScript==
(() => {
  "use strict";
  if (!/\/(?:ananas\/modules\/(?:video|audio)|mooc-ans\/mycourse\/studentstudy)/.test(location.pathname)) return;
  const seen = new WeakSet();
  const configure = media => {
    if (seen.has(media)) return;
    seen.add(media);
    const panel = document.createElement("div");
    panel.style.cssText = "position:fixed;right:12px;top:12px;z-index:2147483647;background:#fff;color:#123;padding:10px;border:1px solid #789;border-radius:8px;font:14px sans-serif";
    const rate = document.createElement("select");
    rate.setAttribute("aria-label", "播放倍速");
    for (const n of [1,1.25,1.5,1.75,2]) {const o=document.createElement("option");o.value=n;o.textContent=n+"×";rate.append(o);}
    const mute=document.createElement("button");mute.textContent="静音";
    const play=document.createElement("button");play.textContent="播放";
    const note=document.createElement("small");note.textContent="平台暂停或验证时，请先在页面处理。";
    rate.onchange=()=>{media.playbackRate=Number(rate.value);};
    mute.onclick=()=>{media.muted=!media.muted;mute.textContent=media.muted?"取消静音":"静音";};
    play.onclick=async()=>{try{await media.play();}catch(_){note.textContent="请点击平台播放器开始播放。";}};
    panel.append(rate,mute,play,document.createElement("br"),note);document.body.append(panel);
    media.addEventListener("ended",()=>{
      // Do not mark completion or skip checks. Offer the actual next-chapter control when visible.
      let win=window;
      for(let i=0;i<5;i++){
        try{
          const next=win.document.getElementById("prevNextFocusNext");
          if(next){note.textContent="本视频播放结束；可使用页面的下一节按钮继续。";return;}
          if(win===win.parent)break;
          win=win.parent;
        }catch(_){break;}
      }
      note.textContent="播放结束，请确认平台任务点状态。";
    });
  };
  const scan=()=>document.querySelectorAll("video,audio").forEach(configure);
  new MutationObserver(scan).observe(document.documentElement,{childList:true,subtree:true});scan();
})();
