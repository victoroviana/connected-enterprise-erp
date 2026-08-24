*** Begin Patch
*** Update File: templates/historico_propostas.html
@@
-            <a href="{{ url_for('propostas_bp.download_proposta', id=proposta.id) }}"
-               class="btn btn-success btn-sm text-white px-3"
-               style="min-width:60px;height:45px;">PDF</a>
+            <button type="button"
+                    class="btn btn-success btn-sm text-white px-3 js-history-pdf"
+                    style="min-width:60px;height:45px;"
+                    data-proposal-id="{{ proposta.id }}"
+                    data-proposal-name="{{ proposta.filename or proposta.client_name or 'Proposta' }}">
+              <span class="spinner-border spinner-border-sm me-2 d-none js-loading" role="status" aria-hidden="true"></span>
+              <span class="js-label">PDF</span>
+            </button>
*** End Patch
