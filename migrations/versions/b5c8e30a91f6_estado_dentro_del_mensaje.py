"""estado dentro del mensaje

Revision ID: b5c8e30a91f6
Revises: a2e6f1b83d40
Create Date: 2026-09-11 10:40:00.000000

Fase 5 de SPRINT_AREAS_V2.md (decisión N9). Responder y cambiar el estado
pasan a ser UN SOLO ACTO: el estado viaja dentro del mensaje que lo cambió.

`notatramite.estado_nuevo` guarda el estado que fijó ESE mensaje, vacío
cuando el mensaje no lo movió (siempre, del lado del trabajador).

Vive en la nota y no en una tabla aparte a propósito: separados es lo que
hacía que el chat mostrara dos movimientos por una sola respuesta del
sindicato. Con el estado adentro del mensaje no hay forma de que se
desincronicen.

No hay backfill posible ni deseable. Los cambios de estado viejos ya están
en el log como eventos "cambio_estado" propios, y el chat los sigue
mostrando así: reescribir el historial para que parezca que siempre fue de
esta manera sería inventar qué mensaje acompañó a cada cambio. Lo viejo
queda como fue; lo nuevo va junto.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'b5c8e30a91f6'
down_revision: Union[str, None] = 'a2e6f1b83d40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('notatramite', schema=None) as batch_op:
        batch_op.add_column(sa.Column('estado_nuevo', sqlmodel.sql.sqltypes.AutoString(),
                                      nullable=False, server_default=''))


def downgrade() -> None:
    with op.batch_alter_table('notatramite', schema=None) as batch_op:
        batch_op.drop_column('estado_nuevo')
