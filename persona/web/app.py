from __future__ import annotations

import html
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from persona.core.binding import PRAGMATIC_BINDING_MODE, STRICT_BINDING_MODE
from persona.engine.service import PersonaEngine, segments_to_preview_text
from persona.engine.storage import LocalDocumentStore
from persona.exceptions import PersonaError


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme: light; --bg:#f6f2e8; --panel:#fffaf1; --ink:#1f1a15; --muted:#6d6156; --accent:#9a3412; --line:#e9dcc7; }}
    body {{ margin:0; font-family: Georgia, 'Times New Roman', serif; background:linear-gradient(180deg,#f3ead9 0%,#f8f5ee 100%); color:var(--ink); }}
    main {{ max-width:1100px; margin:0 auto; padding:32px 24px 64px; }}
    h1,h2,h3 {{ margin:0 0 12px; }}
    .layout {{ display:grid; grid-template-columns: 320px 1fr; gap:24px; align-items:start; }}
    .card {{ background:var(--panel); border:1px solid var(--line); border-radius:18px; padding:18px; box-shadow:0 12px 36px rgba(78,55,28,0.08); }}
    .muted {{ color:var(--muted); }}
    .doc-item {{ display:block; padding:12px 14px; border-radius:14px; text-decoration:none; color:inherit; border:1px solid var(--line); margin-bottom:10px; background:#fffdf8; }}
    .doc-item:hover {{ border-color:#d7b98f; background:#fff8eb; }}
    .status {{ display:inline-block; padding:2px 8px; border-radius:999px; font-size:12px; background:#f3e0c0; }}
    input[type=password], input[type=text], select {{ width:100%; padding:10px 12px; border-radius:10px; border:1px solid #d7c3a8; margin-top:6px; margin-bottom:12px; box-sizing:border-box; }}
    input[type=file] {{ margin-top:8px; margin-bottom:12px; }}
    button {{ border:0; border-radius:999px; background:var(--accent); color:white; padding:10px 16px; cursor:pointer; }}
    button.secondary {{ background:#c97f3b; }}
    .preview {{ white-space:pre-wrap; background:#fffdf8; border:1px solid var(--line); border-radius:14px; padding:16px; min-height:320px; overflow:auto; }}
    table {{ width:100%; border-collapse:collapse; }}
    th, td {{ text-align:left; vertical-align:top; padding:10px 8px; border-bottom:1px solid var(--line); }}
    .alert {{ padding:12px 14px; border-radius:14px; background:#fff1df; border:1px solid #f0c38f; margin-bottom:16px; }}
    .toolbar a {{ margin-right:12px; }}
    @media (max-width: 900px) {{ .layout {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body><main>{body}</main></body></html>"""


def _render_document_list(store: LocalDocumentStore) -> str:
    items = []
    for record in store.list_documents():
        items.append(
            f"<a class='doc-item' href='/documents/{record.document_id}'>"
            f"<strong>{html.escape(record.original_name)}</strong><br>"
            f"<span class='muted'>{html.escape(record.file_format)} · {html.escape(record.created_at[:19])}</span><br>"
            f"<span class='status'>{html.escape(record.status)}</span>"
            "</a>"
        )
    return "".join(items) or "<p class='muted'>Nessun documento caricato.</p>"


def _preview_for_path(path_value: str) -> str:
    if not path_value:
        return "Anteprima non disponibile."
    path = Path(path_value)
    if not path.exists():
        return "File non disponibile."
    from persona.adapters.base import get_adapter_for_path

    return segments_to_preview_text(get_adapter_for_path(path).extract_segments(path))


def _render_findings_table(record) -> str:
    rows = []
    for match in record.hydrated_matches():
        checked = "checked" if match.approved else ""
        rows.append(
            "<tr>"
            f"<td><input type='checkbox' name='approve_{html.escape(match.match_id)}' value='1' {checked}></td>"
            f"<td><strong>{html.escape(match.original_value)}</strong><div class='muted'>{html.escape(match.context)}</div></td>"
            f"<td>{html.escape(match.entity_type)}<div class='muted'>{html.escape(match.reason or '')}</div></td>"
            f"<td>{match.score:.2f}</td>"
            f"<td>{html.escape(match.location)}</td>"
            f"<td><input type='text' name='masked_{html.escape(match.match_id)}' value='{html.escape(match.masked_value)}'></td>"
            "</tr>"
        )
    if not rows:
        return "<p class='muted'>Nessun blocco rilevato.</p>"
    return (
        "<table><thead><tr><th>OK</th><th>Blocco</th><th>Label / reason</th><th>Conf.</th><th>Posizione</th><th>Masked block</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _render_detail(store: LocalDocumentStore, record, message: str = "", view: str = "original") -> str:
    preview_path = record.censored_path if view == "anonymized" and record.censored_path else record.original_path
    preview_title = "Anteprima anonimizzata" if view == "anonymized" and record.censored_path else "Anteprima originale"
    message_html = f"<div class='alert'>{html.escape(message)}</div>" if message else ""
    restore_form = ""
    if record.censored_path and record.map_path:
        restore_form = f"""
        <form method="post" action="/documents/{record.document_id}/restore">
          <label>Password<input type="password" name="password" required></label>
          <label>Binding mode
            <select name="binding_mode">
              <option value="{PRAGMATIC_BINDING_MODE}">{PRAGMATIC_BINDING_MODE}</option>
              <option value="{STRICT_BINDING_MODE}">{STRICT_BINDING_MODE}</option>
            </select>
          </label>
          <button class="secondary" type="submit">Restore</button>
        </form>
        """
    return _page(
        f"Persona · {record.original_name}",
        f"""
        <div class="layout">
          <section class="card">
            <h1>I tuoi documenti</h1>
            <p class="muted">Archivio locale offline gestito da Persona.</p>
            {_render_document_list(store)}
            <hr style="border:none;border-top:1px solid #eadbc4;margin:18px 0;">
            <form method="post" action="/documents/upload" enctype="multipart/form-data">
              <label>Carica documento<input type="file" name="document" required></label>
              <label>Password<input type="password" name="password" required></label>
              <button type="submit">Carica e analizza</button>
            </form>
          </section>
          <section class="card">
            {message_html}
            <h2>{html.escape(record.original_name)}</h2>
            <p class="muted">Tipo {html.escape(record.file_format)} · Stato <span class="status">{html.escape(record.status)}</span></p>
            <div class="toolbar">
              <a href="/documents/{record.document_id}?view=original">Originale</a>
              <a href="/documents/{record.document_id}?view=anonymized">Anonimizzato</a>
            </div>
            <h3 style="margin-top:18px;">{preview_title}</h3>
            <div class="preview">{html.escape(_preview_for_path(preview_path))}</div>
            <h3 style="margin-top:18px;">Review blocchi sensibili</h3>
            <form method="post" action="/documents/{record.document_id}/review">
              {_render_findings_table(record)}
              <button type="submit" style="margin-top:14px;">Salva review</button>
            </form>
            <div style="margin-top:18px;">
              <form method="post" action="/documents/{record.document_id}/anonymize">
                <label>Password<input type="password" name="password" required></label>
                <button type="submit">Conferma anonimizzazione</button>
              </form>
              {restore_form}
            </div>
          </section>
        </div>
        """,
    )


def create_web_app(engine: PersonaEngine | None = None, store: LocalDocumentStore | None = None) -> FastAPI:
    app = FastAPI(title="Persona Local App")
    active_engine = engine or PersonaEngine()
    active_store = store or LocalDocumentStore()

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _page(
            "Persona",
            f"""
            <div class="layout">
              <section class="card">
                <h1>I tuoi documenti</h1>
                <p class="muted">Caricamento locale, review dei blocchi sensibili, anonimizzazione reversibile.</p>
                {_render_document_list(active_store)}
              </section>
              <section class="card">
                <h2>Nuovo documento</h2>
                <form method="post" action="/documents/upload" enctype="multipart/form-data">
                  <label>Documento<input type="file" name="document" required></label>
                  <label>Password<input type="password" name="password" required></label>
                  <button type="submit">Carica e analizza</button>
                </form>
              </section>
            </div>
            """,
        )

    @app.post("/documents/upload")
    async def upload_document(document: UploadFile = File(...), password: str = Form(...)) -> RedirectResponse:
        safe_name = Path(document.filename or "document").name
        suffix = Path(safe_name).suffix.lower()
        temp_path = active_store.root_dir / f"upload-{quote(Path(safe_name).stem)}{suffix}"
        temp_path.write_bytes(await document.read())
        try:
            record = active_store.create_document(temp_path, original_name=safe_name)
            session = active_engine.analyze_document(Path(record.original_path), password)
            record.matches = [match.to_dict() for match in session.matches]
            record.backend_name = active_engine.backend.name
            record.status = "review_pending"
            record.warnings = list(session.warnings)
            active_store.save_document(record)
        finally:
            if temp_path.exists():
                temp_path.unlink()
        return RedirectResponse(url=f"/documents/{record.document_id}", status_code=303)

    @app.get("/documents/{document_id}", response_class=HTMLResponse)
    async def document_detail(document_id: str, view: str = "original", message: str = "") -> str:
        record = active_store.load_document(document_id)
        return _render_detail(active_store, record, message=message, view=view)

    @app.post("/documents/{document_id}/review")
    async def save_review(document_id: str, request: Request) -> RedirectResponse:
        record = active_store.load_document(document_id)
        form = await request.form()
        updated_matches = []
        for match in record.hydrated_matches():
            match.approved = bool(form.get(f"approve_{match.match_id}"))
            match.masked_value = str(form.get(f"masked_{match.match_id}", match.masked_value))
            updated_matches.append(match)
        record.matches = [match.to_dict() for match in updated_matches]
        record.status = "reviewed"
        active_store.save_document(record)
        return RedirectResponse(url=f"/documents/{document_id}?message=Review+salvata", status_code=303)

    @app.post("/documents/{document_id}/anonymize")
    async def anonymize_document(document_id: str, password: str = Form(...)) -> RedirectResponse:
        record = active_store.load_document(document_id)
        result = active_engine.anonymize_with_matches(
            Path(record.original_path),
            password,
            record.hydrated_matches(),
            out_dir=active_store.censored_dir,
        )
        record.censored_path = result.output_file
        record.map_path = result.map_file
        record.status = "anonymized"
        active_store.save_document(record)
        return RedirectResponse(url=f"/documents/{document_id}?view=anonymized&message=Documento+anonimizzato", status_code=303)

    @app.post("/documents/{document_id}/restore")
    async def restore_document(
        document_id: str,
        password: str = Form(...),
        binding_mode: str = Form(PRAGMATIC_BINDING_MODE),
    ) -> RedirectResponse:
        record = active_store.load_document(document_id)
        result = active_engine.restore_document(
            Path(record.censored_path),
            Path(record.map_path),
            password,
            out_dir=active_store.restored_dir,
            binding_mode=binding_mode,
        )
        record.restored_path = result.output_file
        record.status = "restored"
        record.warnings = list(result.warnings)
        active_store.save_document(record)
        return RedirectResponse(url=f"/documents/{document_id}?message=Restore+completato", status_code=303)

    @app.exception_handler(PersonaError)
    async def persona_error_handler(_request: Request, exc: PersonaError) -> HTMLResponse:
        return HTMLResponse(_page("Persona error", f"<div class='card alert'>Errore: {html.escape(str(exc))}</div>"), status_code=400)

    return app
