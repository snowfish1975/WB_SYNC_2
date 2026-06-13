/* ============================================================
   CORE.JS — глобальное состояние, утилиты, фильтр кабинета
   Загружается первым на всех страницах.
   ============================================================ */

// ---- ГЛОБАЛЬНОЕ СОСТОЯНИЕ ----
window.WB = {
  period:  40,        // текущий период в днях
  cabinet: '',        // '' = все кабинеты, иначе cabinet_id
  cabinetName: '',    // отображаемое имя выбранного кабинета
  cabinets: [],       // [{cabinet_id, seller_name}, ...]
  theme: localStorage.getItem('wb_theme') || 'dark',
};

// ---- УТИЛИТЫ ----
window.fmt = function(n) {
  if (n == null) return '—';
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(n);
};

window.fmtMoney = function(n) {
  if (n == null) return '—';
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(n) + ' ₽';
};

window.fmtDate = function(s) {
  if (!s) return '—';
  const d = new Date(s);
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' }) + ' ' +
         d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
};

window.loaderHTML = function(msg) {
  return `<div class="loader">
    <div class="loader-dot"></div>
    <div class="loader-dot"></div>
    <div class="loader-dot"></div>
    ${msg ? `<span style="margin-left:8px">${msg}</span>` : ''}
  </div>`;
};

// ---- ПАГИНАЦИЯ ----
window.renderPagination = function(containerId, total, perPage, currentPage, onPage) {
  const totalPages = Math.ceil(total / perPage);
  const el = document.getElementById(containerId);
  if (!el) return;
  if (totalPages <= 1) { el.innerHTML = ''; return; }

  let html = `<span class="page-info">${(currentPage-1)*perPage+1}–${Math.min(currentPage*perPage,total)} из ${fmt(total)}</span>`;

  const pages = new Set([1, totalPages]);
  for (let p = currentPage - 2; p <= currentPage + 2; p++) if (p > 1 && p < totalPages) pages.add(p);
  const uniq = [...pages].sort((a,b) => a-b);

  if (currentPage > 1) html += `<button class="page-btn" onclick="(${onPage})(${currentPage-1})">←</button>`;
  let prev = 0;
  for (const p of uniq) {
    if (p - prev > 1) html += `<span class="page-info">…</span>`;
    html += `<button class="page-btn ${p === currentPage ? 'active' : ''}" onclick="(${onPage})(${p})">${p}</button>`;
    prev = p;
  }
  if (currentPage < totalPages) html += `<button class="page-btn" onclick="(${onPage})(${currentPage+1})">→</button>`;
  el.innerHTML = html;
};

// ---- ТЕМА ----
window.applyTheme = function(theme) {
  WB.theme = theme;
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('wb_theme', theme);
  document.querySelectorAll('.theme-dot').forEach(d => {
    d.classList.toggle('active', d.dataset.t === theme);
  });
};

// ---- ПЕРИОД ----
window.setPeriod = function(days, btn) {
  WB.period = days;
  document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  window.dispatchEvent(new CustomEvent('wb:period-changed', { detail: days }));
};

// ---- КАБИНЕТ ----
window.setCabinet = function(cabinet_id) {
  WB.cabinet = cabinet_id;
  const found = WB.cabinets.find(c => c.cabinet_id === cabinet_id);
  WB.cabinetName = found ? found.seller_name : '';
  // Синхронизируем все селекторы кабинета на странице
  document.querySelectorAll('.global-cab-select').forEach(sel => { sel.value = cabinet_id; });
  window.dispatchEvent(new CustomEvent('wb:cabinet-changed', { detail: cabinet_id }));
};

// ---- ЗАПОЛНЕНИЕ СЕЛЕКТОРОВ КАБИНЕТА ----
window.populateGlobalCabSelects = function(data) {
  // Собираем уникальные кабинеты из любого массива данных с полем seller_name/cabinet_id
  const seen = new Set();
  const cabs = [];
  for (const r of data) {
    const id = r.cabinet_id || '';
    const name = r.seller_name || id.slice(0,8);
    if (id && !seen.has(id)) { seen.add(id); cabs.push({ cabinet_id: id, seller_name: name }); }
  }
  if (cabs.length) {
    WB.cabinets = cabs;
    document.querySelectorAll('.global-cab-select').forEach(sel => {
      const cur = sel.value;
      sel.innerHTML = '<option value="">Все кабинеты</option>';
      for (const c of cabs) {
        sel.innerHTML += `<option value="${c.cabinet_id}" ${cur === c.cabinet_id ? 'selected' : ''}>${c.seller_name}</option>`;
      }
    });
  }
};

// ---- ПОСЛЕДНЯЯ СИНХРОНИЗАЦИЯ ----
window.loadLastSync = async function() {
  try {
    const res = await fetch('/api/logs');
    const logs = await res.json();
    if (logs.length) {
      const d = new Date(logs[0].created_at);
      const el = document.getElementById('lastSync');
      if (el) el.textContent = 'синхр: ' + d.toLocaleString('ru-RU', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' });
    }
  } catch(e) {}
};

// ---- РУЧНАЯ СИНХРОНИЗАЦИЯ ----
window.triggerSync = async function() {
  const btn = document.querySelector('.sync-btn');
  if (!btn) return;
  btn.textContent = '⟳ ЗАПУСК...';
  btn.disabled = true;
  try {
    await fetch('/api/sync/trigger', { method: 'POST' });
    btn.textContent = '✓ ЗАПУЩЕНО';
  } catch(e) {
    btn.textContent = '✗ ОШИБКА';
  }
  setTimeout(() => { btn.textContent = '⟳ СИНХР'; btn.disabled = false; }, 3000);
};

// ---- ИНИЦИАЛИЗАЦИЯ ----
document.addEventListener('DOMContentLoaded', () => {
  applyTheme(WB.theme);
  loadCabinets();
});

// ---- ЗАГРУЗКА СПИСКА КАБИНЕТОВ ----
async function loadCabinets() {
  try {
    const res = await fetch('/api/dashboard/cabinets');
    const cabs = await res.json();
    if (cabs.length) {
      WB.cabinets = cabs;
      document.querySelectorAll('.global-cab-select').forEach(sel => {
        sel.innerHTML = '<option value="">Все кабинеты</option>';
        for (const c of cabs) {
          sel.innerHTML += `<option value="${c.cabinet_id}">${c.seller_name}</option>`;
        }
      });
      // Автоматически выбираем первый кабинет
      setCabinet(cabs[0].cabinet_id);
    }
  } catch(e) {}
}