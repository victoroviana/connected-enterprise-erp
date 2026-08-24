/**
 * static/js/audit_diff.js
 * Specialized logic for rendering audit log differences.
 */
(() => {
  const MAX_DIFF_ITEMS = 40;

  const extractData = (selector, kind) => {
    if (!selector) {
      return { text: 'Sem dados disponveis.', json: null, hasData: false };
    }
    const source = typeof selector === 'string' ? document.querySelector(selector) : selector;
    if (!source) {
      return { text: 'Sem dados disponveis.', json: null, hasData: false };
    }
    const raw = source.textContent || source.dataset?.json || '';
    if (kind === 'payload') {
      try {
        const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw;
        return { text: JSON.stringify(parsed, null, 2), json: parsed, hasData: true };
      } catch (err) {
        console.warn('Falha ao converter JSON da auditoria:', err);
        return { text: String(raw) || '(falha ao interpretar JSON)', json: null, hasData: Boolean(raw) };
      }
    }
    return { text: String(raw) || '(vazio)', json: null, hasData: Boolean(raw) };
  };

  const flattenValue = (value, prefix = '', acc = new Map()) => {
    if (Array.isArray(value)) {
      if (!value.length) { acc.set(prefix || '[root]', '[]'); return acc; }
      value.forEach((item, index) => {
        const nextKey = prefix ? `${prefix}[${index}]` : `[${index}]`;
        flattenValue(item, nextKey, acc);
      });
      return acc;
    }
    if (value && typeof value === 'object') {
      const entries = Object.entries(value);
      if (!entries.length) { acc.set(prefix || '[root]', '{}'); return acc; }
      entries.forEach(([childKey, childValue]) => {
        const nextKey = prefix ? `${prefix}.${childKey}` : childKey;
        flattenValue(childValue, nextKey, acc);
      });
      return acc;
    }
    acc.set(prefix || '[root]', value === null ? 'null' : String(value));
    return acc;
  };

  const buildDiff = (beforeJson, afterJson) => {
    const beforeMap = flattenValue(beforeJson, '', new Map());
    const afterMap = flattenValue(afterJson, '', new Map());
    const keys = new Set([...beforeMap.keys(), ...afterMap.keys()]);
    const rows = [];
    [...keys].sort().forEach((key) => {
      const prev = beforeMap.has(key) ? beforeMap.get(key) : null;
      const next = afterMap.has(key) ? afterMap.get(key) : null;
      if (prev === next) return;
      let status;
      if (prev === null) status = 'added';
      else if (next === null) status = 'removed';
      else status = 'changed';
      rows.push({ key, prev, next, status });
    });
    return rows;
  };

  const escapeHtml = (value) => String(value).replace(/[&<>\"']/g, (char) => {
    switch (char) {
      case '&': return '&amp;';
      case '<': return '&lt;';
      case '>': return '&gt;';
      case '"': return '&quot;';
      case "'": return '&#39;';
      default: return char;
    }
  });

  const formatDiffValue = (value) => {
    if (value === null || value === undefined || value === '') {
      return '&mdash;';
    }
    const str = String(value);
    const truncated = str.length > 160 ? `${str.slice(0, 157)}...` : str;
    return escapeHtml(truncated);
  };

  const renderDiff = (beforeData, afterData, ui) => {
    if (!ui.diffSummary || !ui.diffListEl || !ui.diffCountEl || !ui.diffEmptyEl) return;
    ui.diffSummary.classList.remove('d-none');
    const canCompare = beforeData.json && afterData.json;
    if (!canCompare) {
      ui.diffListEl.innerHTML = '';
      ui.diffCountEl.textContent = '';
      ui.diffEmptyEl.textContent = 'Diferenças disponveis apenas para dados estruturados.';
      ui.diffEmptyEl.classList.remove('d-none');
      return;
    }
    const diffItems = buildDiff(beforeData.json, afterData.json);
    const countLabel = diffItems.length === 1 ? 'alteração' : 'alterações';
    ui.diffCountEl.textContent = `${diffItems.length} ${countLabel}`;
    if (!diffItems.length) {
      ui.diffListEl.innerHTML = '';
      ui.diffEmptyEl.textContent = 'Nenhuma alteração detectada.';
      ui.diffEmptyEl.classList.remove('d-none');
      return;
    }
    ui.diffEmptyEl.classList.add('d-none');
    const badgeMap = {
      added: { label: 'novo', cls: 'text-bg-success' },
      removed: { label: 'removido', cls: 'text-bg-danger' },
      changed: { label: 'alterado', cls: 'text-bg-warning' }
    };
    const limited = diffItems.slice(0, MAX_DIFF_ITEMS);
    ui.diffListEl.innerHTML = limited.map((item) => {
      const meta = badgeMap[item.status] || badgeMap.changed;
      let valuesHtml = '';
      if (item.status === 'added') {
        valuesHtml = `<span>valor <code>${formatDiffValue(item.next)}</code></span>`;
      } else if (item.status === 'removed') {
        valuesHtml = `<span>valor <code>${formatDiffValue(item.prev)}</code></span>`;
      } else {
        valuesHtml = `<span class="text-muted">de <code>${formatDiffValue(item.prev)}</code></span><span>para <code>${formatDiffValue(item.next)}</code></span>`;
      }
      return `<li class="audit-diff-item is-${item.status}"><span class="badge ${meta.cls} audit-diff-item__badge">${meta.label}</span><span class="audit-diff-item__key">${escapeHtml(item.key)}</span><span class="audit-diff-item__values">${valuesHtml}</span></li>`;
    }).join('');
    if (diffItems.length > MAX_DIFF_ITEMS) {
      ui.diffListEl.innerHTML += `<li class="audit-diff-item"><span class="text-muted">+${diffItems.length - MAX_DIFF_ITEMS} alterações adicionais</span></li>`;
    }
  };

  const TRANSLATIONS = {
    created_at: "Data de Criação",
    created_by: "Criado por",
    id: "ID",
    itens: "Itens",
    description: "Descrição",
    discount_percent: "Desconto (%)",
    equipment_id: "Equipamento",
    image: "Imagem",
    key: "Identificador/Chave",
    quantity: "Quantidade",
    total_price: "Preço Total",
    unit_price: "Preço Unitário",
    snapshot: "Dados do Registro",
    aceite: "Aceite/Termos",
    client_name: "Nome do Cliente",
    cnpj: "CNPJ",
    condicoes: "Condições de Pagamento",
    status: "Status/Situação",
    name: "Nome",
    email: "E-mail",
    updated_at: "Última Atualização",
    active: "Ativo",
    role: "Função/Perfil",
    permissions: "Permissões",
    department: "Departamento",
    value: "Valor",
    observation: "Observações",
    title: "Título",
    subject: "Assunto",
    message: "Mensagem",
    phone: "Telefone"
  };

  const isPriceKey = (key) => {
    const k = key.toLowerCase();
    return k.includes('price') || k.includes('preco') || k.includes('valor') || k === 'total' || k === 'subtotal';
  };

  const formatJsonValueOnly = (val) => {
    if (val === null || val === undefined) return `<span class="text-muted">&mdash;</span>`;
    if (typeof val === 'boolean') {
      return val ? `<span class="badge bg-success-subtle text-success border border-success-subtle">Sim</span>` : `<span class="badge bg-danger-subtle text-danger border border-danger-subtle">Não</span>` ;
    }
    if (typeof val === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(val)) {
      try {
        const d = new Date(val);
        if (!isNaN(d.getTime())) {
          return d.toLocaleString('pt-BR');
        }
      } catch (e) {}
    }
    return escapeHtml(val);
  };

  const formatJsonToHtml = (obj, path = '', diffMap = {}) => {
    if (obj === null || obj === undefined) return `<span class="text-muted">&mdash;</span>`;
    if (typeof obj !== 'object') {
      return formatJsonValueOnly(obj);
    }

    if (Array.isArray(obj)) {
      if (obj.length === 0) return `<span class="text-muted">Vazio</span>`;
      const isPrimitiveArray = obj.every(x => typeof x !== 'object' || x === null);
      if (isPrimitiveArray) {
        return `<div class="d-flex flex-wrap gap-1 mt-1">` + 
          obj.map((x, idx) => {
            const currentPath = path ? `${path}[${idx}]` : `[${idx}]`;
            const status = diffMap[currentPath];
            let borderClass = 'border-light-subtle bg-light text-secondary';
            if (status === 'added') borderClass = 'border-success bg-success-subtle text-success';
            else if (status === 'removed') borderClass = 'border-danger bg-danger-subtle text-danger';
            else if (status === 'changed') borderClass = 'border-warning bg-warning-subtle text-warning';
            return `<span class="badge border ${borderClass} px-2 py-1.5 font-weight-normal text-start text-wrap d-inline-block">${formatJsonValueOnly(x)}</span>`;
          }).join('') + `</div>`;
      }
      
      const isKeyValuePairArray = obj.every(x => Array.isArray(x) && x.length === 2 && typeof x[0] === 'string');
      if (isKeyValuePairArray) {
        return `
          <table class="audit-friendly-table">
            <tbody>
              ${obj.map(([k, v], idx) => {
                const currentPath = path ? `${path}[${idx}][1]` : `[${idx}][1]`;
                const status = diffMap[currentPath];
                const highlightClass = status === 'added' ? 'audit-row-added' : 
                                     status === 'removed' ? 'audit-row-removed' : 
                                     status === 'changed' ? 'audit-row-changed' : '';
                return `
                  <tr class="${highlightClass}">
                    <td class="audit-friendly-label">${escapeHtml(k)}</td>
                    <td class="audit-friendly-value">${formatJsonToHtml(v, currentPath, diffMap)}</td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        `;
      }

      return `<div class="d-flex flex-column gap-2 mt-1">` + obj.map((x, idx) => {
        const currentPath = path ? `${path}[${idx}]` : `[${idx}]`;
        const hasChangeInItem = Object.keys(diffMap).some(k => k.startsWith(currentPath));
        const cardBorderClass = hasChangeInItem ? 'border-warning shadow-sm' : 'border-light shadow-sm';
        return `
          <div class="audit-friendly-card ${cardBorderClass}">
            <div class="audit-friendly-card-header">
              <span>Item #${idx + 1}</span>
              ${hasChangeInItem ? `<span class="badge text-bg-warning px-2 py-1 font-weight-normal" style="font-size:0.7rem;"><i class="bi bi-pencil-square me-1"></i>Alterado</span>` : ''}
            </div>
            <div class="audit-friendly-card-body">
              ${formatJsonToHtml(x, currentPath, diffMap)}
            </div>
          </div>
        `;
      }).join('') + `</div>`;
    }

    const entries = Object.entries(obj);
    if (entries.length === 0) return `<span class="text-muted">Vazio</span>`;

    const primitives = [];
    const complex = [];
    entries.forEach(([key, val]) => {
      const isComplex = val !== null && typeof val === 'object';
      if (isComplex) {
        complex.push([key, val]);
      } else {
        primitives.push([key, val]);
      }
    });

    let html = '';
    
    if (primitives.length > 0) {
      html += `
        <table class="audit-friendly-table">
          <tbody>
            ${primitives.map(([key, val]) => {
              const currentPath = path ? `${path}.${key}` : key;
              const status = diffMap[currentPath];
              const highlightClass = status === 'added' ? 'audit-row-added' : 
                                   status === 'removed' ? 'audit-row-removed' : 
                                   status === 'changed' ? 'audit-row-changed' : '';
              
              const label = TRANSLATIONS[key] || key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
              
              let badgeHtml = '';
              if (status === 'added') {
                badgeHtml = `<span class="badge text-bg-success ms-2 font-weight-normal" style="font-size: 0.7rem;"><i class="bi bi-plus-lg me-1"></i>Novo</span>`;
              } else if (status === 'removed') {
                badgeHtml = `<span class="badge text-bg-danger ms-2 font-weight-normal" style="font-size: 0.7rem;"><i class="bi bi-trash me-1"></i>Removido</span>`;
              } else if (status === 'changed') {
                badgeHtml = `<span class="badge text-bg-warning ms-2 font-weight-normal" style="font-size: 0.7rem;"><i class="bi bi-pencil me-1"></i>Alterado</span>`;
              }

              let formattedVal = '';
              if (isPriceKey(key) && typeof val === 'number') {
                formattedVal = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(val);
              } else if (key === 'discount_percent' && typeof val === 'number') {
                formattedVal = val + '%';
              } else {
                formattedVal = formatJsonValueOnly(val);
              }

              return `
                <tr class="${highlightClass}">
                  <td class="audit-friendly-label">${escapeHtml(label)}${badgeHtml}</td>
                  <td class="audit-friendly-value">${formattedVal}</td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      `;
    }

    if (complex.length > 0) {
      html += complex.map(([key, val]) => {
        const currentPath = path ? `${path}.${key}` : key;
        const hasChangeInComplex = Object.keys(diffMap).some(k => k.startsWith(currentPath));
        const label = TRANSLATIONS[key] || key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        const cardBorderClass = hasChangeInComplex ? 'border-warning shadow-sm' : 'border-light shadow-sm';
        return `
          <div class="audit-friendly-card mt-2 ${cardBorderClass}">
            <div class="audit-friendly-card-header">
              <span>${escapeHtml(label)}</span>
              ${hasChangeInComplex ? `<span class="badge text-bg-warning px-2 py-1 font-weight-normal" style="font-size: 0.7rem;"><i class="bi bi-pencil-square me-1"></i>Alterado</span>` : ''}
            </div>
            <div class="audit-friendly-card-body">
              ${formatJsonToHtml(val, currentPath, diffMap)}
            </div>
          </div>
        `;
      }).join('');
    }

    return html;
  };

  const setFocusBlock = (target, blocks) => {
    if (!blocks.before || !blocks.after) return;
    blocks.before.classList.toggle('is-focused', target === 'before');
    blocks.after.classList.toggle('is-focused', target === 'after');
  };

  window.AuditDiff = {
    extractData,
    renderDiff,
    setFocusBlock,
    formatJsonToHtml,
    buildDiff
  };
})();
