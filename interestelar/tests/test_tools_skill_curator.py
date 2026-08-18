"""Fase 7 — caso de teste que faltava: "Curador de Skills — fluxo completo" (mock de
fonte externa -> skills_pendentes/ -> ticket -> POST /aprovar-skill/nome -> skills/).

Nada de rede real nem Groq real: `_download_url` e `llm_client.chat_completion` são
substituídos por dublês; PaperclipClient por um FakeClient em memória."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

SKILL_NOME = "padrao-repositorio"
FONTE_FAKE = "# Conteúdo fake da fonte externa (Reversa/GitHub)\n\nRegra nova: usar snake_case."
SKILL_NOVA_MD = "# Padrão do Repositório\n\nRegra nova: usar snake_case.\n"


class FakeClient:
    """Dublê mínimo de PaperclipClient — só create_issue, que é o que o Curador usa."""

    def __init__(self):
        self.issues: list[dict] = []

    async def create_issue(self, title: str, description: str = "", **kw) -> dict:
        issue = {"id": f"issue-{len(self.issues) + 1}", "title": title, "description": description, **kw}
        self.issues.append(issue)
        return issue


@pytest.fixture
def curador_isolado(isolated_settings, tmp_path, monkeypatch):
    """Isola skills/ e skills_pendentes/ em tmp_path (mesmo cuidado do teste de
    /aprovar-skill em test_auth.py — os dois módulos usam Path("./skills*") relativo
    ao cwd)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "skills" / SKILL_NOME).mkdir(parents=True)
    (tmp_path / "skills" / SKILL_NOME / "SKILL.md").write_text(
        "# Padrão do Repositório\n\nVersão atual, sem a regra nova.\n", encoding="utf-8"
    )
    return tmp_path


async def test_ciclo_completo_propoe_skill_cria_ticket_e_salva_pendente(curador_isolado, monkeypatch):
    from harness import tools_skill_curator as curador

    async def _fake_download_url(url: str):
        return FONTE_FAKE

    async def _fake_chat_completion(system, user, **kw):
        return SKILL_NOVA_MD

    monkeypatch.setattr(curador, "_download_url", _fake_download_url)
    monkeypatch.setattr(curador.llm_client, "chat_completion", _fake_chat_completion)

    client = FakeClient()
    resultados = await curador.executar_ciclo_curadoria(client=client, skills=[SKILL_NOME])

    assert resultados == {SKILL_NOME: True}

    pendente = curador_isolado / "skills_pendentes" / SKILL_NOME / "SKILL.md"
    assert pendente.exists()
    assert pendente.read_text(encoding="utf-8") == SKILL_NOVA_MD

    # A skill aprovada (em skills/) não foi tocada pelo Curador — só quem aprova
    # (aprovar_skill) pode promover skills_pendentes/ -> skills/.
    aprovada = curador_isolado / "skills" / SKILL_NOME / "SKILL.md"
    assert "snake_case" not in aprovada.read_text(encoding="utf-8")

    assert len(client.issues) == 1
    ticket = client.issues[0]
    assert SKILL_NOME in ticket["title"]
    assert ticket["priority"] == "low"
    assert "/aprovar-skill/" + SKILL_NOME in ticket["description"]
    assert "+Regra nova: usar snake_case." in ticket["description"]  # diff unificado


async def test_hash_igual_ao_ultimo_aprovado_nao_repropoe(curador_isolado, monkeypatch):
    """Se a fonte não mudou desde a última aprovação (mesmo hash), o Curador não
    propõe de novo — não chama o LLM nem abre ticket novo."""
    from harness import tools_memoria as mem
    from harness import tools_skill_curator as curador

    async def _fake_download_url(url: str):
        return FONTE_FAKE

    monkeypatch.setattr(curador, "_download_url", _fake_download_url)
    # Hash calculado do mesmo jeito que o código real calcula (sobre `fontes`, a
    # string já com o wrapper "--- FONTE: url ---", não sobre o corpo bruto) — evita
    # duplicar essa lógica de montagem e o teste dessincronizar da implementação.
    fontes_esperado = await curador._baixar_fontes(curador.MANAGED_EXTERNAL_SKILLS[SKILL_NOME])
    hash_fonte = mem.hash_conteudo(fontes_esperado)
    await mem.registrar_proposta_skill(SKILL_NOME, hash_fonte)
    await mem.marcar_skill_aprovada(SKILL_NOME, aprovada_por="board")

    chamou_llm = False

    async def _fake_chat_completion(system, user, **kw):
        nonlocal chamou_llm
        chamou_llm = True
        return "não deveria rodar"

    monkeypatch.setattr(curador.llm_client, "chat_completion", _fake_chat_completion)

    client = FakeClient()
    resultados = await curador.executar_ciclo_curadoria(client=client, skills=[SKILL_NOME])

    assert resultados == {SKILL_NOME: False}
    assert chamou_llm is False
    assert client.issues == []
    assert not (curador_isolado / "skills_pendentes" / SKILL_NOME / "SKILL.md").exists()


async def test_fluxo_completo_ate_aprovacao_via_endpoint(curador_isolado, monkeypatch):
    """Ponta a ponta: fonte externa mockada -> Curador propõe -> skills_pendentes/ ->
    POST /aprovar-skill/{nome} -> promovida pra skills/ -> hash registrado como
    aprovado (não seria mais re-proposta com a mesma fonte)."""
    from fastapi.testclient import TestClient

    from harness import tools_memoria as mem
    from harness import tools_skill_curator as curador
    from harness.webhook import app

    async def _fake_download_url(url: str):
        return FONTE_FAKE

    async def _fake_chat_completion(system, user, **kw):
        return SKILL_NOVA_MD

    monkeypatch.setattr(curador, "_download_url", _fake_download_url)
    monkeypatch.setattr(curador.llm_client, "chat_completion", _fake_chat_completion)

    client = FakeClient()
    resultados = await curador.executar_ciclo_curadoria(client=client, skills=[SKILL_NOME])
    assert resultados == {SKILL_NOME: True}

    with TestClient(app) as tc:
        r = tc.post(f"/aprovar-skill/{SKILL_NOME}", params={"aprovada_por": "diego"})
    assert r.status_code == 200
    assert r.json()["applied"] is True

    promovida = curador_isolado / "skills" / SKILL_NOME / "SKILL.md"
    assert promovida.read_text(encoding="utf-8") == SKILL_NOVA_MD
    assert not (curador_isolado / "skills_pendentes" / SKILL_NOME / "SKILL.md").exists()

    fontes_esperado = await curador._baixar_fontes(curador.MANAGED_EXTERNAL_SKILLS[SKILL_NOME])
    hash_aprovado = await mem.obter_ultimo_hash_skill_aprovado(SKILL_NOME)
    assert hash_aprovado == mem.hash_conteudo(fontes_esperado)

    # Rodar o ciclo de novo com a mesma fonte não deveria re-propor.
    client2 = FakeClient()
    resultados2 = await curador.executar_ciclo_curadoria(client=client2, skills=[SKILL_NOME])
    assert resultados2 == {SKILL_NOME: False}
    assert client2.issues == []
