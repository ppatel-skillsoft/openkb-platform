import asyncio
from openkb.db import get_session
from openkb.db.metadata import documents, knowledge_bases
from sqlalchemy import select

async def main():
    async with get_session() as s:
        kb = (await s.execute(select(knowledge_bases.c.id, knowledge_bases.c.slug))).fetchone()
        print("KB:", kb)
        result = await s.execute(documents.insert().values(
            kb_id=kb[0],
            source_type="url",
            source_uri="https://mysite.com/page",
            status="pending",
        ))
        print("Inserted doc id:", result.inserted_primary_key)

asyncio.run(main())