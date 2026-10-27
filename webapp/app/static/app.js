'use strict';
const $ = id => document.getElementById(id);
const money = value => new Intl.NumberFormat('fr-FR', {style:'currency', currency:'EUR', maximumFractionDigits:0}).format(value);
const number = value => new Intl.NumberFormat('fr-FR', {maximumFractionDigits:0}).format(value);
const date = value => value ? new Date(value * 1000).toLocaleString('fr-FR', {dateStyle:'short', timeStyle:'short'}) : '—';
const modelNames = {m3:'Model 3', my:'Model Y', ms:'Model S', mx:'Model X'};
let dashboard, needsSetup = false, formDirty = false, latestEvent = null, pollTimer, toastTimer;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function toast(message, error = false) {
  clearTimeout(toastTimer);
  $('toast').textContent = message;
  $('toast').className = 'toast' + (error ? ' error' : '');
  $('toast').hidden = false;
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, 7000);
}
async function api(path, method = 'GET', body) {
  const response = await fetch('/api/' + path, {
    method, credentials:'same-origin', headers:{'Content-Type':'application/json', 'X-Requested-With':'TeslaInventoryWatch'},
    ...(body === undefined ? {} : {body:JSON.stringify(body)})
  });
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 && !['login', 'setup'].includes(path)) showAuth();
    let detail = data.detail;
    if (Array.isArray(detail)) detail = detail.map(item => item.msg).join(' · ');
    if (typeof detail === 'object' && detail !== null) detail = detail.message;
    throw new Error(detail || 'La requête a échoué.');
  }
  return data;
}
function showAuth() {
  clearInterval(pollTimer);
  $('application').hidden = true;
  $('auth-screen').hidden = false;
}
async function boot() {
  try {
    const session = await api('session');
    needsSetup = session.needs_setup;
    $('auth-title').textContent = needsSetup ? 'Faites comme chez vous.' : 'Bienvenue chez vous.';
    $('auth-description').textContent = needsSetup ? 'Créez votre accès privé. Votre mot de passe protège les recherches de cette instance.' : 'Connectez-vous pour retrouver votre surveillance.';
    $('auth-submit').textContent = needsSetup ? 'Créer mon accès →' : 'Se connecter →';
    $('confirm-label').hidden = !needsSetup;
    $('password-confirm').hidden = !needsSetup;
    $('password-confirm').required = needsSetup;
    $('password').autocomplete = needsSetup ? 'new-password' : 'current-password';
    if (session.authenticated) await enterApp();
  } catch (error) { $('auth-error').textContent = 'Impossible de joindre le serveur. Vérifiez son démarrage.'; }
}
$('auth-form').addEventListener('submit', async event => {
  event.preventDefault();
  $('auth-error').textContent = '';
  if (needsSetup && $('password').value !== $('password-confirm').value) {
    $('auth-error').textContent = 'Les deux mots de passe doivent être identiques.'; return;
  }
  $('auth-submit').disabled = true;
  try {
    await api(needsSetup ? 'setup' : 'login', 'POST', {password:$('password').value});
    $('auth-form').reset();
    await enterApp();
  } catch (error) { $('auth-error').textContent = error.message; }
  finally { $('auth-submit').disabled = false; }
});
async function enterApp() {
  latestEvent = null;
  await refresh();
  $('auth-screen').hidden = true;
  $('application').hidden = false;
  showView();
  clearInterval(pollTimer);
  pollTimer = setInterval(() => refresh().catch(error => toast(error.message, true)), 15000);
}
async function logout() {
  try { await api('logout', 'POST'); showAuth(); await boot(); } catch (error) { toast(error.message, true); }
}
$('logout').addEventListener('click', logout);
$('account-logout').addEventListener('click', logout);
function showView() {
  const requested = location.hash.slice(1) || 'dashboard';
  const view = ['dashboard','search','history','help'].includes(requested) ? requested : 'dashboard';
  for (const section of document.querySelectorAll('.view')) section.hidden = section.id !== 'view-' + view;
  for (const link of document.querySelectorAll('[data-view]')) link.classList.toggle('active', link.dataset.view === view);
  const labels = {dashboard:'Tableau de bord',search:'Ma recherche',history:'Historique',help:'Comment ça marche'};
  $('breadcrumb').replaceChildren(document.createTextNode('Votre espace '), element('span', '/'), document.createTextNode(' ' + labels[view]));
}
window.addEventListener('hashchange', showView);
async function refresh() {
  dashboard = await api('dashboard');
  render(dashboard);
}
function render(data) {
  const {config, state, vehicles, events, checks, enabled} = data;
  const unread = events.filter(item => !item.read_at);
  const now = data.server_time;
  $('available-count').textContent = state.initialized ? number(vehicles.length) : '—';
  $('new-count').replaceChildren(document.createTextNode(number(data.unread_count)), element('span','✧','stat-spark'));
  $('last-success').textContent = state.last_success ? `Relevé ${state.source === 'import' ? 'importé' : 'vérifié'} le ${date(state.last_success)}` : 'Votre premier contrôle vous attend';
  $('nav-count').textContent = data.unread_count;
  $('nav-count').hidden = !data.unread_count;
  const checking = state.status === 'checking';
  const status = checking ? 'Contrôle en cours' : state.error ? 'Accès à vérifier' : enabled ? 'Surveillance active' : 'Surveillance en pause';
  $('status-badge').replaceChildren(element('span', '', 'small-dot'), document.createTextNode(status));
  $('status-badge').className = 'status-pill' + (state.error ? ' error' : enabled || checking ? ' running' : '');
  $('toggle-monitor').textContent = enabled ? 'Mettre en pause Ⅱ' : 'Activer la surveillance →';
  if (checking) {
    $('next-check').textContent = 'En cours…'; $('next-caption').textContent = 'Chromium consulte l’inventaire Tesla';
  } else if (state.next_check > now) {
    const remaining = state.next_check - now;
    const minutes = Math.ceil(remaining / 60);
    $('next-check').textContent = `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2,'0')}`;
    $('next-caption').textContent = `${enabled ? 'Contrôle prévu' : 'Contrôle autorisé'} le ${date(state.next_check)}`;
  } else {
    $('next-check').textContent = enabled ? 'Imminent.' : 'À votre rythme.';
    $('next-caption').textContent = enabled ? 'Le serveur prépare le prochain contrôle' : 'Une vérification toutes les 8 heures';
  }
  $('status-message').hidden = !state.error;
  $('status-message').textContent = state.error ? `${state.error} Aucun nouvel appel avant le ${date(state.next_check)}. La collecte n’est pas garantie sur chaque réseau.` : '';
  $('check-now').disabled = checking || state.next_check > now;
  $('check-now').title = $('check-now').disabled ? `Prochaine tentative autorisée : ${date(state.next_check)}` : 'Lancer un contrôle avec Chromium';
  $('summary-title').textContent = `${modelNames[config.model]} · ${config.condition === 'used' ? 'Occasion' : 'Neuf'}`;
  const chips = [config.years.length ? config.years.join(', ') : 'Toutes années', `${money(config.price_min)} – ${money(config.price_max)}`, `${number(config.odometer_min)} – ${number(config.odometer_max)} km`, config.paints.length ? config.paints.join(' / ') : 'Toutes couleurs', config.zip];
  $('summary-chips').replaceChildren(...chips.map(chip => element('span', chip, 'chip')));
  $('vehicle-counter').textContent = vehicles.length;
  $('vehicles').replaceChildren(...vehicles.map(vehicle => vehicleCard(vehicle, unread.some(item => item.vin === vehicle.vin))));
  $('empty-state').hidden = vehicles.length > 0;
  $('empty-description').textContent = state.error ? 'Tesla n’a pas fourni d’inventaire exploitable. Le détail et la prochaine tentative sont affichés ci-dessus.' : state.initialized ? 'Aucun véhicule ne correspond actuellement à votre recherche. La surveillance continue avec vos critères.' : 'Vérifiez vos critères, puis lancez votre premier contrôle. La première recherche crée une référence silencieuse.';
  $('events-list').replaceChildren(...(events.length ? events.map(eventRow) : [element('div', 'Vos nouvelles annonces apparaîtront ici après le premier contrôle de référence.', 'empty-state muted')]));
  const statusLabels = {success:'Réussi',error:'Erreur',running:'En cours',interrupted:'Interrompu',discarded:'Ignoré'};
  $('checks-list').replaceChildren(...checks.map(check => {
    const tr = element('tr');
    for (const value of [date(check.started), check.source === 'import' ? 'Import manuel' : 'Chromium', statusLabels[check.status] || check.status, check.count ?? '—', check.detail || '—']) tr.append(element('td', value));
    return tr;
  }));
  if (!formDirty) fillForm(config);
  const maxEvent = events.length ? Math.max(...events.map(item => item.id)) : 0;
  if (latestEvent !== null && maxEvent > latestEvent) {
    const arrivals = events.filter(item => item.id > latestEvent);
    toast(`${arrivals.length} nouvelle(s) Tesla correspondant à votre recherche.`);
    if (localStorage.getItem('browser-alerts') === 'yes' && 'Notification' in window && Notification.permission === 'granted') {
      for (const item of arrivals.slice(0, 5)) {
        const vehicle = item.vehicle;
        const notice = new Notification('Une nouvelle Tesla vous attend', {body:`${vehicle.year} · ${vehicle.trim} · ${money(vehicle.price)} · ${vehicle.city}`, icon:'/static/icon.svg', tag:'vehicle-' + vehicle.vin});
        notice.onclick = () => { window.focus(); location.hash = '#history'; notice.close(); };
      }
    }
  }
  latestEvent = maxEvent;
}
function vehicleCard(vehicle, fresh) {
  const card = element('article', undefined, 'vehicle-card');
  const top = element('div', undefined, 'vehicle-top');
  top.append(element('small', `TESLA · ${vehicle.year}`));
  if (fresh) top.append(element('span', 'NOUVELLE ANNONCE', 'new-label'));
  card.append(top, element('h3', vehicle.trim || modelNames[dashboard.config.model]), element('p', [vehicle.paint, vehicle.city].filter(Boolean).join(' · ')), element('div', money(vehicle.price), 'vehicle-price'));
  const meta = element('div', undefined, 'vehicle-meta');
  meta.append(element('span', `${number(vehicle.mileage)} km`, 'muted'), teslaLink(vehicle));
  card.append(meta, element('p', vehicle.vin, 'vehicle-vin'));
  return card;
}
function teslaLink(vehicle) {
  const link = element('a', 'Voir sur Tesla →', 'text-link');
  // Only permit links constructed for Tesla, even if retained data is malformed.
  try { const url = new URL(vehicle.url); if (url.origin === 'https://www.tesla.com') link.href = url.href; } catch (_) {}
  link.target = '_blank'; link.rel = 'noopener noreferrer';
  return link;
}
function eventRow(item) {
  const row = element('article', undefined, 'event-row' + (item.read_at ? '' : ' unread'));
  const content = element('div', undefined, 'event-content');
  content.append(element('h3', `${item.vehicle.year} · ${item.vehicle.trim || 'Tesla'} · ${money(item.vehicle.price)}`), element('p', `${number(item.vehicle.mileage)} km · ${item.vehicle.city || 'France'} · ${item.vin}`));
  row.append(element('span', date(item.created), 'event-time'), content, teslaLink(item.vehicle));
  return row;
}
function fillForm(config) {
  for (const [key, value] of Object.entries(config)) {
    const input = $('search-form').elements.namedItem(key);
    if (input) input.value = Array.isArray(value) ? value.join(', ') : value;
  }
}
$('search-form').addEventListener('input', () => { formDirty = true; $('search-feedback').textContent = ''; });
$('search-form').addEventListener('submit', async event => {
  event.preventDefault();
  const form = new FormData(event.target), config = {};
  const stringKeys = ['model','condition','zip'];
  const listKeys = ['years','categories','paints'];
  for (const [key, value] of form.entries()) {
    if (listKeys.includes(key)) config[key] = String(value).split(',').map(item => item.trim()).filter(Boolean).map(item => key === 'years' ? Number(item) : item);
    else config[key] = stringKeys.includes(key) ? String(value).trim() : Number(value);
  }
  const submit = event.target.querySelector('[type=submit]');
  submit.disabled = true;
  try {
    const result = await api('config','PUT',config);
    formDirty = false;
    $('search-feedback').textContent = result.baseline_reset ? 'Recherche enregistrée. Une référence sera créée au prochain contrôle.' : 'Recherche enregistrée.';
    await refresh(); toast('Vos critères sont enregistrés.');
  } catch (error) { toast(error.message, true); $('search-feedback').textContent = error.message; }
  finally { submit.disabled = false; }
});
$('toggle-monitor').addEventListener('click', async () => {
  $('toggle-monitor').disabled = true;
  try { await api('enabled','POST',{enabled:!dashboard.enabled}); await refresh(); }
  catch (error) { toast(error.message, true); }
  finally { $('toggle-monitor').disabled = false; }
});
$('check-now').addEventListener('click', async () => {
  $('check-now').disabled = true;
  try { await api('check','POST'); toast('Contrôle lancé. Le résultat s’affichera automatiquement.'); await refresh(); }
  catch (error) { toast(error.message, true); await refresh(); }
});
$('mark-read').addEventListener('click', async () => {
  try { await api('events/read','POST'); await refresh(); toast('Les annonces sont marquées comme lues.'); } catch (error) { toast(error.message, true); }
});
$('browser-notifications').addEventListener('click', async () => {
  if (!('Notification' in window) || !window.isSecureContext) { toast('Les notifications nécessitent HTTPS ou une connexion sur localhost.', true); return; }
  const permission = await Notification.requestPermission();
  localStorage.setItem('browser-alerts', permission === 'granted' ? 'yes' : 'no');
  $('notification-permission').textContent = permission === 'granted' ? 'Notifications activées pour ce navigateur, lorsque la page est ouverte.' : 'Notifications non autorisées. Les annonces restent visibles dans l’historique.';
});
$('import-button').addEventListener('click', async () => {
  $('import-button').disabled = true;
  try {
    const data = JSON.parse($('import-json').value);
    const result = await api('import','POST',{data});
    $('import-feedback').textContent = `${result.count} véhicule(s) importé(s), ${result.new} nouvelle(s) annonce(s).`;
    $('import-json').value = ''; await refresh(); toast('Le résultat manuel est enregistré.');
  } catch (error) { $('import-feedback').textContent = error instanceof SyntaxError ? 'Le contenu n’est pas un JSON valide.' : error.message; }
  finally { $('import-button').disabled = false; }
});
boot();
