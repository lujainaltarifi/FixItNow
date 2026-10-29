document.addEventListener('DOMContentLoaded',()=> {
  const chatForm = document.getElementById('chatForm');
  const chatWindow = document.getElementById('chatWindow');
  if (!chatForm) return;

  function appendBubble(text, cls){
    const div = document.createElement('div');
    div.className = 'bubble ' + cls;
    div.textContent = text;
    chatWindow.appendChild(div);
    chatWindow.scrollTop = chatWindow.scrollHeight;
  }

  chatForm.addEventListener('submit', async e=>{
    e.preventDefault();
    const inp = document.getElementById('userInput');
    let msg = inp.value.trim();
    if(!msg) return;
    appendBubble(msg,'user');
    inp.value='';
    appendBubble('...', 'bot');

    let res = await fetch('/api/chat',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({message:msg})
    });
    let data = await res.json();
    chatWindow.lastChild.remove();
    appendBubble(data.reply || 'Error, try again.','bot');
  });
});
