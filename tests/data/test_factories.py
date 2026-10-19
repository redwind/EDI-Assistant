from edi_assistant.core.models import FactoryAddress
from edi_assistant.data import FactoryStore
from edi_assistant.data.factories import factory_from_excel_footer


def test_store_and_suggest(tmp_path):
    s = FactoryStore(tmp_path / "f.json")
    assert s.list() == []
    f = FactoryAddress(id="", name="Sumec Textile Co., Ltd", address1="68 Yunlongshan Road")
    s.upsert(f)
    assert f.id and s.get(f.id).name == f.name
    s.upsert(FactoryAddress(id="", name="Other Garment Factory", address1="x", aliases=["OGF"]))
    got, score = s.suggest("SUMEC TEXTILE")
    assert got.id == f.id and score >= 0.5
    got, score = s.suggest("SUMEC TEXTILE COMPANY LIMITED")
    assert got.id == f.id and score == 1.0
    assert s.suggest("Unrelated Corp")[0] is None
    s.delete(f.id)
    assert len(s.list()) == 1


def test_footer():
    t = "SUMEC TEXTILE COMPANY LIMITED 68 Yunlongshan Road,Jianye District,Nanjing,China"
    f = factory_from_excel_footer(t)
    assert (f.name, f.address1, f.address2, f.city, f.country) == (
        "SUMEC TEXTILE COMPANY LIMITED", "68 Yunlongshan Road", "Jianye District", "Nanjing", "CHINA")
    wrapped = "TOTAL: 1\nSUMEC TEXTILE COMPANY LIMITED 68 Yunlongshan\nRoad,Jianye District,Nanjing,China"
    assert factory_from_excel_footer(wrapped).address1 == "68 Yunlongshan Road"
