async function sendJarvisCommand(text){
  const reply=document.getElementById('jarvisReply');
  const links=document.getElementById('jarvisLinks');
  reply.textContent='Working...';
  links.innerHTML='';
  try{
    const res=await fetch('/jarvis-brain/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})});
    const data=await res.json();
    reply.textContent=data.reply || 'Done.';
    if(data.links){
      links.innerHTML=data.links.map(l=>`<a href="${l.url}">${l.kind}: ${l.title}</a>`).join('');
    }
  }catch(e){
    reply.textContent='Jarvis hit an error: '+e;
  }
}
document.addEventListener('DOMContentLoaded',()=>{
  const box=document.getElementById('jarvisCommand');
  const send=document.getElementById('sendJarvis');
  const mic=document.getElementById('micJarvis');
  document.querySelectorAll('.quick-command').forEach(b=>b.addEventListener('click',()=>{box.value=b.dataset.command||'';box.focus();}));
  send.addEventListener('click',()=>{const t=box.value.trim(); if(t) sendJarvisCommand(t);});
  box.addEventListener('keydown',e=>{if(e.key==='Enter' && (e.ctrlKey||e.metaKey)){send.click();}});
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SR){mic.disabled=true; mic.textContent='Mic not supported'; return;}
  const rec=new SR(); rec.continuous=false; rec.interimResults=false; rec.lang='en-US';
  rec.onresult=e=>{box.value=(e.results[0][0].transcript||''); send.click();};
  rec.onerror=e=>{document.getElementById('jarvisReply').textContent='Mic error: '+e.error;};
  mic.addEventListener('click',()=>rec.start());
});