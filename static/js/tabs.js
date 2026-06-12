/* ============================================================
   TABS.JS — логика вкладок и динамической подгрузки
   ============================================================ */

const TAB_SRCS = {
  summary:      '/static/tabs/summary.html',
  orders:       '/static/tabs/orders.html',
  stocks:       '/static/tabs/stocks.html',
  top:          '/static/tabs/top-products.html',
  report:       '/static/tabs/sales-report.html',
};

const loadedTabs = new Set();

async function loadTab(name) {
  if (loadedTabs.has(name)) return;
  const container = document.getElementById(`tab-${name}`);
  if (!container) return;

  container.innerHTML = loaderHTML('Загрузка...');
  try {
    const res = await fetch(TAB_SRCS[name]);
    const html = await res.text();
    container.innerHTML = html;

    // Выполняем inline-скрипты из загруженного фрагмента
    container.querySelectorAll('script').forEach(oldScript => {
      const s = document.createElement('script');
      if (oldScript.src) { s.src = oldScript.src; }
      else { s.textContent = oldScript.textContent; }
      document.body.appendChild(s);
      oldScript.remove();
    });

    loadedTabs.add(name);

    // Сообщаем табу что он загружен и активен
    window.dispatchEvent(new CustomEvent(`wb:tab-loaded:${name}`));
    window.dispatchEvent(new CustomEvent(`wb:tab-activated:${name}`));
  } catch(e) {
    container.innerHTML = `<div style="color:var(--red);padding:30px;font-family:'IBM Plex Mono',monospace;font-size:12px;">Ошибка загрузки таба: ${e.message}</div>`;
  }
}

function activateTab(name) {
  // Скрываем все табы
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));

  // Показываем нужный
  const content = document.getElementById(`tab-${name}`);
  const btn = document.querySelector(`.tab-btn[data-tab="${name}"]`);
  if (content) content.classList.add('active');
  if (btn) btn.classList.add('active');

  // Сохраняем активный таб
  localStorage.setItem('wb_active_tab', name);

  // Загружаем если ещё не загружен, иначе просто уведомляем
  if (!loadedTabs.has(name)) {
    loadTab(name);
  } else {
    window.dispatchEvent(new CustomEvent(`wb:tab-activated:${name}`));
  }
}

// Глобальная функция для вызова из HTML
window.switchTab = activateTab;

document.addEventListener('DOMContentLoaded', () => {
  // При смене периода — уведомляем активный таб
  window.addEventListener('wb:period-changed', () => {
    const active = localStorage.getItem('wb_active_tab') || 'summary';
    if (loadedTabs.has(active)) {
      window.dispatchEvent(new CustomEvent(`wb:tab-activated:${active}`));
    }
  });

  // При смене кабинета — уведомляем активный таб
  window.addEventListener('wb:cabinet-changed', () => {
    const active = localStorage.getItem('wb_active_tab') || 'summary';
    if (loadedTabs.has(active)) {
      window.dispatchEvent(new CustomEvent(`wb:tab-activated:${active}`));
    }
  });

  // Восстанавливаем последний активный таб
  const saved = localStorage.getItem('wb_active_tab') || 'summary';
  activateTab(saved);
});