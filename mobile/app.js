// Compagnon mobile d'Alyx — client WebSocket vanilla JS, sans framework ni build.
// Reprend exactement le même protocole JSON que l'UI C# (AlyxDesktop/MainWindow.axaml.cs) :
// même serveur, même contrat de messages, donc mêmes fonctionnalités (fichiers, PDF,
// rappels/notes, batterie/réseau...) accessibles depuis le téléphone.
//
// Volontairement PAS de bouton micro ici : activer 'vocal' ferait écouter le
// MICROPHONE DU PC (mode_vocal déclenche un enregistrement côté serveur, pas côté
// client), ce qui serait un contresens depuis un téléphone. Toutes les requêtes
// envoyées par ce client portent donc vocal: false.

(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const pairingScreen = $('pairing-screen');
  const chatScreen = $('chat-screen');
  const inputHost = $('input-host');
  const inputToken = $('input-token');
  const btnConnect = $('btn-connect');
  const pairingError = $('pairing-error');
  const chatList = $('chat-list');
  const statusLine = $('status-line');
  const inputText = $('input-text');
  const sendBtn = $('send-btn');
  const stopBtn = $('stop-btn');
  const modelsSelect = $('models-select');
  const forgetBtn = $('forget-btn');

  let ws = null;
  let isProcessing = false;
  let currentStreamingEl = null;
  let reconnectDelay = 1000;
  let reconnectTimer = null;
  let intentionalClose = false;

  // --- Persistance du jumelage (une seule saisie par téléphone) ---
  function chargerJumelage() {
    return {
      host: localStorage.getItem('alyx_host') || '',
      token: localStorage.getItem('alyx_token') || '',
    };
  }

  function sauvegarderJumelage(host, token) {
    localStorage.setItem('alyx_host', host);
    localStorage.setItem('alyx_token', token);
  }

  function oublierJumelage() {
    localStorage.removeItem('alyx_host');
    localStorage.removeItem('alyx_token');
  }

  // --- Rendu des messages ---
  function ajouterMessage(role, texte) {
    const el = document.createElement('div');
    el.className = `msg ${role}`;
    el.textContent = texte;
    chatList.appendChild(el);
    chatList.scrollTop = chatList.scrollHeight;
    return el;
  }

  function afficherReflexion() {
    if (chatList.querySelector('.msg.thinking')) return;
    const el = document.createElement('div');
    el.className = 'msg thinking';
    el.textContent = 'Alyx réfléchit...';
    el.id = 'thinking-indicator';
    chatList.appendChild(el);
    chatList.scrollTop = chatList.scrollHeight;
  }

  function masquerReflexion() {
    const el = $('thinking-indicator');
    if (el) el.remove();
  }

  function ajouterDemandePermission(action, cible, toolCall) {
    const container = document.createElement('div');
    container.className = 'msg error';
    container.style.borderColor = '#E55934';
    container.style.color = '#1A1A1A';
    container.style.textAlign = 'left';
    container.style.alignSelf = 'center';
    container.style.maxWidth = '95%';

    const titre = document.createElement('div');
    titre.style.fontWeight = '800';
    titre.textContent = `Action destructive détectée : ${action}`;
    container.appendChild(titre);

    const detail = document.createElement('div');
    detail.style.margin = '6px 0';
    detail.textContent = `Cible : ${cible}\nAlyx attend votre validation avant de procéder.`;
    detail.style.whiteSpace = 'pre-wrap';
    container.appendChild(detail);

    const boutons = document.createElement('div');
    boutons.style.display = 'flex';
    boutons.style.gap = '10px';
    boutons.style.marginTop = '8px';

    const btnOk = document.createElement('button');
    btnOk.textContent = 'Autoriser';
    const btnNon = document.createElement('button');
    btnNon.textContent = 'Refuser';
    btnNon.className = 'secondary';

    const repondre = (accorde) => {
      btnOk.disabled = true;
      btnNon.disabled = true;
      envoyer({ type: accorde ? 'permission_granted' : 'permission_denied', tool_call: toolCall });
      ajouterMessage('user', accorde ? "J'autorise l'action." : 'Je refuse cette action.');
    };
    btnOk.onclick = () => repondre(true);
    btnNon.onclick = () => repondre(false);

    boutons.appendChild(btnOk);
    boutons.appendChild(btnNon);
    container.appendChild(boutons);

    chatList.appendChild(container);
    chatList.scrollTop = chatList.scrollHeight;
  }

  // --- État de traitement (boutons, indicateurs) ---
  function debuterTraitement() {
    isProcessing = true;
    sendBtn.disabled = true;
    stopBtn.classList.add('visible');
    afficherReflexion();
  }

  function terminerTraitement() {
    isProcessing = false;
    sendBtn.disabled = false;
    stopBtn.classList.remove('visible');
    masquerReflexion();
    currentStreamingEl = null;
  }

  // --- WebSocket ---
  function envoyer(payload) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload));
    }
  }

  function connecter(host, token, { estTentativeInitiale } = {}) {
    intentionalClose = false;
    let url;
    try {
      url = `ws://${host}/?token=${encodeURIComponent(token)}`;
    } catch (e) {
      afficherErreurJumelage("Adresse invalide.");
      return;
    }

    statusLine.textContent = 'Statut : connexion...';
    ws = new WebSocket(url);

    const timeoutInitial = estTentativeInitiale
      ? setTimeout(() => {
          if (ws.readyState !== WebSocket.OPEN) {
            ws.close();
            // Les navigateurs ne donnent JAMAIS accès au code HTTP (401 vs PC injoignable
            // vs mauvaise IP) refusé pendant la poignée de main WebSocket, par restriction
            // de sécurité du standard — le message reste donc volontairement générique.
            afficherErreurJumelage(
              "Connexion impossible : vérifiez l'adresse IP:port, que Alyx tourne bien " +
              "sur le PC, que le téléphone est sur le même Wi-Fi, et le code de jumelage."
            );
          }
        }, 6000)
      : null;

    ws.onopen = () => {
      if (timeoutInitial) clearTimeout(timeoutInitial);
      reconnectDelay = 1000;
      sauvegarderJumelage(host, token);
      afficherEcranChat();
      statusLine.textContent = 'Statut : connecté';
      envoyer({ type: 'get_models' });
    };

    ws.onmessage = (event) => traiterMessage(JSON.parse(event.data));

    ws.onclose = () => {
      if (timeoutInitial) clearTimeout(timeoutInitial);
      if (intentionalClose) return;
      statusLine.textContent = 'Statut : déconnecté (reconnexion...)';
      terminerTraitement();
      reconnectTimer = setTimeout(() => {
        reconnectDelay = Math.min(reconnectDelay * 1.5, 15000);
        connecter(host, token, { estTentativeInitiale: false });
      }, reconnectDelay);
    };

    ws.onerror = () => { /* onclose suit systématiquement : traité là-bas */ };
  }

  function afficherErreurJumelage(texte) {
    pairingError.textContent = texte;
    btnConnect.disabled = false;
    btnConnect.textContent = 'Se connecter';
  }

  function afficherEcranChat() {
    pairingScreen.classList.add('hidden');
    chatScreen.classList.add('active');
    pairingError.textContent = '';
  }

  // --- Traitement des messages serveur (même contrat que le client C#) ---
  function traiterMessage(data) {
    switch (data.type) {
      case 'models_list': {
        modelsSelect.innerHTML = '';
        const providers = data.providers || {};
        for (const [nomFournisseur, modeles] of Object.entries(providers)) {
          for (const m of modeles) {
            const opt = document.createElement('option');
            opt.value = m.name;
            opt.textContent = `[${nomFournisseur.toUpperCase()}] ${m.name}`;
            if (m.name === data.current_model) opt.selected = true;
            modelsSelect.appendChild(opt);
          }
        }
        break;
      }

      case 'model_selected':
        ajouterMessage('system', `Modèle changé vers '${data.model}'`);
        break;

      case 'system_action':
        ajouterMessage('system', data.content);
        break;

      case 'listening':
        // Ne devrait normalement jamais arriver depuis ce client (vocal toujours
        // false), géré par prudence si le contrat serveur évolue.
        afficherReflexion();
        break;

      case 'token':
        masquerReflexion();
        if (!currentStreamingEl) {
          currentStreamingEl = ajouterMessage('alyx', '');
        }
        currentStreamingEl.textContent += data.content;
        chatList.scrollTop = chatList.scrollHeight;
        break;

      case 'done':
        terminerTraitement();
        break;

      case 'error':
        masquerReflexion();
        if (data.reason !== 'silence') {
          ajouterMessage('error', data.message || 'Erreur');
        }
        terminerTraitement();
        break;

      case 'action_required':
        masquerReflexion();
        ajouterDemandePermission(data.action, data.cible, data.tool_call);
        break;

      default:
        break; // types inconnus (mobile_info, provider_status...) ignorés ici
    }
  }

  // --- Envoi utilisateur ---
  function envoyerMessage() {
    const texte = inputText.value.trim();
    if (!texte || isProcessing) return;
    ajouterMessage('user', texte);
    inputText.value = '';
    inputText.style.height = 'auto';
    debuterTraitement();
    envoyer({ type: 'chat', prompt: texte, vocal: false });
  }

  sendBtn.addEventListener('click', envoyerMessage);
  inputText.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      envoyerMessage();
    }
  });
  inputText.addEventListener('input', () => {
    inputText.style.height = 'auto';
    inputText.style.height = Math.min(inputText.scrollHeight, 120) + 'px';
  });

  stopBtn.addEventListener('click', () => envoyer({ type: 'cancel' }));

  modelsSelect.addEventListener('change', () => {
    envoyer({ type: 'select_model', model: modelsSelect.value });
  });

  forgetBtn.addEventListener('click', () => {
    if (!confirm("Oublier ce PC ? Il faudra ressaisir l'adresse et le code de jumelage.")) return;
    intentionalClose = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (ws) ws.close();
    oublierJumelage();
    inputHost.value = '';
    inputToken.value = '';
    chatList.innerHTML = '';
    chatScreen.classList.remove('active');
    pairingScreen.classList.remove('hidden');
    btnConnect.disabled = false;
    btnConnect.textContent = 'Se connecter';
  });

  // --- Écran de jumelage ---
  btnConnect.addEventListener('click', () => {
    const host = inputHost.value.trim().replace(/^wss?:\/\//, '').replace(/\/$/, '');
    const token = inputToken.value.trim();
    if (!host || !token) {
      afficherErreurJumelage('Adresse et code de jumelage requis.');
      return;
    }
    btnConnect.disabled = true;
    btnConnect.textContent = 'Connexion...';
    pairingError.textContent = '';
    connecter(host, token, { estTentativeInitiale: true });
  });

  // --- Démarrage ---
  const { host, token } = chargerJumelage();
  if (host && token) {
    inputHost.value = host;
    inputToken.value = token;
    connecter(host, token, { estTentativeInitiale: true });
  }

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('sw.js').catch(() => { /* installable en best-effort */ });
  }
})();
