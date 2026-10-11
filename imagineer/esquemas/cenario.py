"""Os contratos do cenário e da fotografia (item 4.11, AF1): usados pelo dossiê da cena e pelo estado do elemento."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CampoDoCenario(BaseModel):
    """Um campo do cenário (item 4.11, AF1): o texto e de onde ele veio."""

    model_config = ConfigDict(extra="forbid")

    texto: str | None = Field(default=None, max_length=2000)
    origem: Literal["texto", "anterior", "sugerido"] = Field(
        default="texto",
        description="`texto`: o livro (ou a pessoa) disse; `anterior`: herdado da cena ou do capítulo anterior; `sugerido`: a IA sugeriu (enquadramento e lente).",
    )


class CenarioDaCena(BaseModel):
    """O cenário e a fotografia (item 4.11, AF1): ambiente, clima, luz, hora e estação, atmosfera, enquadramento e lente. Campo ausente = sem informação."""

    model_config = ConfigDict(extra="forbid")

    ambiente: CampoDoCenario | None = None
    clima: CampoDoCenario | None = None
    iluminacao: CampoDoCenario | None = None
    hora_e_estacao: CampoDoCenario | None = None
    atmosfera: CampoDoCenario | None = None
    enquadramento: CampoDoCenario | None = None
    lente: CampoDoCenario | None = None
