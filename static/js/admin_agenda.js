(() => {
  const tableBody = document.getElementById('agenda-table-body');
  const paginationEl = document.getElementById('agenda-pagination');
  const loadingOverlay = document.getElementById('agenda-loading');
  const searchInput = document.getElementById('agendaSearch');
  const toggleViewBtn = document.getElementById('btnToggleView');
  const toggleWeekBtn = document.getElementById('btnToggleWeek');
  const listView = document.getElementById('agendaListView');
  const calendarView = document.getElementById('agendaCalendarView');
  const calendarEl = document.getElementById('agendaCalendar');
  const jumpForm = document.getElementById('agenda-page-jump');
  const jumpInput = document.getElementById('agenda-page-input');
  
  let calendar;
  let currentData = { items: [], pagination: {} };
  let showWeekOnly = false;
  let currentSearch = '';
  const entryMap = new Map();
  let targetEntryId = null;
  const urlParams = new URLSearchParams(window.location.search);
  const initialSearch = (urlParams.get('search') || '').trim();
  const initialEntryId = urlParams.get('agenda_id');
  if (initialEntryId) {
    const parsedId = parseInt(initialEntryId, 10);
    if (!Number.isNaN(parsedId)) {
      targetEntryId = String(parsedId);
    }
  }
  if (initialSearch) {
    currentSearch = initialSearch;
    if (searchInput) searchInput.value = initialSearch;
  }

  async function loadAgenda(page = 1) {
    if (loadingOverlay) loadingOverlay.classList.remove('d-none');
    
    const params = new URLSearchParams();
    params.set('page', page);
    if (currentSearch) params.set('search', currentSearch);
    
    try {
      const response = await fetch(`${API_AGENDA}?${params.toString()}`);
      const data = await response.json();
      currentData = data;
      
      renderTable(data.items);
      renderPagination(data.pagination);
      if (calendar) refreshCalendar(data.items);
      if (targetEntryId && entryMap.has(targetEntryId)) {
        openEditModal(entryMap.get(targetEntryId));
        targetEntryId = null;
      }
      
    } catch (error) {
      console.error('Erro ao carregar agenda:', error);
      if (tableBody) tableBody.innerHTML = '<tr><td colspan="6" class="text-center text-danger py-4">Erro ao carregar dados.</td></tr>';
    } finally {
      if (loadingOverlay) loadingOverlay.classList.add('d-none');
    }
  }
  if (typeof window !== 'undefined') {
    window.loadAgenda = loadAgenda;
  }

  function renderTable(items) {
    if (!tableBody) return;
    entryMap.clear();
    
    if (!items || items.length === 0) {
      tableBody.innerHTML = '<tr><td colspan="6" class="text-center py-4 text-muted">Nenhum agendamento encontrado.</td></tr>';
      return;
    }

    tableBody.innerHTML = items.map(item => {
      const dateFormatted = item.data_atendimento ? new Date(item.data_atendimento + 'T00:00:00').toLocaleDateString('pt-BR') : '-';
      entryMap.set(String(item.id), item);
      return `
        <tr data-entry-id="${item.id}">
          <td class="fw-semibold">${item.tecnico}</td>
          <td>${item.unidade}</td>
          <td>${dateFormatted}</td>
          <td>${item.periodo}</td>
          <td class="text-muted">${item.obs || ''}</td>
          <td class="text-end agenda-actions">
            <div class="btn-group btn-group-sm">
              <button type="button" class="btn btn-outline-primary" onclick='openEditModal(${JSON.stringify(item).replace(/'/g, "&apos;")})'>
                <i class="bi bi-pencil"></i>
              </button>
              <form method="post" action="${item.delete_url}" onsubmit="return confirm('Remover este agendamento?');" style="display:inline;">
                <input type="hidden" name="csrf_token" value="${CSRF_TOKEN}">
                <button type="submit" class="btn btn-outline-danger"><i class="bi bi-trash"></i></button>
              </form>
            </div>
          </td>
        </tr>
      `;
    }).join('');
  }

  function renderPagination(p) {
    if (!paginationEl || p.pages <= 1) {
      if (paginationEl) paginationEl.innerHTML = '';
      if (jumpForm) jumpForm.classList.add('d-none');
      return;
    }

    const pages = buildPageList(p.page, p.pages);
    let html = `
      <li class="page-item ${!p.has_prev ? 'disabled' : ''}">
        <a class="page-link" href="#" data-page="${p.prev_num || 1}">Anterior</a>
      </li>
    `;
    pages.forEach(pageNum => {
      html += `
        <li class="page-item ${pageNum === p.page ? 'active' : ''}">
          <a class="page-link" href="#" data-page="${pageNum}">${pageNum}</a>
        </li>
      `;
    });
    html += `
      <li class="page-item ${!p.has_next ? 'disabled' : ''}">
        <a class="page-link" href="#" data-page="${p.next_num || p.pages}">Proxima</a>
      </li>
    `;
    paginationEl.innerHTML = html;
    paginationEl.querySelectorAll('a[data-page]').forEach(link => {
      link.addEventListener('click', (event) => {
        event.preventDefault();
        if (link.closest('.disabled')) return;
        const page = parseInt(link.dataset.page, 10);
        if (!Number.isNaN(page)) loadAgenda(page);
      });
    });
    if (jumpForm && jumpInput) {
      jumpForm.classList.remove('d-none');
      jumpInput.max = p.pages;
      jumpInput.value = p.page;
    }
  }

  function buildPageList(current, total) {
    const pages = [];
    const candidates = [1, current, current + 1, current + 2, current + 3, total];
    candidates.forEach(page => {
      if (page >= 1 && page <= total && !pages.includes(page)) {
        pages.push(page);
      }
    });
    return pages;
  }

  function refreshCalendar(items) {
    const events = items.map(item => ({
      id: item.id,
      title: `${item.tecnico} (${item.periodo})`,
      start: item.data_atendimento,
      allDay: true,
      extendedProps: item
    }));
    calendar.removeAllEvents();
    calendar.addEventSource(events);
  }

  window.openEditModal = function(item) {
    const form = document.getElementById('formEditarAgenda');
    const modalEl = document.getElementById('modalEditarAgenda');
    
    form.action = item.update_url;
    document.getElementById('edit-usuario-id').value = item.usuario_id;
    document.getElementById('edit-data').value = item.data_atendimento;
    document.getElementById('edit-periodo').value = item.periodo;
    document.getElementById('editAgendaUnit').value = item.unidade;
    document.getElementById('edit-obs').value = item.obs || '';
    
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
  };

  if (searchInput) {
    let timeout;
    searchInput.addEventListener('input', (e) => {
      clearTimeout(timeout);
      timeout = setTimeout(() => {
        currentSearch = e.target.value;
        loadAgenda(1);
      }, 500);
    });
  }

  if (toggleWeekBtn) {
    toggleWeekBtn.addEventListener('click', () => {
      showWeekOnly = !showWeekOnly;
      toggleWeekBtn.textContent = showWeekOnly ? 'Mostrar todos' : 'Mostrar semana atual';
      loadAgenda(1);
    });
  }

  if (toggleViewBtn && listView && calendarView) {
    toggleViewBtn.addEventListener('click', () => {
      const isList = !listView.classList.contains('d-none');
      if (isList) {
        listView.classList.add('d-none');
        calendarView.classList.remove('d-none');
        toggleViewBtn.textContent = 'Ver lista';
        if (!calendar && window.FullCalendar) {
          calendar = new FullCalendar.Calendar(calendarEl, {
            initialView: 'dayGridMonth',
            locale: 'pt-br',
            height: 'auto',
            events: [],
            eventClick: (info) => openEditModal(info.event.extendedProps)
          });
          calendar.render();
          refreshCalendar(currentData.items);
        }
      } else {
        calendarView.classList.add('d-none');
        listView.classList.remove('d-none');
        toggleViewBtn.textContent = 'Ver calendário';
      }
    });
  }

  if (jumpForm && jumpInput) {
    jumpForm.addEventListener('submit', (event) => {
      event.preventDefault();
      const page = parseInt(jumpInput.value, 10);
      if (!Number.isNaN(page)) loadAgenda(page);
    });
  }

  if (tableBody) {
    tableBody.addEventListener('click', (event) => {
      if (event.target.closest('a, button, input, select, textarea, form, .btn, .btn-group, .agenda-actions')) return;
      const row = event.target.closest('tr[data-entry-id]');
      if (!row) return;
      const entry = entryMap.get(row.getAttribute('data-entry-id'));
      if (!entry) return;
      openEditModal(entry);
    });
  }

  document.addEventListener('DOMContentLoaded', () => loadAgenda(1));
})();
