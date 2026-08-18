"""Testes do PaperclipClient contra um transporte HTTP mockado (httpx.MockTransport) —
verificam o contrato de verdade da requisição HTTP (headers, corpo), não só a lógica
Python em volta dela. Complementa os outros testes, que usam um FakeClient e por isso
não pegam bugs no nível de "o que realmente sai na rede"."""
from __future__ import annotations

import functools

import httpx
import pytest

pytestmark = pytest.mark.asyncio


async def test_upload_attachment_manda_multipart_de_verdade(isolated_settings, monkeypatch, tmp_path):
    """Regressão de um bug achado ao vivo em 2026-08-18: upload_attachment mandava o
    arquivo como corpo bruto com Content-Type = mime do arquivo (ex.: text/markdown),
    em vez de multipart/form-data com um campo chamado "file". O multer do core
    (`upload.single("file")` em server/src/routes/issues.ts) nunca reconhecia esse
    corpo como upload de arquivo e sempre devolvia 400 "Missing file field 'file'" —
    o upload de anexo nunca tinha funcionado de verdade contra o core real, mascarado
    pelo try/except que só loga warning em _finalizar_como_head."""
    from harness import paperclip_client as pc_module
    from harness.paperclip_client import PaperclipClient

    capturado: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        capturado["content_type"] = request.headers.get("content-type", "")
        capturado["body"] = request.content
        return httpx.Response(201, json={"id": "att-1"})

    transport = httpx.MockTransport(_handler)
    monkeypatch.setattr(
        pc_module.httpx, "AsyncClient", functools.partial(httpx.AsyncClient, transport=transport)
    )

    client = PaperclipClient()
    p = tmp_path / "teste.md"
    p.write_text("# conteudo", encoding="utf-8")

    resultado = await client.upload_attachment(
        issue_id="issue-1",
        file_path=p,
        mime="text/markdown",
        filename="teste.md",
        company_id="company-1",
    )

    assert resultado == {"id": "att-1"}
    assert capturado["content_type"].startswith("multipart/form-data; boundary=")
    assert b'name="file"' in capturado["body"]
    assert b'filename="teste.md"' in capturado["body"]


async def test_requests_normais_continuam_json(isolated_settings, monkeypatch):
    """Regressão do fix acima: só chamadas com `files=` devem perder o
    Content-Type: application/json default — as normais (a imensa maioria) não podem
    ser afetadas."""
    from harness import paperclip_client as pc_module
    from harness.paperclip_client import PaperclipClient

    capturado: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        capturado["content_type"] = request.headers.get("content-type", "")
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(_handler)
    monkeypatch.setattr(
        pc_module.httpx, "AsyncClient", functools.partial(httpx.AsyncClient, transport=transport)
    )

    client = PaperclipClient()
    await client.health()

    assert capturado["content_type"] == "application/json"
