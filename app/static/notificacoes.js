// Avisos como no WhatsApp (pedido da Maria em 23/11/2026: "replique o funcionamento de notificações do WhatsApp para o
// sistema, além de que adicione esse som para quando alguém responder em alguma conversa ou algum disparo de alguma
// campanha"). Em qualquer tela do sistema:
// - os números vermelhos do menu (Conversas, API Oficial, Oportunidades, a soma de cada grupo do menu de cima e a do ☰
//   no celular) e os Avisos mudam sozinhos;
// - o título da aba ganha o número de novidades, como "(3) Leads";
// - chegou mensagem ou resposta de campanha: toca o som (static/sons/notificacao.wav) e, com a permissão do
//   navegador, aparece o aviso no canto da tela do computador (clicar abre a conversa ou a oportunidade).
// Pergunta a /novidades (app/novidades.py) a cada 15 s com a aba à vista e a cada 30 s com ela escondida. Com várias
// abas abertas, só a primeira que vê a novidade avisa (o "até onde já vi" fica guardado no navegador). Conversa aberta
// na tela à vista não avisa (como no WhatsApp). O som só toca depois de um clique na página: regra dos navegadores.
(function () {
  'use strict';
  const GUARDADO = 'ms_novidades_ultimos', SOM_LIGADO = 'ms_novidades_som';
  const CHAVES = { conversa: 'c', oficial: 'o', resposta: 'n' };
  // "Até onde já vi" mais velho que isto (o sistema ficou fechado): recomeça sem avisar o que chegou enquanto isso
  // (os números do menu já mostram), para não abrir o sistema de manhã com uma enxurrada de avisos
  const VALIDADE_MS = 10 * 60 * 1000;
  const tituloBase = document.title.replace(/^\(\d+\)\s*/, '');
  let audio = null, ocupado = false, parado = false;

  function ler(chave, padrao) {
    try { const v = localStorage.getItem(chave); return v === null ? padrao : v; } catch (e) { return padrao; }
  }
  function gravar(chave, valor) { try { localStorage.setItem(chave, valor); } catch (e) { /* aba privada */ } }
  const somLigado = () => ler(SOM_LIGADO, '1') === '1';
  function vistos() {
    try { const v = JSON.parse(ler(GUARDADO, '') || 'null'); return v && typeof v === 'object' ? v : null; } catch (e) { return null; }
  }

  function tocar() {
    if (!somLigado()) return;
    try {
      audio = audio || new Audio('/static/sons/notificacao.wav');
      audio.currentTime = 0;
      const p = audio.play();
      if (p && p.catch) p.catch(() => { /* sem clique na página ainda: o navegador não deixa tocar */ });
    } catch (e) { /* navegador sem som */ }
  }

  function contador(id, valor) {
    const el = document.getElementById(id);
    if (!el || typeof valor !== 'number') return;
    el.textContent = valor;
    el.hidden = !valor;
  }

  // O número de cada grupo do menu de cima (e o do ☰ no celular) é a soma dos números das telas dele (data-soma)
  function somarGrupos() {
    document.querySelectorAll('[data-soma]').forEach(el => {
      const soma = el.dataset.soma.split(' ').reduce((total, id) => {
        const c = document.getElementById(id);
        return total + (c && !c.hidden ? Number(c.textContent) || 0 : 0);
      }, 0);
      el.textContent = soma;
      el.hidden = !soma;
    });
  }

  function mostrarContadores(c) {
    contador('contador-conversas', c.conversas);
    contador('contador-oficial', c.oficial);
    contador('contador-oportunidades', c.oportunidades);
    somarGrupos();
    const avisos = document.getElementById('link-avisos');
    if (avisos && typeof c.avisos === 'number') avisos.textContent = 'Avisos' + (c.avisos ? ' (' + c.avisos + ')' : '');
    const total = ['conversas', 'oficial', 'oportunidades'].reduce((soma, k) => soma + (c[k] || 0), 0);
    document.title = (total ? '(' + total + ') ' : '') + tituloBase;
  }

  // A conversa já está aberta na tela à vista (Conversas ou API Oficial): não avisa, como o WhatsApp
  function estaAberta(item) {
    if (document.hidden) return false;
    const a = window.conversaAberta;
    return !!a && a.tipo === item.tipo && a.telefone === item.telefone && (!a.numero || a.numero === item.numero);
  }

  function avisoNaTela(item) {
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    if (!document.hidden && document.hasFocus()) return;  // com o sistema à frente, o som e o menu bastam
    try {
      const aviso = new Notification(item.titulo, { body: item.texto, tag: item.chave });
      aviso.onclick = function () {
        window.focus();
        if (/^\/(?!\/)/.test(item.link || '')) location.href = item.link;  // só endereços do próprio sistema
        aviso.close();
      };
    } catch (e) { /* celular: o aviso precisa de outro caminho; fica o som */ }
  }

  async function perguntar() {
    if (ocupado || parado) return;
    ocupado = true;
    try {
      const guardado = vistos();
      const antes = guardado && Date.now() - (Number(guardado.t) || 0) < VALIDADE_MS ? guardado : null;
      const params = antes ? '?c=' + (antes.c || 0) + '&o=' + (antes.o || 0) + '&n=' + (antes.n || 0) : '';
      let d;
      try {
        const r = await fetch('/novidades' + params, { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
        if (!r.ok || !(r.headers.get('content-type') || '').includes('json')) {
          if (r.redirected || r.status === 401) parado = true;  // a sessão acabou: para de perguntar
          return;
        }
        d = await r.json();
      } catch (e) { return; }
      mostrarContadores(d.contadores || {});
      // outra aba pode ter avisado enquanto esta esperava (o guardado vencido não vale)
      const atual = vistos();
      const agora = antes && atual ? atual : {};
      const novas = (d.novas || []).filter(item => !(Number(agora[CHAVES[item.tipo]]) >= item.id));
      const u = d.ultimos || {};
      gravar(GUARDADO, JSON.stringify({
        c: Math.max(Number(agora.c) || 0, Number(u.c) || 0),
        o: Math.max(Number(agora.o) || 0, Number(u.o) || 0),
        n: Math.max(Number(agora.n) || 0, Number(u.n) || 0),
        t: Date.now(),
      }));
      const avisar = novas.filter(item => !estaAberta(item));
      if (avisar.length) {
        tocar();
        avisar.slice(0, 3).forEach(avisoNaTela);
      }
      if ((d.novas || []).length) document.dispatchEvent(new CustomEvent('novidades', { detail: d }));
    } finally {
      ocupado = false;
    }
  }

  function proxima() {
    if (parado) return;
    setTimeout(() => { perguntar().finally(proxima); }, document.hidden ? 30000 : 15000);
  }

  function montarBotoes() {
    const caixa = document.getElementById('notif-config');
    if (!caixa) return;
    caixa.hidden = false;
    const som = document.getElementById('notif-som'), tela = document.getElementById('notif-tela');
    const textoDoSom = () => {
      som.textContent = somLigado() ? '🔊 Som ligado' : '🔇 Som desligado';
      som.classList.toggle('desligado', !somLigado());
    };
    som.addEventListener('click', () => { gravar(SOM_LIGADO, somLigado() ? '0' : '1'); textoDoSom(); tocar(); });
    textoDoSom();
    if (!('Notification' in window)) { tela.hidden = true; return; }
    const textoDaTela = () => {
      const p = Notification.permission;
      tela.textContent = p === 'granted' ? '🔔 Avisos na tela ligados'
        : (p === 'denied' ? '🔕 Avisos bloqueados no navegador' : '🔔 Ativar avisos na tela');
      tela.disabled = p !== 'default';
      if (p === 'denied') tela.title = 'Para liberar: clique no cadeado ao lado do endereço do site > Notificações > Permitir';
    };
    tela.addEventListener('click', async () => {
      try { await Notification.requestPermission(); } catch (e) { /* navegador antigo */ }
      textoDaTela();
      if (Notification.permission === 'granted') tocar();
    });
    textoDaTela();
  }

  montarBotoes();
  document.addEventListener('visibilitychange', () => { if (!document.hidden) perguntar(); });
  perguntar().finally(proxima);
})();
