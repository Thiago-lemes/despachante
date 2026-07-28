(() => {
  const sidebar = document.querySelector('[data-sidebar]');
  const overlay = document.querySelector('[data-sidebar-overlay]');
  const toggle = document.querySelector('[data-sidebar-toggle]');
  const closeSidebar = () => {
    sidebar?.classList.remove('is-open');
    overlay?.classList.remove('is-open');
  };
  toggle?.addEventListener('click', () => {
    sidebar?.classList.add('is-open');
    overlay?.classList.add('is-open');
  });
  overlay?.addEventListener('click', closeSidebar);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeSidebar();
  });

  const input = document.querySelector('[data-file-input]');
  const dropzone = document.querySelector('[data-dropzone]');
  const list = document.querySelector('[data-file-list]');
  const summary = document.querySelector('[data-file-summary]');
  const modeInputs = document.querySelectorAll('input[name="modo"]');
  const modeHint = document.querySelector('[data-mode-hint]');
  const ehLote = () => document.querySelector('input[name="modo"]:checked')?.value === 'lote';
  const definirArquivos = (arquivos) => {
    if (!input) return;
    const dt = new DataTransfer();
    arquivos.forEach((arquivo) => dt.items.add(arquivo));
    input.files = dt.files;
    renderFiles();
  };
  const renderFiles = () => {
    if (!input || !list || !summary) return;
    const files = Array.from(input.files || []);
    list.innerHTML = files.map((file, indice) => `
      <li class="file-row">
        <svg class="h-5 w-5 shrink-0 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/></svg>
        <span class="min-w-0 flex-1">
          <span class="block truncate font-semibold text-slate-700">${file.name.replace(/[&<>"']/g, '')}</span>
          <span class="block text-xs text-slate-400">${(file.size / 1048576).toFixed(1)} MB</span>
        </span>
        <button type="button" class="file-row-remove" data-remove-file="${indice}" title="Remover arquivo" aria-label="Remover arquivo">
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>
        </button>
      </li>`).join('');
    list.classList.toggle('hidden', files.length === 0);
    const size = files.reduce((total, file) => total + file.size, 0) / 1048576;
    summary.textContent = files.length ? `${files.length} arquivo(s) - ${size.toFixed(1)} MB` : 'Nenhum arquivo selecionado';
  };
  input?.addEventListener('change', renderFiles);
  list?.addEventListener('click', (event) => {
    const botao = event.target.closest('[data-remove-file]');
    if (!botao || !input) return;
    const indice = Number(botao.dataset.removeFile);
    definirArquivos(Array.from(input.files || []).filter((_, i) => i !== indice));
  });
  dropzone?.addEventListener('dragover', (event) => { event.preventDefault(); dropzone.classList.add('is-dragging'); });
  dropzone?.addEventListener('dragleave', () => dropzone.classList.remove('is-dragging'));
  dropzone?.addEventListener('drop', (event) => {
    event.preventDefault();
    dropzone.classList.remove('is-dragging');
    const soltos = Array.from(event.dataTransfer?.files || []).filter((f) => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'));
    if (!soltos.length) return;
    const existentes = ehLote() ? Array.from(input?.files || []) : [];
    definirArquivos([...existentes, ...soltos]);
  });
  modeInputs.forEach((radio) => radio.addEventListener('change', () => {
    const lote = ehLote();
    if (input) input.toggleAttribute('multiple', lote);
    if (modeHint) modeHint.textContent = lote ? 'Até 20 PDFs por envio.' : 'Um PDF por envio.';
    if (!lote && input?.files.length > 1) definirArquivos(Array.from(input.files).slice(0, 1));
    renderFiles();
  }));
  document.querySelector('input[name="modo"]:checked')?.dispatchEvent(new Event('change'));

  const uploadForm = document.querySelector('[data-upload-form]');
  uploadForm?.addEventListener('submit', () => {
    const botao = uploadForm.querySelector('[data-submit-button]');
    if (!botao || botao.disabled) return;
    botao.disabled = true;
    botao.querySelector('[data-submit-icon]')?.classList.add('animate-spin');
    const rotulo = botao.querySelector('[data-submit-label]');
    if (rotulo) rotulo.textContent = 'Processando...';
  });

  const confirmDialog = document.querySelector('[data-confirm-dialog]');
  if (confirmDialog) {
    const mensagemEl = confirmDialog.querySelector('[data-confirm-message]');
    const aceitarBtn = confirmDialog.querySelector('[data-confirm-accept]');
    let pendingForm = null;
    document.addEventListener('submit', (event) => {
      const form = event.target.closest('[data-confirm-delete]');
      if (!form) return;
      event.preventDefault();
      pendingForm = form;
      if (mensagemEl) mensagemEl.textContent = form.dataset.confirmMessage || 'Esta ação não pode ser desfeita.';
      confirmDialog.showModal();
    });
    aceitarBtn?.addEventListener('click', () => {
      confirmDialog.close();
      pendingForm?.submit();
      pendingForm = null;
    });
    confirmDialog.addEventListener('close', () => { pendingForm = null; });
  }

  const progress = document.querySelector('[data-progress-url]');
  if (progress && progress.dataset.finished !== 'true') {
    let previous = progress.dataset.snapshot;
    const poll = async () => {
      try {
        const response = await fetch(progress.dataset.progressUrl, {headers: {'X-Requested-With': 'XMLHttpRequest'}});
        if (!response.ok) return;
        const data = await response.json();
        const snapshot = [data.resumo.aguardando, data.resumo.processando, data.resumo.concluido, data.resumo.erro].join(':');
        if (snapshot !== previous) window.location.reload();
      } catch (_) { /* A proxima consulta tenta novamente. */ }
    };
    window.setInterval(poll, 3000);
  }

  const pendentesLink = document.querySelector('[data-pendentes-url]');
  const pendentesBadge = document.querySelector('[data-pendentes-badge]');
  if (pendentesLink && pendentesBadge) {
    const atualizarPendentes = async () => {
      try {
        const response = await fetch(pendentesLink.dataset.pendentesUrl, {headers: {'X-Requested-With': 'XMLHttpRequest'}});
        if (!response.ok) return;
        const data = await response.json();
        pendentesBadge.textContent = data.total;
        pendentesBadge.classList.toggle('hidden', !data.total);
      } catch (_) { /* A proxima consulta tenta novamente. */ }
    };
    atualizarPendentes();
    window.setInterval(atualizarPendentes, 5000);
  }

  const pendingDoc = document.querySelector('[data-document-pending]');
  if (pendingDoc) {
    window.setInterval(async () => {
      try {
        const response = await fetch(pendingDoc.dataset.documentPending, {headers: {'X-Requested-With': 'XMLHttpRequest'}});
        if (!response.ok) return;
        const data = await response.json();
        if (data.status !== pendingDoc.dataset.documentStatus) window.location.reload();
      } catch (_) { /* A proxima consulta tenta novamente. */ }
    }, 3000);
  }
})();
