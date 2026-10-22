// Prospecção de Parceiros – funções comuns das telas.
(function () {
  const csrf = () => document.querySelector('meta[name="csrf"]').content;

  function aviso(texto) {
    const el = document.createElement('div');
    el.className = 'copiado';
    el.textContent = texto;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3200);
  }
  window.aviso = aviso;

  async function postarJSON(url, dados) {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf() },
      body: JSON.stringify(dados),
    });
    let corpo = {};
    try { corpo = await r.json(); } catch (e) { /* sem corpo */ }
    if (!r.ok) throw new Error(corpo.erro || 'Não foi possível salvar. Recarregue a página.');
    return corpo;
  }
  window.postarJSON = postarJSON;

  async function copiarTexto(texto) {
    try {
      await navigator.clipboard.writeText(texto);
    } catch (e) {
      const area = document.createElement('textarea');
      area.value = texto;
      document.body.appendChild(area);
      area.select();
      document.execCommand('copy');
      area.remove();
    }
  }

  // Botões "Copiar mensagem" e "Abrir no WhatsApp": registram no histórico (limite diário, opt-out).
  document.addEventListener('click', async (ev) => {
    const botao = ev.target.closest('[data-copiar], [data-whatsapp]');
    if (!botao) return;
    ev.preventDefault();
    const origem = document.getElementById(botao.dataset.alvo);
    const texto = origem ? (origem.value !== undefined && origem.tagName !== 'DIV' ? origem.value : origem.innerText) : '';
    const dados = { lead_id: botao.dataset.lead || null, canal: botao.dataset.canal || 'whatsapp', corpo: texto,
                    assunto: botao.dataset.assunto || '', tarefa_id: botao.dataset.tarefa || null };
    try {
      const r = await postarJSON('/api/mensagens/registrar', dados);
      await copiarTexto(texto);
      if (botao.dataset.whatsapp) {
        window.open(botao.dataset.whatsapp + '?text=' + encodeURIComponent(texto), '_blank', 'noopener');
      }
      aviso(r.aviso ? 'Copiado. Atenção: ' + r.aviso : 'Mensagem copiada! Cole e envie.');
    } catch (e) {
      aviso(e.message);
    }
  });

  // Seleção de todos os itens de uma lista.
  document.addEventListener('change', (ev) => {
    if (ev.target.matches('[data-marcar-todos]')) {
      document.querySelectorAll(ev.target.dataset.marcarTodos).forEach((c) => { c.checked = ev.target.checked; });
    }
  });

  // Confirmação antes de ações importantes.
  document.addEventListener('submit', (ev) => {
    const msg = ev.target.dataset.confirmar;
    if (msg && !confirm(msg)) ev.preventDefault();
  });

  // Menu no celular.
  const botaoMenu = document.getElementById('abrir-menu');
  if (botaoMenu) botaoMenu.addEventListener('click', () => document.querySelector('.menu').classList.toggle('aberto'));
})();
